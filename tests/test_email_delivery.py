"""How a message gets from _dispatch to Resend, and what happens when it does not.

The rest of the suite stubs the notify_* names on app.py, so nothing in it
reaches this machinery at all -- which is exactly why it was possible for
every send to be a bare daemon thread with no retry for as long as it was.
These tests drive notifications.py directly and never touch the network:
_send_via_resend is replaced with something that fails on demand.

The distinction that matters here is transient versus permanent. A 429 or a
502 is worth trying again; a 401 is a bad API key and a 403 is an unverified
sender, and repeating those three times only delays the log line that says
what is actually wrong.
"""

import urllib.error

import pytest

import notifications


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    """A key has to look present or _send takes the dry-run path."""
    monkeypatch.setenv("RESEND_API_KEY", "pytest-not-a-real-key")


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """Record the backoff instead of serving it."""
    slept = []
    monkeypatch.setattr(notifications.time, "sleep", slept.append)
    return slept


def _http_error(code):
    return urllib.error.HTTPError(
        notifications.RESEND_ENDPOINT, code, "boom", hdrs=None, fp=None)


def _failing(times, exc, calls):
    """A sender that raises `exc` the first `times` calls, then succeeds."""
    def send(cfg, to_addr, subject, html, text, reply_to=None):
        calls.append(to_addr)
        if len(calls) <= times:
            raise exc
        return {"id": "sent-after-%s" % (len(calls) - 1)}
    return send


def test_a_transient_failure_is_retried_and_can_succeed(monkeypatch, no_sleeping):
    calls = []
    monkeypatch.setattr(notifications, "_send_via_resend",
                        _failing(2, _http_error(502), calls))

    assert notifications._send("a@example.com", "s", "<p>h</p>", "t") is True
    assert len(calls) == 3            # two failures then the delivery
    assert len(no_sleeping) == 2      # backed off between them
    assert no_sleeping == sorted(no_sleeping)   # and backed off further each time


def test_a_rate_limit_is_treated_as_transient(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "_send_via_resend",
                        _failing(1, _http_error(429), calls))
    assert notifications._send("a@example.com", "s", "<p>h</p>", "t") is True
    assert len(calls) == 2


def test_a_network_error_is_treated_as_transient(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "_send_via_resend",
                        _failing(1, urllib.error.URLError("no route"), calls))
    assert notifications._send("a@example.com", "s", "<p>h</p>", "t") is True
    assert len(calls) == 2


@pytest.mark.parametrize("code", [401, 403, 422])
def test_a_permanent_failure_is_not_retried(monkeypatch, no_sleeping, code):
    """A bad key or an unverified sender fails the same way every time."""
    calls = []
    monkeypatch.setattr(notifications, "_send_via_resend",
                        _failing(99, _http_error(code), calls))

    assert notifications._send("a@example.com", "s", "<p>h</p>", "t") is False
    assert len(calls) == 1
    assert no_sleeping == []


def test_it_gives_up_rather_than_retrying_forever(monkeypatch, no_sleeping):
    calls = []
    monkeypatch.setattr(notifications, "_send_via_resend",
                        _failing(99, _http_error(500), calls))

    assert notifications._send("a@example.com", "s", "<p>h</p>", "t") is False
    assert len(calls) == notifications.MAX_SEND_ATTEMPTS


def test_a_missing_recipient_is_not_sent_anywhere(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "_send_via_resend",
                        _failing(0, None, calls))
    assert notifications._send("", "s", "<p>h</p>", "t") is False
    assert calls == []


def test_dispatch_returns_immediately_and_the_workers_deliver(monkeypatch):
    """The point of the queue: the caller does not wait for Resend."""
    delivered = []

    def send(cfg, to_addr, subject, html, text, reply_to=None):
        delivered.append(to_addr)
        return {"id": "ok"}

    monkeypatch.setattr(notifications, "_send_via_resend", send)

    for i in range(5):
        notifications._dispatch(f"{i}@example.com", "s", "<p>h</p>", "t")

    # _drain is what runs at exit; here it doubles as "wait for the workers".
    assert notifications._drain(timeout=10) is True
    assert sorted(delivered) == [f"{i}@example.com" for i in range(5)]


def test_the_pool_is_fixed_rather_than_a_thread_per_message(monkeypatch):
    """The old shape started one daemon thread per email."""
    monkeypatch.setattr(notifications, "_send_via_resend",
                        lambda *a, **k: {"id": "ok"})

    for i in range(25):
        notifications._dispatch(f"{i}@example.com", "s", "<p>h</p>", "t")
    notifications._drain(timeout=10)

    assert len(notifications._workers) == notifications.EMAIL_WORKERS
    assert all(t.is_alive() for t in notifications._workers)


def test_a_full_queue_drops_rather_than_blocking_the_request(monkeypatch):
    """A provider outage must not stall the web request that produced the mail.

    The full queue is faked rather than actually filled: any worker started
    by an earlier test re-reads the module global each time round its loop,
    so a real one would race with them over who empties it.
    """
    class Full:
        def put_nowait(self, item):
            raise notifications.queue.Full()

    monkeypatch.setattr(notifications, "_queue", Full())
    monkeypatch.setattr(notifications, "_ensure_workers", lambda: None)

    # Does not raise, and does not block: the caller is a request handler.
    notifications._dispatch("overflow@example.com", "s", "<p>h</p>", "t")


def test_no_key_takes_the_dry_run_path_without_sending(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr(notifications, "_send_via_resend",
                        _failing(0, None, calls))
    assert notifications._send("a@example.com", "s", "<p>h</p>", "t") is True
    assert calls == []
