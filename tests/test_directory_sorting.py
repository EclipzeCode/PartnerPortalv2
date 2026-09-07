"""The directory's "Best match" sort.

Every card in the signed-in listing leads with a match score, and until now
the sort control offered name and join date only -- a ranking the reader could
see and could not use. Ordering by it cannot be an ORDER BY, because the score
is computed from two profiles and is not a column, so this path ranks the
whole filtered set before it pages.

What is worth testing is precisely what that restructuring could get wrong:

* The order has to be the one the matches page uses, or the directory and the
  matches list disagree about which of two organizations is the better
  partner. Both go through matching._rank_key now; this checks the result.

* Paging has to run over the *ranked* list. Ranking a page is the bug this
  replaces -- it would order twelve arbitrary rows perfectly and call it the
  top twelve.

* The filters have to be the same ones. They moved into _directory_filters so
  both paths could share them, and a sort that quietly showed hidden or
  unfinished profiles would be worse than no sort.

* Nothing scoring zero may be dropped. The directory is every organization;
  that is what makes it a different surface from the matches page.
"""

import app as app_module


NEEDS = ["web_development", "legal"]
OFFERS = ["event_space", "volunteers"]


def _browse(client, **params):
    params.setdefault("sort", "match")
    query = "&".join(f"{k}={v}" for k, v in params.items())
    response = client.get(f"/api/organizations?{query}")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_best_match_orders_by_fit(client, make_org, login):
    """Two-way first, then by score, then everything with no overlap."""
    me = make_org(name="pytest me", needs=NEEDS, offers=OFFERS)
    # Gives what I need and wants what I offer: two-way.
    mutual = make_org(name="pytest zzz mutual",
                      offers=["web_development"], needs=["event_space"])
    # Gives what I need, wants nothing of mine: one direction only.
    one_way = make_org(name="pytest aaa one way",
                       offers=["web_development", "legal"], needs=["mentors"])
    # No overlap in either direction.
    stranger = make_org(name="pytest aaa stranger",
                        offers=["translation"], needs=["tutors"])

    data = _browse(login(me), per_page=48)
    order = [o["id"] for o in data["organizations"]]
    assert order.index(mutual.id) < order.index(one_way.id)
    assert order.index(one_way.id) < order.index(stranger.id)

    # The names deliberately sort the other way round, so this cannot pass by
    # accidentally falling back to alphabetical.
    assert mutual.name > one_way.name


def test_organizations_with_no_overlap_are_kept(client, make_org, login):
    """A directory is every organization, not a match list."""
    me = make_org(needs=NEEDS, offers=OFFERS)
    stranger = make_org(name="pytest no overlap at all",
                        offers=["translation"], needs=["tutors"])

    data = _browse(login(me), per_page=48)
    ids = [o["id"] for o in data["organizations"]]
    assert stranger.id in ids
    assert next(o for o in data["organizations"]
                if o["id"] == stranger.id)["match_score"] == 0


def test_paging_runs_over_the_ranked_list(client, make_org, login):
    """Not over an arbitrary page that was then ranked.

    The best organization is created last and named last alphabetically, so
    it is on the final page of every other sort. Asked for page one by fit,
    it has to be first.
    """
    me = make_org(name="pytest me", needs=NEEDS, offers=OFFERS)
    for i in range(6):
        make_org(name=f"pytest filler {i}",
                 offers=["translation"], needs=["tutors"])
    best = make_org(name="pytest zzzz best",
                    offers=NEEDS, needs=OFFERS)

    first_page = _browse(login(me), per_page=2, page=1)
    assert first_page["organizations"][0]["id"] == best.id
    assert first_page["pages"] > 1

    # And it appears once, on that page only.
    second = _browse(login(me), per_page=2, page=2)
    assert best.id not in [o["id"] for o in second["organizations"]]


def test_it_honors_the_same_filters_as_every_other_sort(client, make_org,
                                                        login):
    """The filters moved out to be shared; this is that sharing."""
    me = make_org(needs=NEEDS, offers=OFFERS)
    match_in_type = make_org(name="pytest included",
                             offers=NEEDS, needs=OFFERS,
                             organization_type="NGO")
    # A better fit, but the wrong type -- the filter has to win over the rank.
    make_org(name="pytest excluded", offers=NEEDS, needs=OFFERS,
             organization_type="Small Business")

    data = _browse(login(me), per_page=48, type="NGO")
    names = [o["name"] for o in data["organizations"]]
    assert "pytest included" in names
    assert "pytest excluded" not in names
    assert data["total"] == len(names)
    assert match_in_type.id in [o["id"] for o in data["organizations"]]


def test_hidden_and_unfinished_profiles_stay_out(client, make_org, login,
                                                 session):
    """The conditions every directory read carries, on this path too."""
    from datetime import datetime, timezone

    me = make_org(needs=NEEDS, offers=OFFERS)
    hidden = make_org(name="pytest hidden", offers=NEEDS, needs=OFFERS)
    unfinished = make_org(name="pytest unfinished", offers=NEEDS,
                          needs=OFFERS, onboarding_complete=False)
    hidden.hidden_at = datetime.now(timezone.utc)
    session.commit()

    data = _browse(login(me), per_page=48)
    ids = [o["id"] for o in data["organizations"]]
    assert hidden.id not in ids
    assert unfinished.id not in ids
    # ...and the caller is never in its own directory.
    assert me.id not in ids


def test_the_public_directory_will_not_sort_by_fit(client, make_org):
    """There is no viewer to be a fit with, so it falls back rather than lies.

    A payload claiming sort=match over rows ordered by name would render the
    wrong option as selected in the page control.
    """
    make_org()
    response = client.get("/api/directory?sort=match")
    assert response.status_code == 200
    assert response.get_json()["sort"] == "name"


def test_an_unknown_sort_still_falls_back(client, make_org, login):
    """Unchanged by adding a third option to the list."""
    me = make_org(needs=NEEDS, offers=OFFERS)
    data = _browse(login(me), sort="nonsense")
    assert data["sort"] == "name"


def test_the_page_number_is_clamped_not_refused(client, make_org, login):
    """Same forgiveness the SQL path gives a stale bookmark."""
    me = make_org(needs=NEEDS, offers=OFFERS)
    make_org(offers=NEEDS, needs=OFFERS)

    data = _browse(login(me), per_page=12, page=99)
    assert data["page"] == data["pages"]
    assert data["organizations"]


def test_match_is_a_recognized_sort(client):
    """Guards the constant the routing reads."""
    assert "match" in app_module.DIRECTORY_SORTS
