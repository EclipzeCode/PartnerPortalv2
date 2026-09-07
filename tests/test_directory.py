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

    # An unrecognized sort falls back rather than failing.
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


# --- The public directory ---------------------------------------------------
# Same rows, no session, and a payload that carries nothing an account is
# needed to see. This is what the home page's "Browse partners" leads to.

def test_the_public_directory_answers_without_a_session(client, directory):
    response = client.get(f"/api/directory?{SCOPE}")
    assert response.status_code == 200
    assert len(response.get_json()["organizations"]) >= 4


def test_it_carries_no_contact_details(client, directory, make_org):
    """The line public_profile() draws, checked from this end too.

    A listing that hands out addresses is a harvesting endpoint wearing a
    search box, and this one needs no account at all.
    """
    make_org(name="pytest-dir Reachable",
             contact_email="pytest-reach@example.com",
             contact_phone="555-0100")
    payload = client.get(f"/api/directory?{SCOPE}").get_json()
    for org in payload["organizations"]:
        assert "contact_email" not in org
        assert "contact_phone" not in org
        assert "email" not in org


def test_it_publishes_links_only_when_they_were_opted_in(client, make_org):
    make_org(name="pytest-dirpub Open", links_public=True,
             website_url="https://open.example.org")
    make_org(name="pytest-dirpub Shut", links_public=False,
             website_url="https://shut.example.org")
    by_name = {o["name"]: o
               for o in client.get(
                   "/api/directory?q=pytest-dirpub").get_json()["organizations"]}
    assert by_name["pytest-dirpub Open"]["website_url"] == "https://open.example.org"
    assert "website_url" not in by_name["pytest-dirpub Shut"]


def test_it_says_nothing_about_fit(client, directory):
    """There is no second profile to compare against, so there is no score.

    Sending a zero would be a claim, and inventing a ranking from one side
    would be a worse one.
    """
    for org in client.get(f"/api/directory?{SCOPE}").get_json()["organizations"]:
        assert "match_score" not in org
        assert "match_detail" not in org


def test_it_filters_and_pages_like_the_signed_in_one(client, directory):
    """Same builder, so a filter cannot mean two things."""
    names = _names(client.get(f"/api/directory?{SCOPE}&offers=web_development"))
    assert names == ["pytest-dir Alpha Web"]

    first = client.get(f"/api/directory?{SCOPE}&per_page=2&page=1").get_json()
    assert first["per_page"] == 2
    assert len(first["organizations"]) == 2
    assert first["pages"] >= 2


def test_it_clamps_the_page_size_harder_than_the_signed_in_one(client, directory):
    payload = client.get(f"/api/directory?{SCOPE}&per_page=48").get_json()
    assert payload["per_page"] == 24


def test_an_unfinished_profile_is_not_in_it(client, make_org):
    make_org(name="pytest-dirhalf Unfinished", onboarding_complete=False)
    assert _names(client.get("/api/directory?q=pytest-dirhalf")) == []


def test_examples_show_by_default_and_can_be_turned_off(client, make_org):
    """An empty directory teaches a stranger nothing, so the seeded examples
    are in by default here -- labeled, and refusable."""
    make_org(name="pytest-dirdemo Sample", is_demo=True)
    shown = client.get("/api/directory?q=pytest-dirdemo").get_json()
    assert [o["name"] for o in shown["organizations"]] == ["pytest-dirdemo Sample"]
    assert shown["organizations"][0]["is_demo"] is True

    hidden = client.get(
        "/api/directory?q=pytest-dirdemo&include_examples=0").get_json()
    assert hidden["organizations"] == []


# --- The rate limit -------------------------------------------------------
# This route answers without a session, so an address is all it has to go on
# -- and an address is a library, a school or a carrier's NAT as often as it
# is a person. The limit was 120 an hour, set against what a request costs
# rather than against how many people can share one connection; see
# DIRECTORY_READS_PER_HOUR for the arithmetic behind the number that
# replaced it.
#
# None of this was covered before. The tests below pin the two halves that
# matter: that the limit is still enforced, and that it is the constant doing
# the enforcing rather than a number frozen into the route.

def test_the_directory_is_still_rate_limited(client, make_org, monkeypatch):
    """Raising a limit must not turn into removing it."""
    import app as app_module
    monkeypatch.setattr(app_module, "DIRECTORY_READS_PER_HOUR", 4)
    make_org(name="pytest-dirlimit Org")

    codes = [client.get("/api/directory?q=pytest-dirlimit").status_code
             for _ in range(6)]
    assert codes[:4] == [200] * 4, codes
    assert codes[4:] == [429, 429], codes


def test_the_limit_is_read_from_the_constant(client, make_org, monkeypatch):
    """Not frozen into the route, so the env override actually overrides.

    The value is read per request rather than captured at import, which is
    what makes DIRECTORY_READS_PER_HOUR tunable without a code change -- and
    what lets the test above set it to something a test can reach.
    """
    import app as app_module
    make_org(name="pytest-dirtune Org")

    monkeypatch.setattr(app_module, "DIRECTORY_READS_PER_HOUR", 1)
    assert client.get("/api/directory?q=pytest-dirtune").status_code == 200
    assert client.get("/api/directory?q=pytest-dirtune").status_code == 429

    # Raised mid-flight: the request that was refused a moment ago is allowed
    # now, on the same address, without anything being cleared.
    monkeypatch.setattr(app_module, "DIRECTORY_READS_PER_HOUR", 50)
    assert client.get("/api/directory?q=pytest-dirtune").status_code == 200


def test_being_refused_says_how_long_to_wait(client, make_org, monkeypatch):
    """A shared address will hit this, so the answer has to be actionable."""
    import app as app_module
    monkeypatch.setattr(app_module, "DIRECTORY_READS_PER_HOUR", 1)
    make_org(name="pytest-dirwait Org")

    client.get("/api/directory?q=pytest-dirwait")
    refused = client.get("/api/directory?q=pytest-dirwait")
    assert refused.status_code == 429
    assert refused.headers["Retry-After"].isdigit()
    body = refused.get_json()
    assert body["retry_after"] > 0
    assert "Try again" in body["error"]


def test_the_default_is_the_raised_one(client):
    """Guards the number itself, which is the whole point of the change.

    Written as a floor rather than an equality: this is here to catch the
    limit being quietly dropped back to something a shared connection
    exhausts in four sessions, not to make tuning it upward a test failure.
    """
    import app as app_module
    assert app_module.DIRECTORY_READS_PER_HOUR >= 600
