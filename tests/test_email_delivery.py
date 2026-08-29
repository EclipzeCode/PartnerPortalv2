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
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

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




def test_no_key_takes_the_dry_run_path_without_sending(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr(notifications, "_send_via_resend",
                        _failing(0, None, calls))
    assert notifications._send("a@example.com", "s", "<p>h</p>", "t") is True
    assert calls == []


# --- The outbox -------------------------------------------------------------
# What replaced the in-memory queue. The queue lost everything it was holding
# when the process died, and because sending is off the request path the
# person who caused the message had already been shown a success -- so a
# password reset could simply never arrive and nobody would learn that it had
# not. These are about the message surviving that.
#
# Split in two on purpose. The threading tests below use a fake store,
# because what they assert is about workers rather than about SQL; the store
# tests after them drive the real table single-threaded, because what they
# assert is the SQL.

class FakeOutbox:
    """The six operations delivery needs, in a dict."""

    def __init__(self):
        self.rows = {}
        self.next_id = 1
        self.lock = __import__("threading").Lock()

    def add(self, to_addr, subject, html, text, reply_to=None):
        with self.lock:
            message_id = self.next_id
            self.next_id += 1
            self.rows[message_id] = {
                "id": message_id, "to_addr": to_addr, "subject": subject,
                "html": html, "text": text, "reply_to": reply_to,
                "status": "queued", "attempts": 0, "error": None,
            }
            return message_id

    def claim(self):
        with self.lock:
            for row in self.rows.values():
                if row["status"] == "queued":
                    row["status"] = "sending"
                    row["attempts"] += 1
                    return notifications._Claim((
                        row["id"], row["to_addr"], row["subject"], row["html"],
                        row["text"], row["reply_to"], row["attempts"]))
            return None

    def delivered(self, message_id):
        with self.lock:
            self.rows[message_id]["status"] = "delivered"

    def retry_later(self, message_id, error, delay_seconds):
        with self.lock:
            self.rows[message_id].update(status="queued", error=error)

    def give_up(self, message_id, error):
        with self.lock:
            self.rows[message_id].update(status="failed", error=error)

    def maintain(self):
        return 0

    def outstanding(self):
        with self.lock:
            return sum(1 for r in self.rows.values()
                       if r["status"] in ("queued", "sending"))


@pytest.fixture
def fake_outbox(monkeypatch):
    """A store with no database behind it, and no workers left running after.

    Stopping them matters: a worker that outlived its test would spend the
    rest of the session polling the real outbox and claiming rows other
    tests are asserting on.
    """
    store = FakeOutbox()
    monkeypatch.setattr(notifications, "_outbox", store)
    try:
        yield store
    finally:
        notifications._stop_workers()


def test_dispatch_returns_immediately_and_the_workers_deliver(
        monkeypatch, fake_outbox):
    """The point of the whole arrangement: the caller does not wait for Resend."""
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
    assert all(r["status"] == "delivered" for r in fake_outbox.rows.values())


def test_the_message_is_written_down_before_anything_tries_to_send_it(
        fake_outbox, monkeypatch):
    """The row is what makes it survive the process.

    Workers are never started here, so nothing delivers anything -- and the
    message is still on record afterward, which is exactly the state the old
    queue could not represent.
    """
    monkeypatch.setattr(notifications, "_ensure_workers", lambda: None)

    message_id = notifications._dispatch(
        "durable@example.com", "s", "<p>h</p>", "t")

    assert message_id is not None
    assert fake_outbox.rows[message_id]["status"] == "queued"
    assert fake_outbox.outstanding() == 1


def test_the_pool_is_fixed_rather_than_a_thread_per_message(
        monkeypatch, fake_outbox):
    """The original shape started one daemon thread per email."""
    monkeypatch.setattr(notifications, "_send_via_resend",
                        lambda *a, **k: {"id": "ok"})

    for i in range(25):
        notifications._dispatch(f"{i}@example.com", "s", "<p>h</p>", "t")
    notifications._drain(timeout=10)

    assert len(notifications._workers) == notifications.EMAIL_WORKERS
    assert all(t.is_alive() for t in notifications._workers)


def test_a_store_that_cannot_be_written_does_not_break_the_caller(monkeypatch):
    """The caller is a request handler, and the action it is notifying about
    has already succeeded. A database that cannot be reached is not a reason
    to fail the proposal that was just created."""
    class Broken:
        def add(self, *a, **k):
            raise RuntimeError("database is on fire")

    monkeypatch.setattr(notifications, "_outbox", Broken())
    monkeypatch.setattr(notifications, "_ensure_workers", lambda: None)

    # Does not raise, and says so by returning nothing.
    assert notifications._dispatch("x@example.com", "s", "<p>h</p>", "t") is None


def test_a_message_with_no_recipient_is_not_written_down(fake_outbox):
    notifications._dispatch("", "s", "<p>h</p>", "t")
    assert fake_outbox.rows == {}


def test_a_failure_defers_the_message_rather_than_dropping_it(
        monkeypatch, fake_outbox):
    """A message that could not be sent goes back in the table.

    The old queue had nowhere to put it: once the three in-call attempts were
    spent the message was gone.
    """
    monkeypatch.setattr(notifications, "_send", lambda *a, **k: False)
    monkeypatch.setattr(notifications, "_ensure_workers", lambda: None)

    message_id = notifications._dispatch("x@example.com", "s", "<p>h</p>", "t")
    notifications._deliver(fake_outbox.claim())

    assert fake_outbox.rows[message_id]["status"] == "queued"
    assert fake_outbox.rows[message_id]["attempts"] == 1


def test_it_stops_after_a_bounded_number_of_rounds(monkeypatch, fake_outbox):
    """Deferring forever is its own failure mode: a message nobody can
    deliver must not be retried until the end of time."""
    monkeypatch.setattr(notifications, "_send", lambda *a, **k: False)
    monkeypatch.setattr(notifications, "_ensure_workers", lambda: None)

    message_id = notifications._dispatch("x@example.com", "s", "<p>h</p>", "t")
    for _ in range(notifications.MAX_DELIVERY_ROUNDS):
        notifications._deliver(fake_outbox.claim())

    row = fake_outbox.rows[message_id]
    assert row["status"] == "failed"
    assert row["attempts"] == notifications.MAX_DELIVERY_ROUNDS
    # And the reason is on the row, rather than only in a log line.
    assert "gave up" in row["error"]


# --- The store itself -------------------------------------------------------
# Driven single-threaded against the real table, because what is being
# asserted here is the SQL: the claim that two workers cannot both take,
# the backoff that makes a row wait, and the release that recovers a message
# from a process that died holding it.

@pytest.fixture
def store(connection, monkeypatch):
    """The real DatabaseOutbox, pointed at the test's transaction.

    Its own _session is what gets replaced rather than SessionLocal, so the
    SQL underneath -- FOR UPDATE SKIP LOCKED and all -- is exactly what
    production runs.

    The table is emptied first, inside the transaction that is about to be
    rolled back. Without it a row left queued by a local dev run would be
    visible to claim() and these tests would be asserting on somebody else's
    mail.
    """
    from sqlalchemy.orm import Session

    def _session(self):
        return Session(bind=connection, join_transaction_mode="create_savepoint",
                       expire_on_commit=False)

    monkeypatch.setattr(notifications.DatabaseOutbox, "_session", _session)
    outbox = notifications.DatabaseOutbox()
    db = outbox._session()
    try:
        db.execute(sa.text("DELETE FROM email_outbox"))
        db.commit()
    finally:
        db.close()
    return outbox


def _row(store, message_id):
    from models import EmailOutbox
    db = store._session()
    try:
        return db.get(EmailOutbox, message_id)
    finally:
        db.close()


def test_a_queued_message_is_on_the_table_before_anyone_sends_it(store):
    message_id = store.add("a@example.com", "Subject", "<p>h</p>", "t")
    row = _row(store, message_id)
    assert row.status == "queued"
    assert row.to_addr == "a@example.com"
    assert row.body_text == "t"
    assert row.attempts == 0


def test_claiming_takes_one_message_and_counts_the_attempt(store):
    store.add("a@example.com", "s", "<p>h</p>", "t")

    claimed = store.claim()
    assert claimed is not None
    assert claimed.to_addr == "a@example.com"
    assert claimed.attempts == 1
    assert _row(store, claimed.id).status == "sending"

    # And nobody else can take it -- which is what stops the two gunicorn
    # workers from both sending the same email.
    assert store.claim() is None


def test_messages_are_claimed_oldest_first(store):
    first = store.add("1@example.com", "s", "<p>h</p>", "t")
    second = store.add("2@example.com", "s", "<p>h</p>", "t")
    assert store.claim().id == first
    assert store.claim().id == second


def test_delivering_closes_the_row_out(store):
    message_id = store.add("a@example.com", "s", "<p>h</p>", "t")
    store.claim()
    store.delivered(message_id)

    row = _row(store, message_id)
    assert row.status == "delivered"
    assert row.delivered_at is not None
    assert row.claimed_at is None
    assert store.outstanding() == 0


def test_a_deferred_message_waits_out_its_backoff_before_it_can_be_claimed(store):
    message_id = store.add("a@example.com", "s", "<p>h</p>", "t")
    store.claim()
    store.retry_later(message_id, "502 from the provider", delay_seconds=600)

    row = _row(store, message_id)
    assert row.status == "queued"
    assert row.last_error == "502 from the provider"
    # Queued again, but not yet: claiming now would be a retry with no backoff.
    assert store.claim() is None
    # It is still outstanding -- deferred is not delivered.
    assert store.outstanding() == 1


def test_a_message_due_again_is_claimable(store):
    message_id = store.add("a@example.com", "s", "<p>h</p>", "t")
    store.claim()
    store.retry_later(message_id, "transient", delay_seconds=-60)
    claimed = store.claim()
    assert claimed is not None
    assert claimed.attempts == 2


def test_a_claim_held_by_a_process_that_died_is_released(store):
    """The recovery the whole table exists for.

    A row that says `sending` with nobody sending it belonged to a worker
    that is gone. Under the old queue this message did not exist at all.
    """
    from models import EmailOutbox

    message_id = store.add("a@example.com", "s", "<p>h</p>", "t")
    store.claim()
    assert store.claim() is None          # held

    # Backdate the claim to before the timeout, as a dead worker's would be.
    db = store._session()
    try:
        db.query(EmailOutbox).filter(EmailOutbox.id == message_id).update({
            "claimed_at": datetime.now(timezone.utc) - timedelta(
                seconds=notifications.CLAIM_TIMEOUT_SECONDS + 60),
        }, synchronize_session=False)
        db.commit()
    finally:
        db.close()

    assert store.maintain() == 1
    recovered = store.claim()
    assert recovered is not None
    assert recovered.id == message_id


def test_a_fresh_claim_is_not_taken_away_from_the_worker_holding_it(store):
    """A slow send is still a send. Releasing it would mail twice."""
    store.add("a@example.com", "s", "<p>h</p>", "t")
    store.claim()
    assert store.maintain() == 0
    assert store.claim() is None


def test_giving_up_leaves_the_reason_on_the_row(store):
    message_id = store.add("a@example.com", "s", "<p>h</p>", "t")
    store.claim()
    store.give_up(message_id, "403: sender not verified")

    row = _row(store, message_id)
    assert row.status == "failed"
    assert row.last_error == "403: sender not verified"
    # Failed is not outstanding: nothing is going to send it.
    assert store.outstanding() == 0


def test_delivered_rows_are_tidied_away_once_they_have_aged_out(store):
    from models import EmailOutbox

    keep = store.add("recent@example.com", "s", "<p>h</p>", "t")
    old = store.add("old@example.com", "s", "<p>h</p>", "t")
    store.delivered(keep)
    store.delivered(old)

    db = store._session()
    try:
        db.query(EmailOutbox).filter(EmailOutbox.id == old).update({
            "delivered_at": datetime.now(timezone.utc) - timedelta(
                days=notifications.OUTBOX_RETENTION_DAYS + 1),
        }, synchronize_session=False)
        db.commit()
    finally:
        db.close()

    store.maintain()
    assert _row(store, keep) is not None
    assert _row(store, old) is None
