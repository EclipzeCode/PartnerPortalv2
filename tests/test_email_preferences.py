"""Which emails an organization gets, by category.

One boolean used to cover all of it, which made the only way to stop a busy
message thread reaching your inbox also the way to stop hearing that somebody
had proposed a partnership. Those are not the same decision, and the second is
the thing this product exists to deliver -- so the switch people would
actually reach for turned off the one they came for.

The rules these pin: an absent key means yes, only an explicit false is
silence, a category turned off silences that category and nothing else, and
account-security mail ignores the whole mechanism.
"""

import pytest

from models import Organization


# --- The rule itself -------------------------------------------------------

def test_nothing_stored_means_everything_on(make_org):
    """A new account has chosen nothing, and hears about everything."""
    org = make_org()
    assert org.email_preferences == {}
    for category in Organization.EMAIL_CATEGORIES:
        assert org.wants_email(category) is True


def test_only_an_explicit_false_is_silence(make_org):
    org = make_org(email_preferences={"messages": False})
    assert org.wants_email("messages") is False
    # The two nobody mentioned are untouched.
    assert org.wants_email("proposals") is True
    assert org.wants_email("partnerships") is True


def test_an_unknown_category_defaults_to_sending(make_org):
    """Fails toward sending, not toward silence.

    An email nobody wanted is one somebody deletes. An email that was never
    sent is an organization never learning a partnership was proposed to
    them -- and there is no other channel that would tell them.
    """
    org = make_org(email_preferences={})
    assert org.wants_email("a_category_from_a_later_release") is True


def test_a_malformed_value_does_not_silence(make_org):
    """Same direction, for a row written by something that got it wrong."""
    org = make_org(email_preferences={"messages": "no"})
    assert org.wants_email("messages") is True


# --- The API ---------------------------------------------------------------

def test_a_category_can_be_turned_off(client, login, make_org, session):
    org = make_org()
    login(org)
    response = client.patch("/api/settings", json={
        "email_preferences": {"messages": False},
    })
    assert response.status_code == 200
    assert response.get_json()["organization"]["email_preferences"] == {
        "proposals": True, "messages": False, "partnerships": True,
    }
    session.refresh(org)
    assert org.wants_email("messages") is False


def test_saving_one_category_leaves_the_others_alone(client, login, make_org):
    """Partial by design, like the rest of this endpoint.

    The settings page sends only the switch that moved, so a stale page open
    in another tab cannot overwrite a change made here.
    """
    login(make_org(email_preferences={"proposals": False}))
    response = client.patch("/api/settings", json={
        "email_preferences": {"messages": False},
    })
    prefs = response.get_json()["organization"]["email_preferences"]
    assert prefs == {"proposals": False, "messages": False, "partnerships": True}


def test_a_category_can_be_turned_back_on(client, login, make_org):
    login(make_org(email_preferences={"proposals": False}))
    response = client.patch("/api/settings", json={
        "email_preferences": {"proposals": True},
    })
    assert response.get_json()["organization"]["email_preferences"]["proposals"] is True


@pytest.mark.parametrize("body", [
    {"email_preferences": {"nonsense": False}},
    {"email_preferences": {"messages": "false"}},
    {"email_preferences": {"messages": 0}},
    {"email_preferences": []},
])
def test_a_body_that_does_not_mean_anything_is_refused(
        client, login, make_org, body):
    """Rejected rather than guessed at: "false" and 0 are both things a client
    might send and both read wrong under bool()."""
    login(make_org())
    assert client.patch("/api/settings", json=body).status_code == 400


def test_the_payload_resolves_the_defaults(client, login, make_org):
    """The column stores only what was chosen; the API answers all three.

    A settings page that had to know "absent means yes" in order to draw a
    switch is a second place for that rule to be got wrong.
    """
    login(make_org(email_preferences={}))
    prefs = client.get("/api/me").get_json()["organization"]["email_preferences"]
    assert prefs == {"proposals": True, "messages": True, "partnerships": True}


# --- What actually gets sent -----------------------------------------------

def _pending(client, login, make_org, **recipient_prefs):
    """A proposal from one org to another, and the recipient's preferences."""
    recipient = make_org(offers=["mentors"], needs=["web_development"],
                         **recipient_prefs)
    proposer = make_org(offers=["web_development"], needs=["mentors"])
    login(proposer)
    response = client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["web_development"],
        "recipient_gives": ["mentors"],
    })
    assert response.status_code == 201, response.get_data(as_text=True)
    return proposer, recipient, response.get_json()["proposal"]["id"]


def test_a_proposal_email_is_sent_by_default(client, login, make_org, outbox):
    _pending(client, login, make_org)
    assert [kind for kind, _a, _k in outbox] == ["notify_proposal_created"]


@pytest.fixture
def dispatched(monkeypatch):
    """Every message the real senders hand to the delivery queue.

    The autouse fixture in conftest replaces the notify_* names that app.py
    imported, which is right for a route test -- it stops the suite mailing
    anybody -- but it means the senders themselves never run, and the senders
    are where the preference is consulted. This patches one layer lower, so
    the real function decides and only the transport is stubbed.
    """
    import notifications

    seen = []
    monkeypatch.setattr(
        notifications, "_dispatch",
        lambda to_addr, subject, *a, **k: seen.append((to_addr, subject)))
    return seen


def _proposal_between(session, proposer, recipient):
    from models import Partnership

    proposal = Partnership(
        proposer_id=proposer.id, recipient_id=recipient.id,
        status=Partnership.PENDING,
        proposer_gives=["web_development"], recipient_gives=["mentors"],
        proposer_name=proposer.name, recipient_name=recipient.name,
    )
    session.add(proposal)
    session.commit()
    return proposal


def test_turning_proposals_off_stops_the_proposal_email(
        session, make_org, dispatched):
    """The decision lives in the sender, so that is where this asks."""
    from notifications import notify_proposal_created

    quiet = make_org(email_preferences={"proposals": False})
    proposer = make_org()
    notify_proposal_created(_proposal_between(session, proposer, quiet))
    assert dispatched == []


def test_leaving_proposals_on_sends_it(session, make_org, dispatched):
    """The other half, so the test above cannot pass by being broken."""
    from notifications import notify_proposal_created

    recipient = make_org()
    proposer = make_org()
    notify_proposal_created(_proposal_between(session, proposer, recipient))
    assert len(dispatched) == 1
    assert dispatched[0][0] == recipient.contact_email or recipient.email


def test_silencing_messages_does_not_silence_proposals(
        session, make_org, dispatched):
    """The whole reason the switch was split.

    Somebody who does not want a running conversation in their inbox still
    wants to know a partnership was proposed to them.
    """
    from notifications import notify_proposal_created

    recipient = make_org(email_preferences={
        "messages": False, "partnerships": False,
    })
    proposer = make_org()
    notify_proposal_created(_proposal_between(session, proposer, recipient))
    assert len(dispatched) == 1


def test_silencing_messages_leaves_proposals_alone(
        client, login, make_org, outbox):
    """The whole point of splitting the switch.

    Somebody who does not want a running conversation in their inbox still
    wants to know a partnership was proposed to them.
    """
    _pending(client, login, make_org,
             email_preferences={"messages": False, "partnerships": False})
    assert [kind for kind, _a, _k in outbox] == ["notify_proposal_created"]


def test_account_security_mail_ignores_every_preference(
        client, make_org, outbox):
    """Verification and reset are the only channel back to somebody locked
    out of their own account. A preference that can silence them is a
    preference that can lock somebody out for good."""
    org = make_org(email_preferences={
        "proposals": False, "messages": False, "partnerships": False,
    })
    response = client.post("/forgot-password", json={"email": org.email})
    assert response.status_code == 200
    assert [kind for kind, _a, _k in outbox] == ["notify_password_reset"]
