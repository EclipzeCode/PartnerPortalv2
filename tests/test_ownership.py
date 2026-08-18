"""One organization acting on another's rows.

Every one of these answers 404 rather than 403 on purpose: a "forbidden"
tells the caller the id exists, which turns these routes into a way to probe
for other organizations' records.
"""


def test_an_org_cannot_delete_another_orgs_meeting(client, login, make_org):
    owner = make_org()
    intruder = make_org()

    login(owner)
    created = client.post("/api/events", json={
        "title": "Board review", "date": "2030-09-20", "time": "11:15",
        "duration": 1, "partner": "Someone"}).get_json()
    event_id = created["event"]["id"]
    client.post("/logout")

    login(intruder)
    assert client.delete(f"/api/events/{event_id}").status_code == 404
    assert client.get("/api/events").get_json()["events"] == []
    client.post("/logout")

    # Still there for the organization that made it.
    login(owner)
    assert len(client.get("/api/events").get_json()["events"]) == 1


def test_an_org_cannot_note_or_remove_another_orgs_shortlist_entry(
        client, login, make_org):
    owner = make_org(needs=["web_development"], offers=["grant_writing"])
    target = make_org(needs=["grant_writing"], offers=["web_development"])
    intruder = make_org(needs=["web_development"], offers=["grant_writing"])

    login(owner)
    client.post("/api/saved", json={"organization_id": target.id})
    client.patch(f"/api/saved/{target.id}", json={"note": "owner note"})
    client.post("/logout")

    login(intruder)
    # The intruder has its own (empty) shortlist, so this is not "not found
    # anywhere" -- it is "not found on yours".
    assert client.patch(f"/api/saved/{target.id}",
                        json={"note": "hijacked"}).status_code == 404
    assert client.delete(f"/api/saved/{target.id}").status_code == 200
    client.post("/logout")

    login(owner)
    saved = client.get("/api/saved").get_json()["saved"]
    assert [s["id"] for s in saved] == [target.id]
    assert saved[0]["note"] == "owner note"


def test_a_note_cannot_be_written_for_something_not_saved(client, login, make_org):
    """PATCH never creates the row, so a stale tab cannot resurrect one."""
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    them = make_org(needs=["grant_writing"], offers=["web_development"])

    login(me)
    assert client.patch(f"/api/saved/{them.id}",
                        json={"note": "not saved yet"}).status_code == 404
    assert client.get("/api/saved").get_json()["count"] == 0


def test_saving_is_idempotent_and_never_duplicates(client, login, make_org):
    """The bookmark is a toggle; a double click means saved, not an error."""
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    them = make_org(needs=["grant_writing"], offers=["web_development"])

    login(me)
    assert client.post("/api/saved", json={"organization_id": them.id}).status_code == 201
    assert client.post("/api/saved", json={"organization_id": them.id}).status_code == 201
    assert client.get("/api/saved").get_json()["count"] == 1

    assert client.delete(f"/api/saved/{them.id}").status_code == 200
    assert client.delete(f"/api/saved/{them.id}").status_code == 200
    assert client.get("/api/saved").get_json()["count"] == 0


def test_example_organizations_and_self_cannot_be_saved(client, login, make_org):
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    example = make_org(needs=["grant_writing"], offers=["web_development"],
                       is_demo=True)

    login(me)
    assert client.post("/api/saved", json={"organization_id": me.id}).status_code == 400
    assert client.post("/api/saved",
                       json={"organization_id": example.id}).status_code == 400
    assert client.get("/api/saved").get_json()["count"] == 0


def test_signed_out_callers_get_401_not_data(client, make_org):
    org = make_org(needs=["web_development"], offers=["grant_writing"])
    for path in ("/api/me", "/api/saved", "/api/events", "/api/dashboard",
                 "/api/matches", f"/api/organizations/{org.id}"):
        assert client.get(path).status_code == 401, path
