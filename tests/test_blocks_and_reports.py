"""Blocking an organization, reporting a thread, opting into search, and
signing out everywhere else.

The README listed the first two as not built. What a block promises is
written in models.Block: the blocked side cannot propose, cannot post,
disappears from the blocker's matches and directory, and is never told.
"""

import pytest


@pytest.fixture
def pair(make_org):
    # Both list both, so either can propose the same terms to the other.
    both = ["web_development", "grant_writing"]
    me = make_org(name="pytest blocker", needs=both, offers=both)
    other = make_org(name="pytest blocked", needs=both, offers=both)
    return me, other


def _propose(client, recipient):
    return client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    })


def test_a_block_settles_the_proposal_and_closes_the_thread(
        client, login, pair, outbox):
    me, them = pair
    login(them)
    pid = _propose(client, me).get_json()["proposal"]["id"]
    assert client.post(f"/api/proposals/{pid}/messages",
                       json={"body": "pytest hello"}).status_code == 201
    client.post("/logout")

    login(me)
    outbox.clear()
    response = client.post("/api/blocks", json={"organization_id": them.id})
    assert response.status_code == 201
    assert outbox == []                       # nobody is told

    # The proposal they sent me is declined; the thread reads closed.
    proposal = client.get(f"/api/proposals/{pid}").get_json()["proposal"]
    assert proposal["status"] == "declined"
    thread = client.get(f"/api/proposals/{pid}/messages").get_json()
    assert thread["open"] is False
    assert [b["organization_id"] for b in
            client.get("/api/blocks").get_json()["blocks"]] == [them.id]

    # And they are gone from my matches and my directory.
    assert them.id not in [m["id"] for m in
                           client.get("/api/matches").get_json()["matches"]]
    listing = client.get("/api/organizations?q=pytest%20blocked").get_json()
    assert them.id not in [o["id"] for o in listing["organizations"]]
    client.post("/logout")

    # From their side: a settled proposal, a refused thread, and a proposal
    # refused in words that do not say why.
    login(them)
    assert client.post(f"/api/proposals/{pid}/messages",
                       json={"body": "pytest again"}).status_code == 409
    refused = _propose(client, me)
    assert refused.status_code == 403
    assert "block" not in refused.get_json()["error"].lower()
    # Still listed for them: the block shows only on the blocker's side.
    assert me.id in [m["id"] for m in
                     client.get("/api/matches").get_json()["matches"]]


def test_unblocking_restores_proposals(client, login, pair):
    me, them = pair
    login(me)
    client.post("/api/blocks", json={"organization_id": them.id})
    assert client.delete(f"/api/blocks/{them.id}").status_code == 200
    assert client.get("/api/blocks").get_json()["blocks"] == []
    client.post("/logout")

    login(them)
    assert _propose(client, me).status_code == 201


def test_blocking_is_idempotent_and_refuses_the_self_and_the_absent(
        client, login, pair):
    me, them = pair
    login(me)
    assert client.post("/api/blocks", json={"organization_id": them.id}).status_code == 201
    assert client.post("/api/blocks", json={"organization_id": them.id}).status_code == 201
    assert len(client.get("/api/blocks").get_json()["blocks"]) == 1
    assert client.post("/api/blocks", json={"organization_id": me.id}).status_code == 400
    assert client.post("/api/blocks", json={"organization_id": 2147483647}).status_code == 404
    assert client.post("/api/blocks", json={}).status_code == 400


def test_a_report_reaches_the_admin_queue(client, login, pair, session):
    from test_admin import ADMIN_PASSWORD
    import bcrypt
    from models import Admin
    me, them = pair
    admin = Admin(
        email=f"pytest-admin-{me.id}@example.com", name="Test Admin",
        password_hash=bcrypt.hashpw(
            ADMIN_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode())
    session.add(admin)
    session.commit()
    login(them)
    pid = _propose(client, me).get_json()["proposal"]["id"]
    client.post("/logout")

    login(me)
    assert client.post(f"/api/proposals/{pid}/report", json={}).status_code == 400
    response = client.post(f"/api/proposals/{pid}/report",
                           json={"reason": "pytest: unwelcome", "block": True})
    assert response.status_code == 201
    assert response.get_json()["blocked"] is True
    assert client.get("/api/proposals/{}".format(pid)).get_json()[
        "proposal"]["status"] == "declined"
    client.post("/logout")

    assert client.post("/api/admin/login", json={
        "email": admin.email, "password": ADMIN_PASSWORD}).status_code == 200
    overview = client.get("/api/admin/overview").get_json()
    mine = [r for r in overview["reports"] if r["partnership_id"] == pid]
    assert len(mine) == 1
    report = mine[0]
    assert report["reporter_name"] == me.name
    assert report["reported_name"] == them.name
    assert report["reason"] == "pytest: unwelcome"
    assert overview["counts"]["reports"] >= 1

    handled = client.post(f"/api/admin/reports/{report['id']}/handled")
    assert handled.status_code == 200
    assert handled.get_json()["report"]["handled_at"]
    again = client.get("/api/admin/overview").get_json()
    assert not [r for r in again["reports"] if r["id"] == report["id"]]

    from models import AdminAction
    assert session.query(AdminAction).filter_by(
        action="handle_report", target_id=report["id"]).count() == 1


def test_only_a_party_can_report(client, login, pair, make_org):
    me, them = pair
    login(them)
    pid = _propose(client, me).get_json()["proposal"]["id"]
    client.post("/logout")

    stranger = make_org(name="pytest stranger")
    login(stranger)
    assert client.post(f"/api/proposals/{pid}/report",
                       json={"reason": "pytest"}).status_code == 404


def test_search_indexing_is_opt_in(client, login, make_org):
    org = make_org(name="pytest searchable")
    page = client.get(f"/organization.html?id={org.id}").get_data(as_text=True)
    assert 'content="noindex, nofollow"' in page
    assert f"organization.html?id={org.id}" not in client.get(
        "/sitemap.xml").get_data(as_text=True)

    login(org)
    assert client.get("/api/me").get_json()["organization"]["searchable"] is False
    assert client.patch("/api/settings", json={"searchable": "yes"}).status_code == 400
    response = client.patch("/api/settings", json={"searchable": True})
    assert response.status_code == 200
    assert response.get_json()["organization"]["searchable"] is True
    client.post("/logout")

    page = client.get(f"/organization.html?id={org.id}").get_data(as_text=True)
    assert 'content="index, follow"' in page
    assert 'content="noindex' not in page
    assert f"organization.html?id={org.id}" in client.get(
        "/sitemap.xml").get_data(as_text=True)


def test_signing_out_everywhere_else_keeps_this_session(client, login, make_org):
    org = make_org(name="pytest sessions")
    login(org)
    response = client.delete("/api/account/sessions/others")
    assert response.status_code == 200
    # The caller stays signed in on the device it did this from.
    assert client.get("/api/me").status_code == 200
