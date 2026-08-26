"""The homepage contact form.

It posted to /api/contact from the day it was written, and that route did not
exist. Worse than a 404: static_url_path is "" so the static route claims the
path for GET, and a POST therefore returned Flask's HTML 405 -- which
common.js's api() cannot parse, so the visitor saw the string
"Could not send message (405)" and the message was gone.
"""

import pytest


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


# --- Storage ---------------------------------------------------------------
# The form was delivered by email and kept nowhere, which held up exactly
# until the mail stopped going -- and it has not gone for as long as the
# sending domain has been unverified. Every message went nowhere while the
# sender was shown a success.

def _messages(session):
    from models import ContactMessage
    return session.query(ContactMessage).order_by(ContactMessage.id).all()


def test_a_message_is_written_down(client, session):
    response = client.post("/api/contact", json={
        "name": "Ada", "email": "ada@example.com",
        "phone": "555-0100", "message": "Can we talk about a partnership?",
    })
    assert response.status_code == 200

    stored = _messages(session)[-1]
    assert stored.name == "Ada"
    assert stored.email == "ada@example.com"
    assert stored.phone == "555-0100"
    assert stored.message == "Can we talk about a partnership?"
    # Null is the queue; a timestamp is the record.
    assert stored.handled_at is None
    assert stored.created_at is not None


def test_it_is_stored_even_when_the_mail_goes_nowhere(client, session, monkeypatch):
    """The entire reason this table exists.

    Delivery is queued and its failures are swallowed by design -- the
    visitor's action has already succeeded. That is right, and it is why the
    only durable copy has to be written before the send is attempted.
    """
    import app as app_module

    def explode(**kwargs):
        raise RuntimeError("no verified sending domain")

    monkeypatch.setattr(app_module, "notify_contact_message", explode)

    before = len(_messages(session))
    with pytest.raises(RuntimeError):
        client.post("/api/contact", json={
            "name": "Grace", "email": "grace@example.com",
            "message": "Nothing will deliver this.",
        })
    after = _messages(session)
    assert len(after) == before + 1
    assert after[-1].email == "grace@example.com"


def test_the_honeypot_stores_nothing(client, session):
    """A bot is answered as a success and must not fill the queue."""
    before = len(_messages(session))
    response = client.post("/api/contact", json={
        "name": "Bot", "email": "bot@example.com", "message": "buy things",
        "website": "http://spam.example",
    })
    assert response.status_code == 200
    assert len(_messages(session)) == before


@pytest.mark.parametrize("body", [
    {"name": "", "email": "a@example.com", "message": "hi"},
    {"name": "A", "email": "nonsense", "message": "hi"},
    {"name": "A", "email": "a@example.com", "message": ""},
])
def test_a_rejected_message_stores_nothing(client, session, body):
    before = len(_messages(session))
    assert client.post("/api/contact", json=body).status_code == 400
    assert len(_messages(session)) == before


def test_no_address_is_recorded(session):
    """The rest of this schema does not record who somebody is unless it has
    to -- profile views are a salted digest for that reason -- and the
    honeypot and the per-connection limit already do the abuse work an IP
    would be kept for."""
    from models import ContactMessage
    assert not any(
        "ip" in column.name or "address" in column.name
        for column in ContactMessage.__table__.columns
    )
