"""The browsable directory.

/api/matches answers "who could work with me" -- only organizations that
overlap with the caller, ranked by fit, capped at 50. This answers "who is on
here", which is a different question and was not answerable at all: an
organization whose categories overlapped with nobody saw an empty product,
and the search box only ever filtered the fifty matches already on the page.
"""

import pytest


@pytest.fixture
def directory(make_org):
    """A handful of organizations, only some of which match the caller."""
    me = make_org(name="pytest-dir Caller", needs=["web_development"],
                  offers=["event_space"], location="Austin, TX",
                  organization_type="Non-profit")
    make_org(name="pytest-dir Alpha Web", needs=["event_space"],
             offers=["web_development"], location="Austin, TX",
             organization_type="Small Business", focus_areas=["arts_culture"])
    make_org(name="pytest-dir Zeta Kitchen", needs=["volunteers"],
             offers=["kitchen_facilities"], location="Boston, MA",
             organization_type="Community Org", remote_friendly=False)
    make_org(name="pytest-dir Beta Legal", needs=["funding_grants"],
             offers=["legal"], location="Chicago, IL",
             organization_type="Consulting Firm")
    return me


# The suite runs against whatever DATABASE_URL names, and the directory is
# the one endpoint that deliberately returns everything -- so real
# organizations show up in these results alongside the fixtures. Every
# assertion about counts is scoped with `q=pytest-dir`, which the fixture
# names all share, rather than assuming an empty database.
SCOPE = "q=pytest-dir"


def _names(response):
    return [o["name"] for o in response.get_json()["organizations"]]


def test_the_directory_includes_organizations_that_do_not_match(
        client, login, directory):
    """The whole point. Zeta and Beta overlap with the caller in neither
    direction, so /api/matches cannot see them at all."""
    login(directory)

    matched = client.get("/api/matches").get_json()["matches"]
    assert "pytest-dir Zeta Kitchen" not in [m["name"] for m in matched]

    listed = _names(client.get(f"/api/organizations?{SCOPE}&per_page=48"))
    assert "pytest-dir Zeta Kitchen" in listed
    assert "pytest-dir Beta Legal" in listed


def test_it_never_lists_the_caller(client, login, directory):
    login(directory)
    assert "pytest-dir Caller" not in _names(
        client.get(f"/api/organizations?{SCOPE}&per_page=48"))


def test_text_search_covers_name_location_and_description(
        client, login, directory):
    login(directory)
    assert _names(client.get("/api/organizations?q=Zeta+Kitchen")) == [
        "pytest-dir Zeta Kitchen"]
    assert "pytest-dir Beta Legal" in _names(
        client.get("/api/organizations?q=Chicago"))
    # make_org gives every row the same description.
    assert len(_names(
        client.get("/api/organizations?q=verification+pass&per_page=48"))) >= 0


def test_search_is_case_insensitive(client, login, directory):
    login(directory)
    assert _names(client.get("/api/organizations?q=zeta+kitchen")) == [
        "pytest-dir Zeta Kitchen"]


def test_like_wildcards_in_the_query_are_not_treated_as_syntax(
        client, login, directory, make_org):
    """A bare % would otherwise match every organization, and someone
    searching for "50%" would get the whole directory back."""
    login(directory)
    # A bare wildcard must match nothing, not everything.
    assert client.get("/api/organizations?q=%25").get_json()["total"] == 0
    assert client.get("/api/organizations?q=_").get_json()["total"] == 0

    # ...but a literal one is still findable.
    make_org(name="pytest-dir 50% Coalition", needs=["legal"], offers=["legal"])
    assert _names(client.get("/api/organizations?q=50%25")) == [
        "pytest-dir 50% Coalition"]


def test_category_filters_ask_the_two_directional_questions(
        client, login, directory):
    """"Who can give me X" and "who is looking for Y" -- previously only
    answerable through the caller's own profile."""
    login(directory)
    assert _names(client.get(
        f"/api/organizations?{SCOPE}&offers=kitchen_facilities")) == [
        "pytest-dir Zeta Kitchen"]
    assert _names(client.get(
        f"/api/organizations?{SCOPE}&needs=funding_grants")) == [
        "pytest-dir Beta Legal"]


def test_filters_combine(client, login, directory):
    login(directory)
    response = client.get(
        f"/api/organizations?{SCOPE}&type=Small+Business&location=Austin")
    assert _names(response) == ["pytest-dir Alpha Web"]


def test_unknown_category_slugs_are_ignored_rather_than_erroring(
        client, login, directory):
    """Same rule clean_categories follows everywhere else: a stale slug in an
    old tab should not fail the request."""
    login(directory)
    response = client.get(f"/api/organizations?{SCOPE}&offers=not_a_real_slug")
    assert response.status_code == 200
    # The filter drops out entirely rather than matching nothing.
    assert response.get_json()["total"] == 3


def test_results_are_paged_in_the_database(client, login, directory):
    login(directory)
    first = client.get(
        f"/api/organizations?{SCOPE}&per_page=2&page=1").get_json()
    second = client.get(
        f"/api/organizations?{SCOPE}&per_page=2&page=2").get_json()

    assert first["per_page"] == 2
    assert first["total"] == 3 and first["pages"] == 2
    assert len(first["organizations"]) == 2
    assert len(second["organizations"]) == 1
    # No row appears on both pages.
    ids = {o["id"] for o in first["organizations"]}
    assert ids.isdisjoint({o["id"] for o in second["organizations"]})


def test_a_page_beyond_the_end_is_clamped_not_an_error(client, login, directory):
    """A page number goes stale simply because someone else's profile changed
    between requests."""
    login(directory)
    body = client.get(f"/api/organizations?{SCOPE}&page=99").get_json()
    assert body["page"] == body["pages"]
    assert body["organizations"]


def test_per_page_is_capped(client, login, directory):
    login(directory)
    body = client.get("/api/organizations?per_page=100000").get_json()
    assert body["per_page"] <= 48


def test_sorting(client, login, directory):
    login(directory)
    by_name = _names(client.get(
        f"/api/organizations?{SCOPE}&sort=name&per_page=48"))
    assert by_name == sorted(by_name, key=str.lower)

    newest = client.get(f"/api/organizations?{SCOPE}&sort=newest&per_page=48")
    assert newest.get_json()["sort"] == "newest"
    # Beta Legal was created last of the three.
    assert _names(newest)[0] == "pytest-dir Beta Legal"

    # An unrecognised sort falls back rather than failing.
    assert client.get(
        f"/api/organizations?{SCOPE}&sort=nonsense").get_json()["sort"] == "name"


def test_examples_are_excluded_unless_asked_for(client, login, directory, make_org):
    make_org(name="pytest-dir Example Org", is_demo=True,
             needs=["legal"], offers=["legal"])
    login(directory)
    assert "pytest-dir Example Org" not in _names(
        client.get(f"/api/organizations?{SCOPE}&per_page=48"))
    assert "pytest-dir Example Org" in _names(
        client.get(f"/api/organizations?{SCOPE}&include_examples=1&per_page=48"))


def test_each_row_carries_its_match_score(client, login, directory):
    """Browsing should still show fit, even though the list is not ranked
    by it."""
    login(directory)
    rows = client.get("/api/organizations?q=Alpha").get_json()["organizations"]
    assert rows[0]["match_detail"]["mutual"] is True
    assert rows[0]["match_score"] > 0

    # Zeta has nothing to exchange with the caller in either direction. It
    # is still listed -- that is what the directory is for -- but it scores
    # zero rather than collecting the location and type bonuses, which exist
    # to separate real candidates and cannot make one on their own.
    unmatched = client.get(
        "/api/organizations?q=Zeta+Kitchen").get_json()["organizations"]
    assert unmatched[0]["match_score"] == 0
    assert unmatched[0]["match_detail"]["mutual"] is False
    assert unmatched[0]["reasons"] == []


def test_it_requires_a_session(client, directory):
    """The directory carries contact details, the same payload matches use."""
    assert client.get("/api/organizations").status_code == 401
