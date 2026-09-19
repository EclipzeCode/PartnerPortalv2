"""Correcting a proposal before it is answered, and the dates it carries.

The window is the load-bearing part: editing stops at acceptance, because an
accepted partnership is a record of what two organizations agreed to and one
of them changing it afterward would make it a claim about the other.
"""

from datetime import datetime, timedelta, timezone

import pytest

from models import Partnership


@pytest.fixture
def pair(make_org):
    """A proposer and a recipient with something to exchange either way."""
    proposer = make_org(name="pytest proposer",
                        needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(name="pytest recipient",
                         needs=["grant_writing"], offers=["web_development"])
    return proposer, recipient


def _propose(client, recipient, **extra):
    return client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
        **extra,
    })


def test_a_pending_proposal_can_be_corrected(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(
        client, recipient, starts_on="2026-09-01").get_json()["proposal"]["id"]

    response = client.patch(f"/api/proposals/{proposal_id}", json={
        "starts_on": "2026-10-01",
        "ends_on": "2026-12-31",
        "message": "Moved the start back a month.",
    })
    assert response.status_code == 200
    updated = response.get_json()["proposal"]
    assert updated["starts_on"] == "2026-10-01"
    assert updated["ends_on"] == "2026-12-31"
    assert updated["message"] == "Moved the start back a month."
    # Still pending, and still the same row -- the thread on it survives,
    # which is the whole reason this exists rather than withdraw-and-resend.
    assert updated["status"] == "pending"


def test_the_recipient_editing_is_a_counter_offer(client, login, pair, outbox):
    """The recipient's edit hands the proposal back to the proposer.

    Before this the recipient's answers were yes and no; changing a term
    meant declining and proposing afresh the other way. Now their edit is
    their answer, and the proposer is the one who has to accept it.
    """
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    outbox.clear()
    response = client.patch(f"/api/proposals/{proposal_id}",
                            json={"message": "Actually, make it December."})
    assert response.status_code == 200
    countered = response.get_json()["proposal"]
    assert countered["status"] == "pending"
    assert countered["countered"] is True
    assert countered["awaiting_you"] is False       # it is the proposer's turn
    assert countered["can_respond"] is False
    assert countered["can_edit"] is False           # not until they answer
    assert [kind for kind, _, _ in outbox] == ["notify_proposal_updated"]

    # Answering their own counter is not theirs to do.
    assert client.post(f"/api/proposals/{proposal_id}/accept").status_code == 403
    second = client.patch(f"/api/proposals/{proposal_id}", json={"message": "and January"})
    assert second.status_code == 403
    client.post("/logout")

    # The proposer now sees it as waiting on them, and can accept it.
    login(proposer)
    mine = client.get(f"/api/proposals/{proposal_id}").get_json()["proposal"]
    assert mine["awaiting_you"] is True
    assert mine["can_respond"] is True
    assert mine["message"] == "Actually, make it December."
    assert client.get("/api/me").get_json()["pending_proposals"] == 1
    accepted = client.post(f"/api/proposals/{proposal_id}/accept")
    assert accepted.status_code == 200
    assert accepted.get_json()["proposal"]["status"] == "accepted"


def test_an_edit_that_changes_nothing_is_not_a_counter_offer(
        client, login, pair, outbox):
    """A body that restates the terms as they are is refused.

    It used to be accepted, and accepting it did two things nobody asked
    for: the turn flipped to the other side, and they were emailed that the
    terms had changed. From the recipient that made "send the same terms
    back" indistinguishable from a real counter-offer.
    """
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(
        client, recipient, message="Hello", starts_on="2026-09-01",
        proposer_quantities={"grant_writing": {"amount": 20, "unit": "hours"}},
    ).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    outbox.clear()
    for body in (
        {},
        {"message": "Hello", "starts_on": "2026-09-01", "ends_on": "",
         "timeline": "", "proposer_gives": ["grant_writing"],
         "recipient_gives": ["web_development"],
         "proposer_quantities": {"grant_writing": {"amount": 20,
                                                   "unit": "hours"}}},
    ):
        response = client.patch(f"/api/proposals/{proposal_id}", json=body)
        assert response.status_code == 400
        assert "Nothing changed" in response.get_json()["error"]

    # Still waiting on the recipient, and nobody was told anything.
    mine = client.get(f"/api/proposals/{proposal_id}").get_json()["proposal"]
    assert mine["awaiting_you"] is True
    assert mine["countered"] is False
    assert outbox == []

    # A real change still goes through.
    response = client.patch(f"/api/proposals/{proposal_id}",
                            json={"message": "Make it December."})
    assert response.status_code == 200
    assert response.get_json()["proposal"]["countered"] is True


def test_a_counter_offer_can_be_countered_back(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    assert client.patch(f"/api/proposals/{proposal_id}",
                        json={"timeline": "six_months"}).status_code == 200
    client.post("/logout")

    login(proposer)
    back = client.patch(f"/api/proposals/{proposal_id}",
                        json={"timeline": "three_months"})
    assert back.status_code == 200
    assert back.get_json()["proposal"]["awaiting_you"] is False
    assert back.get_json()["proposal"]["countered"] is False
    client.post("/logout")

    login(recipient)
    theirs = client.get(f"/api/proposals/{proposal_id}").get_json()["proposal"]
    assert theirs["awaiting_you"] is True
    assert theirs["timeline"] == "three_months"


def test_the_recipient_counters_with_their_own_offers(client, login, pair):
    """Each side is still held to its own list, whoever is editing.

    The columns in the edit dialog are "you" and "they" from the editor's
    point of view; the server checks proposer_gives against the proposer's
    offers and recipient_gives against the recipient's regardless of who
    sent the request.
    """
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    # The recipient cannot commit the proposer to something the proposer
    # never listed...
    refused = client.patch(f"/api/proposals/{proposal_id}",
                           json={"proposer_gives": ["web_development"]})
    assert refused.status_code == 400
    assert "their list of offers" in refused.get_json()["error"]
    # ...nor themselves.
    refused = client.patch(f"/api/proposals/{proposal_id}",
                           json={"recipient_gives": ["grant_writing"]})
    assert refused.status_code == 400
    assert "your list of offers" in refused.get_json()["error"]


def test_an_accepted_partnership_is_fixed(client, login, pair):
    """The agreement is the record. It stops being editable the moment it
    becomes one."""
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    assert client.post(
        f"/api/proposals/{proposal_id}/accept").status_code == 200
    client.post("/logout")

    login(proposer)
    response = client.patch(f"/api/proposals/{proposal_id}",
                            json={"ends_on": "2027-01-01"})
    assert response.status_code == 409
    assert "fixed" in response.get_json()["error"]


def test_an_end_before_a_start_is_refused(client, login, pair):
    proposer, recipient = pair
    login(proposer)

    # On the way in...
    response = _propose(client, recipient,
                        starts_on="2026-10-01", ends_on="2026-09-01")
    assert response.status_code == 400
    assert response.get_json()["field"] == "ends_on"

    # ...and on an edit, including when only one half is sent and has to be
    # read against what is already stored.
    proposal_id = _propose(
        client, recipient, starts_on="2026-10-01").get_json()["proposal"]["id"]
    response = client.patch(f"/api/proposals/{proposal_id}",
                            json={"ends_on": "2026-09-01"})
    assert response.status_code == 400
    assert response.get_json()["field"] == "ends_on"


def test_the_dates_reach_the_public_summary(client, login, pair):
    """A funder reading this months later wants to know when it ran."""
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient, starts_on="2026-09-01",
                           ends_on="2026-12-01").get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    token = client.post(
        f"/api/proposals/{proposal_id}/accept").get_json()["proposal"]["share_token"]
    client.post("/logout")

    summary = client.get(f"/api/partnerships/{token}").get_json()["partnership"]
    assert summary["starts_on"] == "2026-09-01"
    assert summary["ends_on"] == "2026-12-01"


def test_a_start_with_no_end_is_accepted(client, login, pair):
    """Open-ended is a real arrangement, not a half-filled form."""
    proposer, recipient = pair
    login(proposer)
    response = _propose(client, recipient, starts_on="2026-09-01")
    assert response.status_code == 201
    assert response.get_json()["proposal"]["ends_on"] is None


def test_a_seen_counter_offer_stays_seen_when_the_row_is_touched(
        client, login, pair, session):
    """The "suggested different terms" entry is dated by the counter itself.

    It was dated by updated_at, and updated_at moves whenever the row does:
    opening the thread stamps a read marker on it. So a counter the proposer
    had already looked at came back as new -- a different key, unseen again,
    the dot on the bell relit -- every time they read a message on it.
    """
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    client.patch(f"/api/proposals/{proposal_id}", json={"message": "Less."})
    client.post(f"/api/proposals/{proposal_id}/messages",
                json={"body": "Does that work?"})
    client.post("/logout")

    login(proposer)
    # Opening the bell marks everything seen.
    seen = client.post("/api/notifications/read").get_json()["notifications"]
    counter = next(n for n in seen if n["kind"] == "proposal_countered")

    # Reading the thread writes the proposer's read marker onto the
    # partnership row, which is exactly the touch that used to re-date it.
    # The suite runs inside one transaction and Postgres's now() is fixed
    # for a transaction, so updated_at cannot move here on its own; it is
    # moved by hand to what a later request would have written.
    client.get(f"/api/proposals/{proposal_id}/messages")
    row = session.get(Partnership, proposal_id)
    row.updated_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    session.commit()

    after = client.get("/api/notifications").get_json()
    again = next(n for n in after["notifications"]
                 if n["kind"] == "proposal_countered")
    assert again["key"] == counter["key"]
    assert again["at"] == counter["at"]
    assert again["seen"] is True
    assert after["unseen"] == 0
