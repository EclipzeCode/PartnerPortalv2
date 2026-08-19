"""How a profile view is counted.

The number is shown to an organization as a measure of interest, so what it
counts has to match what it claims: people who opened the profile, once
each, not reloads, not the owner, and not a link preview.
"""


def _views(client):
    return client.get("/api/dashboard").get_json()["stats"]["profile_views"]


def test_an_orgs_own_visits_are_not_counted(client, login, make_org):
    """The dashboard and settings both link to it, so this would inflate on
    every check of your own page."""
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    login(me)
    for _ in range(3):
        client.get(f"/api/organizations/{me.id}/public")
    assert _views(client) == 0


def test_a_signed_in_viewer_counts_once_however_often_they_look(
        client, login, make_org):
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    viewer = make_org(needs=["grant_writing"], offers=["web_development"])

    login(viewer)
    for _ in range(4):
        client.get(f"/api/organizations/{me.id}/public")
    client.post("/logout")

    login(me)
    assert _views(client) == 1


def test_two_different_viewers_count_separately(client, login, make_org):
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    first = make_org(needs=["grant_writing"], offers=["web_development"])
    second = make_org(needs=["grant_writing"], offers=["web_development"])

    for viewer in (first, second):
        login(viewer)
        client.get(f"/api/organizations/{me.id}/public")
        client.post("/logout")

    login(me)
    assert _views(client) == 2


def test_a_link_preview_cannot_inflate_the_count(client, login, make_org):
    """Unfurl bots fetch the HTML and never run its script, so counting on
    the endpoint that script calls is what keeps them out."""
    me = make_org(needs=["web_development"], offers=["grant_writing"])

    for _ in range(5):
        client.get(f"/organization.html?id={me.id}",
                   headers={"User-Agent": "Slackbot-LinkExpanding 1.0"})

    login(me)
    assert _views(client) == 0


def test_views_of_an_unfinished_profile_are_not_recorded(client, login, make_org):
    """There is no public profile to look at until onboarding is done."""
    me = make_org(onboarding_complete=False)
    viewer = make_org(needs=["grant_writing"], offers=["web_development"])

    login(viewer)
    assert client.get(f"/api/organizations/{me.id}/public").status_code == 404
    client.post("/logout")

    login(me)
    assert _views(client) == 0


def test_the_stored_row_identifies_no_one(session, client, login, make_org):
    """viewer_key exists so a reload can be told from a second visit, and for
    nothing else.

    An earlier version of this test asserted that the viewer's id did not
    appear as a substring of the digest, which is not a property of anything:
    a two-digit id turns up in a 64-character hex string about half the time.
    It passed against a database whose ids were three digits long and failed
    the first time it met a freshly migrated one.
    """
    import hashlib

    from models import ProfileView

    me = make_org(needs=["web_development"], offers=["grant_writing"])
    viewer = make_org(needs=["grant_writing"], offers=["web_development"])
    other = make_org(needs=["grant_writing"], offers=["web_development"])

    for org in (viewer, other):
        login(org)
        client.get(f"/api/organizations/{me.id}/public")
        client.post("/logout")

    keys = [row.viewer_key for row in session.query(ProfileView).filter(
        ProfileView.organization_id == me.id).all()]

    assert len(keys) == 2
    for key in keys:
        assert len(key) == 64 and all(c in "0123456789abcdef" for c in key)
    # Two visitors, two keys: enough to count them separately, which is all
    # the column is for.
    assert keys[0] != keys[1]
    # Salted with the app secret, so holding the table is not enough to
    # rehash candidate organization ids and recover who looked.
    unsalted = hashlib.sha256(f"org:{viewer.id}".encode()).hexdigest()
    assert unsalted not in keys
