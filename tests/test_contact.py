"""The homepage contact form.

It posted to /api/contact from the day it was written, and that route did not
exist. Worse than a 404: static_url_path is "" so the static route claims the
path for GET, and a POST therefore returned Flask's HTML 405 -- which
common.js's api() cannot parse, so the visitor saw the string
"Could not send message (405)" and the message was gone.
"""


def _post(client, **overrides):
    payload = {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "",
        "message": "We run a food bank and are looking for delivery help.",
    }
    payload.update(overrides)
    return client.post("/api/contact", json=payload)


def test_a_complete_message_is_accepted(client):
    assert _post(client).status_code == 200


def test_missing_fields_are_named(client):
    response = _post(client, name="", message="")
    assert response.status_code == 400
    error = response.get_json()["error"]
    assert "your name" in error and "a message" in error


def test_a_malformed_address_is_rejected(client):
    response = _post(client, email="not-an-address")
    assert response.status_code == 400
    assert response.get_json()["field"] == "email"


def test_an_over_length_message_is_rejected(client):
    response = _post(client, message="m" * 5000)
    assert response.status_code == 400
    assert response.get_json()["field"] == "message"


def test_the_honeypot_looks_like_success_and_sends_nothing(client, outbox):
    """Same shape /register's honeypot uses: a bot learns nothing from the
    response, and nothing is sent."""
    response = _post(client, website="http://spam.example")
    assert response.status_code == 200
    assert not [s for s in outbox if s[0] == "notify_contact_message"]


def test_a_real_message_is_dispatched(client, outbox):
    _post(client)
    sent = [s for s in outbox if s[0] == "notify_contact_message"]
    assert len(sent) == 1
    assert sent[0][2]["email"] == "ada@example.com"


def test_the_form_is_rate_limited(client):
    for _ in range(5):
        assert _post(client).status_code == 200
    assert _post(client).status_code == 429


def test_an_unknown_api_path_answers_a_post_in_json(client):
    """The failure mode that hid this bug. Flask's default 405 is an HTML
    document, which api() cannot turn into a message."""
    response = client.post("/api/definitely-not-a-route", json={})
    assert response.status_code == 405
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.get_json()["error"]
