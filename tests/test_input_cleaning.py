"""What the server does with input it does not recognise.

The rule throughout is: drop what is unknown, keep what is not, and never
fail a whole submission because one value was stale. A browser tab left open
across a vocabulary change should still be able to save.
"""

from categories import clean_categories, clean_focus_areas


def test_unknown_and_duplicate_category_slugs_are_dropped(client, login, make_org):
    me = make_org()
    login(me)

    response = client.post("/api/onboarding", json={
        "organization_name": "pytest cleaning", "organization_type": "NGO",
        "location": "Testville, TS",
        "needs": ["web_development", "not_a_real_slug", 42, "web_development"],
        "offers": ["grant_writing"],
        "focus_areas": ["food_security", "no_such_cause", None, "food_security"],
        "description": "Long enough to satisfy the description minimum.",
    })

    assert response.status_code == 200
    me_body = client.get("/api/me").get_json()["organization"]
    assert me_body["needs"] == ["web_development"]
    assert me_body["focus_areas"] == ["food_security"]


def test_cleaning_preserves_order_and_removes_duplicates():
    assert clean_categories(["legal", "web_development", "legal"]) == [
        "legal", "web_development"]
    assert clean_focus_areas(["veterans", "food_security", "veterans"]) == [
        "veterans", "food_security"]


def test_cleaning_handles_values_that_are_not_lists():
    for junk in (None, "web_development", 7, {"a": 1}):
        assert clean_categories(junk) == []
        assert clean_focus_areas(junk) == []


def test_focus_areas_and_categories_are_separate_vocabularies():
    """A cause is not something anyone trades, so neither list accepts the
    other's slugs -- mixing them would corrupt matching."""
    assert clean_categories(["food_security"]) == []
    assert clean_focus_areas(["web_development"]) == []


def test_onboarding_still_refuses_a_submission_with_nothing_to_match_on(
        client, login, make_org):
    """Dropping unknown values must not quietly turn a real mistake into a
    saved profile with empty needs."""
    me = make_org()
    login(me)

    response = client.post("/api/onboarding", json={
        "organization_name": "pytest empty", "organization_type": "NGO",
        "location": "Testville, TS",
        "needs": ["not_a_real_slug"], "offers": ["also_not_real"],
        "description": "Long enough to satisfy the description minimum.",
    })
    assert response.status_code == 400


def test_meeting_validation_rejects_what_the_columns_cannot_hold(
        client, login, make_org):
    """The form is not the only way in, and date/time/duration are real
    column types rather than the strings the browser sends."""
    me = make_org()
    login(me)
    valid = {"title": "Sync", "date": "2030-09-20", "time": "11:15",
             "duration": 1, "partner": "Someone"}

    assert client.post("/api/events", json=valid).status_code == 201
    for field, bad in [
        ("title", ""), ("partner", ""), ("date", "2030-13-45"),
        ("time", "99:99"), ("duration", 0), ("duration", 25),
        ("duration", "soon"),
    ]:
        assert client.post(
            "/api/events", json={**valid, field: bad}
        ).status_code == 400, f"{field}={bad!r}"


def test_a_shortlist_note_is_trimmed_capped_and_clearable(client, login, make_org):
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    them = make_org(needs=["grant_writing"], offers=["web_development"])
    login(me)
    client.post("/api/saved", json={"organization_id": them.id})

    client.patch(f"/api/saved/{them.id}", json={"note": "   spaced out   "})
    assert client.get("/api/saved").get_json()["saved"][0]["note"] == "spaced out"

    # Cleared rather than stored as an empty string.
    client.patch(f"/api/saved/{them.id}", json={"note": "   "})
    assert client.get("/api/saved").get_json()["saved"][0]["note"] == ""

    assert client.patch(f"/api/saved/{them.id}",
                        json={"note": "x" * 500}).status_code == 200
    assert client.patch(f"/api/saved/{them.id}",
                        json={"note": "x" * 501}).status_code == 400
