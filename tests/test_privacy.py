"""What one organization can and cannot learn about another.

Each of these is a promise made somewhere in the product: in a form's helper
text, in a dialog, or in the decision not to build a feature. They are the
tests most worth having, because breaking one leaks something rather than
visibly failing.
"""


def test_public_profile_withholds_contact_details(client, make_org):
    """Served to anyone with the URL, so it carries no way to reach anyone."""
    org = make_org(needs=["web_development"], offers=["grant_writing"],
                   contact_email="reachme@example.com",
                   contact_phone="+1 555 0100")

    body = client.get(f"/api/organizations/{org.id}/public").get_json()
    profile = body["organization"]

    assert "contact_email" not in profile
    assert "contact_phone" not in profile
    assert "reachme@example.com" not in str(body)
    # The login address is not in there under any name either.
    assert org.email not in str(body)


def test_links_are_public_only_when_opted_in(client, make_org):
    """links_public defaults off, so handles are never published by accident."""
    private = make_org(needs=["web_development"], offers=["grant_writing"],
                       website_url="https://private.example.org")
    public = make_org(needs=["web_development"], offers=["grant_writing"],
                      website_url="https://public.example.org",
                      links_public=True)

    private_body = client.get(f"/api/organizations/{private.id}/public").get_json()
    public_body = client.get(f"/api/organizations/{public.id}/public").get_json()

    assert "website_url" not in private_body["organization"]
    assert public_body["organization"]["website_url"] == "https://public.example.org"


def test_a_saved_lead_is_invisible_to_the_organization_saved(client, login, make_org):
    """Saving is a bookmark, not an approach.

    If being saved were visible it would be an unsolicited signal to the
    other side, which is a different feature with different consent.
    """
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    them = make_org(needs=["grant_writing"], offers=["web_development"])

    login(me)
    assert client.post("/api/saved", json={"organization_id": them.id}).status_code == 201
    client.post("/logout")

    login(them)
    assert client.get("/api/saved").get_json() == {"saved": [], "count": 0}
    assert client.get("/api/matches").get_json()["saved_ids"] == []
    # Nothing in the payload about `me` hints at it either.
    body = client.get(f"/api/organizations/{me.id}").get_json()
    assert "saved" not in str(body).lower().replace("saved_ids", "")


def test_a_shortlist_note_never_reaches_the_organization_it_is_about(
        client, login, make_org):
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    them = make_org(needs=["grant_writing"], offers=["web_development"])
    secret = "pytest-private-note-do-not-leak"

    login(me)
    client.post("/api/saved", json={"organization_id": them.id})
    assert client.patch(f"/api/saved/{them.id}",
                        json={"note": secret}).status_code == 200
    client.post("/logout")

    login(them)
    for path in ("/api/saved", "/api/matches", "/api/dashboard",
                 f"/api/organizations/{me.id}",
                 f"/api/organizations/{me.id}/public"):
        assert secret not in client.get(path).get_data(as_text=True), path


def test_profile_views_are_counted_but_never_itemised(client, login, make_org):
    """An organization learns how often it was looked at, not by whom.

    Most visitors are signed out and have no account to be named from, so
    there is deliberately no endpoint that lists them.
    """
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    # Deliberately shares nothing with `me`, so it cannot turn up in the
    # dashboard as a match. If its name appears at all, view tracking put it
    # there -- which is the thing being ruled out.
    viewer = make_org(needs=["translation"], offers=["animal_welfare_help"])

    login(viewer)
    client.get(f"/api/organizations/{me.id}/public")
    client.post("/logout")

    login(me)
    body = client.get("/api/dashboard").get_data(as_text=True)
    stats = client.get("/api/dashboard").get_json()["stats"]

    assert stats["profile_views"] == 1
    assert viewer.name not in body
    assert viewer.email not in body
    # There is no route that would list them, either.
    assert client.get("/api/profile-views").status_code == 404


def test_the_private_payload_never_carries_the_password_hash(client, login, make_org):
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    login(me)
    for path in ("/api/me", "/api/dashboard"):
        body = client.get(path).get_data(as_text=True)
        assert "password_hash" not in body, path
        assert "$2b$" not in body, path
