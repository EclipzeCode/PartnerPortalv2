"""Where an organization's contact details are and are not served.

The listings answer "who could I work with"; they used to answer it with an
address and a phone number attached to every row, which made paging the
directory a way to collect the contact details of every organization on the
site from an account that costs nothing to create. These pin the line: the
listings carry enough to decide whether to approach somebody, and the
profile -- asked for one organization at a time -- carries how.
"""

LISTING_PATHS = ("/api/matches", "/api/organizations", "/api/saved")


def test_listings_carry_no_contact_details(client, login, make_org):
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    them = make_org(needs=["grant_writing"], offers=["web_development"],
                    contact_email="reachme@example.com",
                    contact_phone="+1 555 0100")

    login(me)
    assert client.post("/api/saved", json={"organization_id": them.id}).status_code == 201

    for path in LISTING_PATHS:
        body = client.get(path).get_data(as_text=True)
        assert "reachme@example.com" not in body, path
        assert "555 0100" not in body, path
        # The login address was never in these and still is not.
        assert them.email not in body, path


def test_the_dashboard_carries_no_contact_details(client, login, make_org):
    """top_matches is a listing too, and feeds the same detail dialog."""
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    make_org(needs=["grant_writing"], offers=["web_development"],
             contact_email="reachme@example.com", contact_phone="+1 555 0100")

    login(me)
    body = client.get("/api/dashboard").get_data(as_text=True)
    assert "reachme@example.com" not in body
    assert "555 0100" not in body


def test_the_profile_of_one_organization_still_carries_them(
        client, login, make_org):
    """The whole point of a match is being able to act on it."""
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    them = make_org(needs=["grant_writing"], offers=["web_development"],
                    contact_email="reachme@example.com",
                    contact_phone="+1 555 0100")

    login(me)
    profile = client.get(f"/api/organizations/{them.id}").get_json()["organization"]
    assert profile["contact_email"] == "reachme@example.com"
    assert profile["contact_phone"] == "+1 555 0100"


def test_an_org_still_sees_its_own_contact_details(client, login, make_org):
    """Onboarding and settings render these back into the fields they came
    from, so withholding them from the caller's own record would blank both
    every time the form loaded."""
    me = make_org(needs=["web_development"], offers=["grant_writing"],
                  contact_email="mine@example.com", contact_phone="+1 555 0111")

    login(me)
    org = client.get("/api/me").get_json()["organization"]
    assert org["contact_email"] == "mine@example.com"
    assert org["contact_phone"] == "+1 555 0111"


def test_the_other_side_of_a_proposal_still_carries_them(
        client, login, make_org):
    """A proposal is the two of them already talking."""
    proposer = make_org(needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(needs=["grant_writing"], offers=["web_development"],
                         contact_email="reachme@example.com",
                         contact_phone="+1 555 0100")

    login(proposer)
    assert client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    }).status_code == 201

    listed = client.get("/api/proposals").get_json()["proposals"]
    counterpart = listed[0]["counterpart"]
    assert counterpart["contact_email"] == "reachme@example.com"
    assert counterpart["contact_phone"] == "+1 555 0100"


def test_an_id_too_large_for_the_column_is_not_found_rather_than_a_500(
        client, login, make_org):
    """Every id column is a Postgres integer, and a bigger number cannot be
    compared against one at all -- psycopg raises NumericValueOutOfRange,
    which is a DataError that nothing catches. A mangled link was enough."""
    huge = 99999999999999999999

    # Unauthenticated, which is the one a crawler reaches.
    assert client.get(f"/api/organizations/{huge}/public").status_code == 404
    # The page behind it falls back to its generic link preview.
    assert client.get(f"/organization.html?id={huge}").status_code == 200

    me = make_org(needs=["web_development"], offers=["grant_writing"])
    login(me)
    assert client.get(f"/api/organizations/{huge}").status_code == 404
    assert client.get(f"/api/proposals/{huge}").status_code == 404

    # The two that arrive in a body rather than in the path, where the URL
    # converter never sees them and the handler checks instead.
    assert client.post("/api/saved",
                       json={"organization_id": huge}).status_code == 404
    assert client.post("/api/proposals", json={
        "recipient_id": huge,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    }).status_code == 404

    # A non-GET on an out-of-range id answers 405 rather than 404, and that
    # is this app's existing answer for any unrouted /api path reached with
    # the wrong method -- Flask's static route is mounted at the site root,
    # so it claims the path for GET and HEAD and refuses everything else.
    # See method_not_allowed in app.py. What matters here is what used to
    # happen instead: a DataError escaping as a 500. So this pins the part
    # that is actually load-bearing -- refused, never crashed, and always
    # with a body the client can read -- rather than a status code that
    # belongs to a different decision.
    for response in (client.delete(f"/api/events/{huge}"),
                     client.delete(f"/api/saved/{huge}"),
                     client.patch(f"/api/events/{huge}", json={"title": "x"})):
        assert response.status_code in (404, 405), response.status_code
        assert response.get_json()["error"] == "Not found."
