"""Small rules that had stopped being true.

None of these produced an error page. A rate limiter that never forgets a key
still limits correctly, a view counter that recounts the same visitor still
returns a number, and a settings endpoint that saves nothing still answers
200 -- which is exactly why they are worth a test rather than a glance.
"""

import time

import pytest

import app as app_module


def test_rate_buckets_do_not_grow_without_bound():
    """Keys that can no longer affect any limit are dropped.

    /forgot-password is keyed by email address, so the key space is chosen by
    whoever is calling. Nothing removed an entry once it existed.
    """
    app_module._rate_buckets.clear()
    app_module._rate_sweep_after = 0.0

    now = time.time()
    # Older than the longest window any caller passes.
    stale = now - app_module.RATE_MAX_WINDOW - 60
    for i in range(50):
        app_module._rate_buckets[("forgot_password_email", f"old{i}")] = [stale]
    # Recent enough to still count against a limit.
    app_module._rate_buckets[("login", "current")] = [now]

    app_module._sweep_rate_buckets(now)

    remaining = set(app_module._rate_buckets)
    assert ("login", "current") in remaining
    assert not [k for k in remaining if k[1].startswith("old")]


def test_the_sweep_does_not_run_on_every_call():
    """It walks the whole dict, so the common case must not pay for it."""
    app_module._rate_buckets.clear()
    app_module._rate_sweep_after = 0.0
    now = time.time()

    app_module._sweep_rate_buckets(now)
    app_module._rate_buckets[("login", "stale")] = [now - 99999]
    # Immediately after a sweep, another one is not due yet.
    app_module._sweep_rate_buckets(now)
    assert ("login", "stale") in app_module._rate_buckets

    app_module._sweep_rate_buckets(now + app_module.RATE_SWEEP_INTERVAL + 1)
    assert ("login", "stale") not in app_module._rate_buckets


def test_a_live_limit_survives_a_sweep(client, make_org):
    """The sweep must not hand back attempts that should still be blocked."""
    make_org()
    for _ in range(20):
        client.post("/login", json={"email": "nobody@example.com", "password": "x"})
    app_module._sweep_rate_buckets(time.time())
    response = client.post(
        "/login", json={"email": "nobody@example.com", "password": "x"})
    assert response.status_code == 429


def test_settings_refuses_a_body_it_understands_nothing_in(client, make_org, login):
    """"Settings saved" for a request that saved nothing is a success message
    for something that did not happen."""
    login(make_org())
    response = client.patch("/api/settings", json={"nonexistent_setting": True})
    assert response.status_code == 400
    assert "known setting" in response.get_json()["error"]


def test_settings_still_saves_what_it_does_understand(client, make_org, login):
    """The old all-or-nothing switch still means all of it.

    It predates the per-category preferences and is what any older client
    sends, so it sets every category rather than becoming a fourth thing
    alongside them that nothing consults.
    """
    org = make_org()
    login(org)
    response = client.patch("/api/settings", json={"email_notifications": False})
    assert response.status_code == 200
    prefs = response.get_json()["organization"]["email_preferences"]
    assert prefs == {"proposals": False, "messages": False, "partnerships": False}


def test_the_view_salt_is_independent_of_the_secret_key(client, make_org):
    """Dedup used to be salted with app.secret_key. Without SECRET_KEY set
    that is regenerated every restart, so every returning visitor counted
    again and the dashboard number was restarts as much as visitors."""
    target = make_org()

    client.get(f"/api/organizations/{target.id}/public")
    client.get(f"/api/organizations/{target.id}/public")

    original = app_module.app.secret_key
    try:
        app_module.app.secret_key = "a-different-key-entirely"
        client.get(f"/api/organizations/{target.id}/public")
    finally:
        app_module.app.secret_key = original

    total, _recent, _series, _prior = app_module._profile_view_stats(
        app_module.get_db(), target)
    assert total == 1


# --- Saying how long -------------------------------------------------------
# Every limit here used to end with some version of "please try again in a
# while" -- eleven vaguenesses for a number the server knew exactly.

def test_a_refusal_says_how_long_in_the_body_and_the_header(client):
    for _ in range(5):
        client.post("/api/contact", json={
            "name": "T", "email": "t@example.com", "message": "hi"})
    response = client.post("/api/contact", json={
        "name": "T", "email": "t@example.com", "message": "hi"})

    assert response.status_code == 429
    payload = response.get_json()
    assert payload["retry_after"] > 0
    # The standard header carries the same fact, for the readers that are not
    # going to parse an English sentence out of the body.
    assert response.headers["Retry-After"] == str(payload["retry_after"])
    assert "Try again in about" in payload["error"]


def test_the_wait_is_measured_from_the_oldest_attempt_that_still_counts(client):
    """The limit clears when the oldest attempt inside the window ages out,
    which is the moment there is room for one more."""
    app_module._rate_buckets.clear()
    app_module._rate_sweep_after = 0.0

    assert app_module.rate_limited("probe", "k", 2, 900) == 0
    assert app_module.rate_limited("probe", "k", 2, 900) == 0
    wait = app_module.rate_limited("probe", "k", 2, 900)
    # Both attempts landed just now, so the first ages out in ~the window.
    assert 890 <= wait <= 900


def test_zero_reads_as_allowed(client):
    """The return moved from a boolean to seconds, and every existing
    `if rate_limited(...)` had to keep meaning the same thing."""
    app_module._rate_buckets.clear()
    assert not app_module.rate_limited("probe2", "k", 5, 900)
    assert not app_module.rate_limit_reached("probe2", "k", 5, 900)


def test_checking_still_does_not_spend_the_budget(client):
    """rate_limit_reached returns seconds now too, and must still not count
    the asking -- checking would spend the thing being checked."""
    app_module._rate_buckets.clear()
    for _ in range(20):
        assert app_module.rate_limit_reached("probe3", "k", 2, 900) == 0
    app_module.rate_limited("probe3", "k", 2, 900)
    app_module.rate_limited("probe3", "k", 2, 900)
    assert app_module.rate_limit_reached("probe3", "k", 2, 900) > 0


@pytest.mark.parametrize("seconds,expected", [
    (1, "in a moment"),
    (45, "in a moment"),
    (46, "in about a minute"),
    (90, "in about 2 minutes"),
    (900, "in about 15 minutes"),
    (3600, "in about an hour"),
    (7200, "in about 2 hours"),
])
def test_the_wait_is_rounded_up_not_reported_to_the_second(seconds, expected):
    """Being told five minutes and waiting six is worse than the reverse."""
    assert app_module._human_wait(seconds) == expected
