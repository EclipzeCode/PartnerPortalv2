"""Small rules that had stopped being true.

None of these produced an error page. A rate limiter that never forgets a key
still limits correctly, a view counter that recounts the same visitor still
returns a number, and a settings endpoint that saves nothing still answers
200 -- which is exactly why they are worth a test rather than a glance.
"""

import time

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
    org = make_org()
    login(org)
    response = client.patch("/api/settings", json={"email_notifications": False})
    assert response.status_code == 200
    assert response.get_json()["organization"]["email_notifications"] is False


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

    total, _recent = app_module._profile_view_counts(
        app_module.get_db(), target)
    assert total == 1
