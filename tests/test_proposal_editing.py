"""Correcting a proposal before it is answered, and the dates it carries.

The window is the load-bearing part: editing stops at acceptance, because an
accepted partnership is a record of what two organizations agreed to and one
of them changing it afterwards would make it a claim about the other.
"""

import pytest


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


def test_only_the_sender_may_edit(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    response = client.patch(f"/api/proposals/{proposal_id}",
                            json={"message": "Actually, make it December."})
    assert response.status_code == 403


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
