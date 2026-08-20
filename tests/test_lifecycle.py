"""What happens to a partnership after both sides have agreed.

"accepted" used to be the end of the line, so an agreement that ran its course
last year sat in the same list, with the same public page, as one starting
next week -- and nothing recorded whether either side actually provided what
it committed to.

Completing is mutual, like accepting: one organization deciding alone that a
partnership is finished is a claim about what the other one received. Ending
is unilateral, because needing agreement before you may stop would let one
side hold the other in place by never answering.
"""

import pytest

PASSWORD = "Test1234!verify"


@pytest.fixture
def agreed(client, login, make_org):
    """Two organizations with an accepted partnership between them."""
    proposer = make_org(name="pytest-life Proposer",
                        needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(name="pytest-life Recipient",
                         needs=["grant_writing"], offers=["web_development"])

    login(proposer)
    created = client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    })
    assert created.status_code == 201
    proposal_id = created.get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    accepted = client.post(f"/api/proposals/{proposal_id}/accept", json={})
    assert accepted.status_code == 200
    client.post("/logout")
    return proposer, recipient, proposal_id, accepted.get_json()["proposal"]["share_token"]


# --- Completing -------------------------------------------------------------

def test_completing_takes_both_sides(client, login, agreed):
    proposer, recipient, pid, _token = agreed

    login(proposer)
    first = client.post(f"/api/proposals/{pid}/complete", json={"delivered": True})
    assert first.status_code == 200
    body = first.get_json()
    assert body["awaiting_other_side"] is True
    # One side alone does not close it. That is the whole rule.
    assert body["proposal"]["status"] == "accepted"
    assert body["proposal"]["you_marked_complete"] is True
    assert body["proposal"]["they_marked_complete"] is False
    client.post("/logout")

    login(recipient)
    # The other side sees that it is waiting on them.
    listed = client.get(f"/api/proposals/{pid}").get_json()["proposal"]
    assert listed["they_marked_complete"] is True
    assert listed["you_marked_complete"] is False
    assert listed["can_complete"] is True

    second = client.post(f"/api/proposals/{pid}/complete", json={"delivered": True})
    assert second.status_code == 200
    assert second.get_json()["awaiting_other_side"] is False
    assert second.get_json()["proposal"]["status"] == "completed"
    assert second.get_json()["proposal"]["completed_at"]


def test_a_side_cannot_complete_twice(client, login, agreed):
    """Marking again is not a way to close it without the other side."""
    proposer, _recipient, pid, _token = agreed
    login(proposer)
    assert client.post(f"/api/proposals/{pid}/complete", json={}).status_code == 200
    again = client.post(f"/api/proposals/{pid}/complete", json={})
    assert again.status_code == 409
    assert client.get(f"/api/proposals/{pid}").get_json()["proposal"]["status"] == "accepted"


def test_only_a_party_can_complete(client, login, agreed, make_org):
    _proposer, _recipient, pid, _token = agreed
    outsider = make_org(name="pytest-life Outsider",
                        needs=["legal"], offers=["legal"])
    login(outsider)
    # Same "not found" other org's rows get, so ids cannot be probed.
    assert client.post(f"/api/proposals/{pid}/complete", json={}).status_code == 404


def test_a_pending_proposal_cannot_be_completed(client, login, make_org):
    proposer = make_org(needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(needs=["grant_writing"], offers=["web_development"])
    login(proposer)
    created = client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    })
    pid = created.get_json()["proposal"]["id"]
    assert client.post(f"/api/proposals/{pid}/complete", json={}).status_code == 409


# --- Delivery ---------------------------------------------------------------

def test_each_side_records_a_verdict_on_the_other(client, login, agreed):
    """Named for the side being judged: nobody grades their own homework."""
    proposer, recipient, pid, _token = agreed

    login(proposer)
    client.post(f"/api/proposals/{pid}/complete", json={"delivered": False})
    mine = client.get(f"/api/proposals/{pid}").get_json()["proposal"]
    # The proposer's verdict is about the recipient.
    assert mine["counterpart_delivered"] is False
    assert mine["you_delivered"] is None
    client.post("/logout")

    login(recipient)
    client.post(f"/api/proposals/{pid}/complete", json={"delivered": True})
    theirs = client.get(f"/api/proposals/{pid}").get_json()["proposal"]
    assert theirs["counterpart_delivered"] is True     # about the proposer
    assert theirs["you_delivered"] is False            # what the proposer said


def test_delivered_must_be_a_boolean(client, login, agreed):
    proposer, _recipient, pid, _token = agreed
    login(proposer)
    response = client.post(f"/api/proposals/{pid}/complete",
                           json={"delivered": "yes"})
    assert response.status_code == 400
    assert response.get_json()["field"] == "delivered"


def test_a_verdict_is_never_published(client, login, agreed):
    """An unverified, undisputed claim about a named organization is not
    something to put on a page anyone can open."""
    proposer, recipient, pid, token = agreed
    login(proposer)
    client.post(f"/api/proposals/{pid}/complete", json={"delivered": False})
    client.post("/logout")
    login(recipient)
    client.post(f"/api/proposals/{pid}/complete", json={"delivered": False})
    client.post("/logout")

    public = client.get(f"/api/partnerships/{token}").get_json()["partnership"]
    body = str(public)
    assert "delivered" not in body
    assert public["status"] == "completed"


# --- Ending -----------------------------------------------------------------

def test_either_side_can_end_it_alone(client, login, agreed):
    """No permission needed -- otherwise one side could hold the other to a
    partnership by never answering."""
    _proposer, recipient, pid, _token = agreed
    login(recipient)
    response = client.post(f"/api/proposals/{pid}/end",
                           json={"reason": "Our programme finished early."})
    assert response.status_code == 200
    body = response.get_json()["proposal"]
    assert body["status"] == "ended"
    assert body["ended_at"]
    assert body["ended_by_you"] is True


def test_the_other_side_is_told_who_ended_it_and_why(client, login, agreed):
    proposer, recipient, pid, _token = agreed
    login(recipient)
    client.post(f"/api/proposals/{pid}/end", json={"reason": "Ran out of funding."})
    client.post("/logout")

    login(proposer)
    seen = client.get(f"/api/proposals/{pid}").get_json()["proposal"]
    assert seen["status"] == "ended"
    assert seen["end_reason"] == "Ran out of funding."
    assert seen["ended_by_you"] is False


def test_an_ended_partnership_cannot_be_ended_or_completed_again(client, login, agreed):
    proposer, _recipient, pid, _token = agreed
    login(proposer)
    assert client.post(f"/api/proposals/{pid}/end", json={}).status_code == 200
    assert client.post(f"/api/proposals/{pid}/end", json={}).status_code == 409
    assert client.post(f"/api/proposals/{pid}/complete", json={}).status_code == 409


def test_the_end_reason_is_capped(client, login, agreed):
    proposer, _recipient, pid, _token = agreed
    login(proposer)
    response = client.post(f"/api/proposals/{pid}/end", json={"reason": "x" * 5000})
    assert response.status_code == 400
    assert response.get_json()["field"] == "reason"


def test_the_end_reason_is_never_published(client, login, agreed):
    """Ending is one side's account, given without the other having a say in
    how it is worded."""
    proposer, _recipient, pid, token = agreed
    login(proposer)
    client.post(f"/api/proposals/{pid}/end",
                json={"reason": "They were impossible to work with."})
    client.post("/logout")

    public = client.get(f"/api/partnerships/{token}").get_json()["partnership"]
    assert public["status"] == "ended"
    assert public["ended_at"]
    assert "impossible" not in str(public)
    assert "ended_by" not in public


# --- The public record ------------------------------------------------------

def test_a_finished_agreement_still_resolves(client, login, agreed):
    """The link was shared on the strength of what two organizations agreed,
    and that stays true after it finishes. 404 would break every reference to
    it and tell the reader nothing."""
    proposer, recipient, pid, token = agreed

    assert client.get(f"/api/partnerships/{token}").status_code == 200
    login(proposer)
    client.post(f"/api/proposals/{pid}/complete", json={})
    client.post("/logout")
    login(recipient)
    client.post(f"/api/proposals/{pid}/complete", json={})
    client.post("/logout")

    response = client.get(f"/api/partnerships/{token}")
    assert response.status_code == 200
    summary = response.get_json()["partnership"]
    assert summary["status"] == "completed"
    assert summary["completed_at"]
    # What was agreed is unchanged by it having finished.
    assert len(summary["parties"]) == 2
    assert summary["parties"][0]["gives"]


def test_a_declined_proposal_still_has_no_public_page(client, login, make_org):
    """Widening the public statuses must not have widened it to proposals
    that were never agreed at all."""
    proposer = make_org(needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(needs=["grant_writing"], offers=["web_development"])
    login(proposer)
    pid = client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    }).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    client.post(f"/api/proposals/{pid}/decline", json={})
    # A declined proposal never had a token minted, so there is nothing to
    # ask for -- which is the check that matters.
    assert client.get(f"/api/proposals/{pid}").get_json()[
        "proposal"]["share_token"] is None


def test_a_finished_partnership_can_be_proposed_again(client, login, agreed):
    """Ending is not a ban. The partial unique index only blocks a second
    *pending* proposal in the same direction."""
    proposer, recipient, pid, _token = agreed
    login(proposer)
    client.post(f"/api/proposals/{pid}/end", json={})
    again = client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    })
    assert again.status_code == 201


def test_the_other_side_is_emailed_when_a_partnership_ends(client, login, agreed, outbox):
    proposer, _recipient, pid, _token = agreed
    login(proposer)
    client.post(f"/api/proposals/{pid}/end", json={})
    assert [s for s in outbox if s[0] == "notify_partnership_ended"]


def test_marking_complete_asks_the_other_side_to_confirm(client, login, agreed, outbox):
    """Without this the mutual half does not work: nothing else tells the
    other organization a confirmation is waiting on it."""
    proposer, recipient, pid, _token = agreed
    login(proposer)
    client.post(f"/api/proposals/{pid}/complete", json={})
    assert [s for s in outbox if s[0] == "notify_completion_marked"]
    client.post("/logout")

    login(recipient)
    client.post(f"/api/proposals/{pid}/complete", json={})
    assert [s for s in outbox if s[0] == "notify_partnership_completed"]
