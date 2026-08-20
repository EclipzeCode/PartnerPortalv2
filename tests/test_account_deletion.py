"""What survives an organization closing its account.

Both foreign keys on partnerships were ON DELETE CASCADE, so one side leaving
destroyed every partnership it was party to. The case that matters is an
accepted one: the other organization confirmed it, may have sent its public
link to a board or a funder, was not asked, was not told, and the link simply
began answering 404.
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
