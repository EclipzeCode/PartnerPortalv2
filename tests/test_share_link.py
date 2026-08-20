"""Rotating and revoking a partnership's public link.

The token was minted once, on acceptance, and lived forever. Anyone ever sent
the link kept it -- a funder no longer involved, a list it was forwarded to, a
board pack that travelled further than intended -- and there was nothing
either organization could do about that short of asking support.
"""

import pytest

PASSWORD = "Test1234!verify"


@pytest.fixture
def agreed(client, login, make_org):
    proposer = make_org(name="pytest-share Proposer",
                        needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(name="pytest-share Recipient",
                         needs=["grant_writing"], offers=["web_development"])
    login(proposer)
    pid = client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    }).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    token = client.post(f"/api/proposals/{pid}/accept",
                        json={}).get_json()["proposal"]["share_token"]
    client.post("/logout")
    return proposer, recipient, pid, token


def test_rotating_retires_the_previous_link(client, login, agreed):
    proposer, _recipient, pid, old_token = agreed
    assert client.get(f"/api/partnerships/{old_token}").status_code == 200

    login(proposer)
    response = client.post(f"/api/proposals/{pid}/share", json={})
    assert response.status_code == 200
    new_token = response.get_json()["share_token"]
    assert new_token != old_token

    # The old URL stops resolving; the new one works.
    assert client.get(f"/api/partnerships/{old_token}").status_code == 404
    assert client.get(f"/api/partnerships/{new_token}").status_code == 200


def test_revoking_takes_it_off_the_web(client, login, agreed):
    proposer, _recipient, pid, token = agreed
    login(proposer)
    assert client.delete(f"/api/proposals/{pid}/share").status_code == 200
    assert client.get(f"/api/partnerships/{token}").status_code == 404

    # The agreement itself is untouched -- both parties still have it.
    listed = client.get(f"/api/proposals/{pid}").get_json()["proposal"]
    assert listed["status"] == "accepted"
    assert listed["share_token"] is None


def test_a_link_can_be_issued_again_after_revoking(client, login, agreed):
    proposer, _recipient, pid, _token = agreed
    login(proposer)
    client.delete(f"/api/proposals/{pid}/share")
    fresh = client.post(f"/api/proposals/{pid}/share", json={})
    assert fresh.status_code == 200
    assert client.get(
        f"/api/partnerships/{fresh.get_json()['share_token']}").status_code == 200


def test_either_party_may_do_it(client, login, agreed):
    """The agreement is equally theirs, and the reason to reach for this is
    that the link has gone somewhere neither of them intended."""
    _proposer, recipient, pid, old_token = agreed
    login(recipient)
    assert client.post(f"/api/proposals/{pid}/share", json={}).status_code == 200
    assert client.get(f"/api/partnerships/{old_token}").status_code == 404


def test_an_outsider_cannot(client, login, agreed, make_org):
    _proposer, _recipient, pid, token = agreed
    outsider = make_org(needs=["legal"], offers=["legal"])
    login(outsider)
    assert client.post(f"/api/proposals/{pid}/share", json={}).status_code == 404
    assert client.delete(f"/api/proposals/{pid}/share").status_code == 404
    # ...and the link still works, because nothing happened.
    assert client.get(f"/api/partnerships/{token}").status_code == 200


def test_a_pending_proposal_has_no_link_to_rotate(client, login, make_org):
    proposer = make_org(needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(needs=["grant_writing"], offers=["web_development"])
    login(proposer)
    pid = client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    }).get_json()["proposal"]["id"]
    assert client.post(f"/api/proposals/{pid}/share", json={}).status_code == 409


def test_the_other_party_is_told(client, login, agreed, outbox):
    """Their copy of the link has just stopped working, and finding that out
    from a funder is worse than finding it out here."""
    proposer, _recipient, pid, _token = agreed
    login(proposer)
    client.post(f"/api/proposals/{pid}/share", json={})
    assert [s for s in outbox if s[0] == "notify_share_link_changed"]


def test_revoking_twice_says_nothing_the_second_time(client, login, agreed, outbox):
    """Idempotent, and it does not email the other side about a link that was
    already gone."""
    proposer, _recipient, pid, _token = agreed
    login(proposer)
    client.delete(f"/api/proposals/{pid}/share")
    before = len([s for s in outbox if s[0] == "notify_share_link_changed"])
    assert client.delete(f"/api/proposals/{pid}/share").status_code == 200
    assert len([s for s in outbox if s[0] == "notify_share_link_changed"]) == before
