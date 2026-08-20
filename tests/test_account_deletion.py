"""What survives an organization closing its account.

Both foreign keys on partnerships were ON DELETE CASCADE, so one side leaving
destroyed every partnership it was party to. The case that matters is one the
two organizations actually agreed: the other side confirmed it, may have sent
its public link to a board or a funder, was not asked, was not told, and the
link simply began answering 404.

That covers every status in Partnership.PUBLIC, not only `accepted`. Fixing
the foreign key left a second copy of the same bug in _detach_partnerships,
which kept accepted agreements and deleted completed and ended ones -- so
finishing a partnership properly and then closing your account destroyed it,
while leaving one open preserved it. The last two tests here are that case.
"""

from models import Partnership

PASSWORD = "Test1234!verify"


def _accepted_partnership(client, login, proposer, recipient):
    """Propose and accept, returning the share token."""
    login(proposer)
    created = client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    })
    assert created.status_code == 201, created.get_data(as_text=True)
    proposal_id = created.get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    accepted = client.post(f"/api/proposals/{proposal_id}/accept", json={})
    assert accepted.status_code == 200
    client.post("/logout")
    return accepted.get_json()["proposal"]["share_token"]


def _pair(make_org):
    proposer = make_org(name="pytest leaver",
                        needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(name="pytest stayer",
                         needs=["grant_writing"], offers=["web_development"])
    return proposer, recipient


def test_an_agreement_outlives_the_other_party(client, login, make_org):
    """The bug, directly: the surviving org's public link kept working."""
    leaver, stayer = _pair(make_org)
    token = _accepted_partnership(client, login, leaver, stayer)

    # The link works while both exist.
    assert client.get(f"/api/partnerships/{token}").status_code == 200

    login(leaver)
    assert client.delete(
        "/api/account", json={"password": PASSWORD}).status_code == 200

    # ...and still works afterwards. This used to be a 404.
    response = client.get(f"/api/partnerships/{token}")
    assert response.status_code == 200

    summary = response.get_json()["partnership"]
    names = [p["name"] for p in summary["parties"]]
    assert "pytest leaver" in names
    assert "pytest stayer" in names
    # The reader is told which party is gone, rather than being shown a name
    # that looks like a live organization.
    gone = [p for p in summary["parties"] if p["deleted"]]
    assert len(gone) == 1 and gone[0]["name"] == "pytest leaver"


def test_the_surviving_org_can_still_read_its_proposals(client, login, make_org):
    """SET NULL leaves a row whose relationship is None. Every list the
    survivor loads renders that row, so this is where a naive fix 500s."""
    leaver, stayer = _pair(make_org)
    _accepted_partnership(client, login, leaver, stayer)

    login(leaver)
    client.delete("/api/account", json={"password": PASSWORD})

    login(stayer)
    listing = client.get("/api/proposals")
    assert listing.status_code == 200
    proposals = listing.get_json()["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["counterpart"]["deleted"] is True
    assert proposals[0]["counterpart"]["name"] == "pytest leaver"

    # The dashboard builds its activity feed from the same rows.
    assert client.get("/api/dashboard").status_code == 200


def test_a_pending_proposal_does_not_outlive_its_sender(client, login, make_org):
    """A request from an organization that no longer exists can never be
    accepted, and would sit in the recipient's list as a request from
    nobody."""
    leaver, stayer = _pair(make_org)
    login(leaver)
    assert client.post("/api/proposals", json={
        "recipient_id": stayer.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    }).status_code == 201
    client.delete("/api/account", json={"password": PASSWORD})

    login(stayer)
    assert client.get("/api/proposals").get_json()["proposals"] == []


def test_an_agreement_goes_once_both_parties_have_left(client, login, make_org,
                                                       session):
    """The record survives while there is still a party to it. With both
    gone, nobody remains to be accountable for a public page about them."""
    first, second = _pair(make_org)
    token = _accepted_partnership(client, login, first, second)

    login(first)
    client.delete("/api/account", json={"password": PASSWORD})
    assert client.get(f"/api/partnerships/{token}").status_code == 200

    login(second)
    client.delete("/api/account", json={"password": PASSWORD})
    assert client.get(f"/api/partnerships/{token}").status_code == 404
    assert session.query(Partnership).filter(
        Partnership.share_token == token).one_or_none() is None


def _complete(client, login, first, second, proposal_id):
    """Close a partnership from both sides. Completing is mutual."""
    login(first)
    assert client.post(f"/api/proposals/{proposal_id}/complete",
                       json={"delivered": True}).status_code == 200
    client.post("/logout")

    login(second)
    done = client.post(f"/api/proposals/{proposal_id}/complete",
                       json={"delivered": True})
    assert done.status_code == 200
    assert done.get_json()["proposal"]["status"] == Partnership.COMPLETED
    client.post("/logout")


def test_a_completed_agreement_outlives_the_other_party(client, login, make_org):
    """A partnership that ran its course is more of a record than one still
    in progress, not less. This kept only `accepted`, so finishing a
    partnership and then closing your account destroyed it -- and took the
    survivor's history and their public link with it."""
    leaver, stayer = _pair(make_org)
    token = _accepted_partnership(client, login, leaver, stayer)

    login(leaver)
    proposal_id = client.get("/api/proposals").get_json()["proposals"][0]["id"]
    client.post("/logout")
    _complete(client, login, leaver, stayer, proposal_id)

    login(leaver)
    assert client.delete(
        "/api/account", json={"password": PASSWORD}).status_code == 200

    # The link the other side may have sent to a funder still resolves.
    response = client.get(f"/api/partnerships/{token}")
    assert response.status_code == 200
    assert response.get_json()["partnership"]["status"] == Partnership.COMPLETED

    # And the survivor still has it in their own history.
    login(stayer)
    proposals = client.get("/api/proposals").get_json()["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["status"] == Partnership.COMPLETED
    assert proposals[0]["counterpart"]["deleted"] is True


def test_an_ended_agreement_outlives_the_other_party(client, login, make_org):
    """Ended is the other half of the same rule. The partnership stopped, but
    the two organizations did agree it, and the public page says which it
    is -- so it is a record to keep rather than one to erase."""
    leaver, stayer = _pair(make_org)
    token = _accepted_partnership(client, login, leaver, stayer)

    login(leaver)
    proposal_id = client.get("/api/proposals").get_json()["proposals"][0]["id"]
    ended = client.post(f"/api/proposals/{proposal_id}/end",
                        json={"reason": "pytest ran out of scope"})
    assert ended.status_code == 200
    assert ended.get_json()["proposal"]["status"] == Partnership.ENDED

    assert client.delete(
        "/api/account", json={"password": PASSWORD}).status_code == 200

    response = client.get(f"/api/partnerships/{token}")
    assert response.status_code == 200
    summary = response.get_json()["partnership"]
    assert summary["status"] == Partnership.ENDED
    # The reason stays between the two parties, deleted account or not.
    assert "pytest ran out of scope" not in response.get_data(as_text=True)

    login(stayer)
    assert len(client.get("/api/proposals").get_json()["proposals"]) == 1


def test_a_rename_still_shows_the_current_name(client, login, make_org, session):
    """The snapshot is a fallback, not the source. A live organization is
    read from its own row, so renaming is reflected rather than frozen."""
    proposer, recipient = _pair(make_org)
    token = _accepted_partnership(client, login, proposer, recipient)

    recipient.name = "pytest stayer renamed"
    session.commit()

    summary = client.get(
        f"/api/partnerships/{token}").get_json()["partnership"]
    assert "pytest stayer renamed" in [p["name"] for p in summary["parties"]]
