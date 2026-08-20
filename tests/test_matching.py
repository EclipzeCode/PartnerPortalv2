"""The ranking rules matching.py exists to produce.

These are the claims the product makes about who it puts in front of whom,
and every one of them has been checked by hand at least once during
development. They are here so the next change to a weight has to say so out
loud.
"""

from matching import (
    MAX_FOCUS_BONUS, MUTUAL_BONUS, SHARED_FOCUS, find_matches, score_pair,
)


def test_mutual_match_scores_above_one_way(make_org):
    """The asymmetry the whole module is built around.

    A one-sided match is a request for a favour; a two-way one is a
    partnership. No amount of one-directional overlap should reorder that.
    """
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    mutual = make_org(needs=["grant_writing"], offers=["web_development"])
    one_way = make_org(
        needs=["legal"],
        offers=["web_development", "design_branding", "marketing_social"],
    )

    mutual_score, _, mutual_detail = score_pair(me, mutual)
    one_way_score, _, one_way_detail = score_pair(me, one_way)

    assert mutual_detail["mutual"] is True
    assert one_way_detail["mutual"] is False
    assert mutual_score > one_way_score


def test_shared_focus_never_outranks_a_real_exchange(make_org):
    """Values alignment is a tiebreaker, not the ranking.

    An organization that ticks every one of your causes but has nothing to
    trade must still rank below one that trades with you and shares none.
    """
    causes = ["food_security", "environment_climate", "veterans",
              "animal_welfare", "mental_health"]
    me = make_org(needs=["web_development"], offers=["grant_writing"],
                  focus_areas=causes)
    trades_only = make_org(needs=["grant_writing"], offers=["web_development"])
    causes_only = make_org(needs=["legal"], offers=["web_development"],
                           focus_areas=causes)

    trade_score, _, _ = score_pair(me, trades_only)
    cause_score, _, cause_detail = score_pair(me, causes_only)

    assert len(cause_detail["shared_focus"]) == len(causes)
    assert trade_score > cause_score


def test_focus_bonus_is_capped(make_org):
    """Otherwise enough shared causes would swamp the exchange entirely."""
    causes = ["food_security", "environment_climate", "veterans",
              "animal_welfare", "mental_health", "arts_culture"]
    base = dict(needs=["web_development"], offers=["grant_writing"],
                location="Nowhere, NA", organization_type="NGO")
    me = make_org(focus_areas=causes, **base)
    one_cause = make_org(needs=["grant_writing"], offers=["web_development"],
                         focus_areas=causes[:1], location="Elsewhere, EL")
    all_causes = make_org(needs=["grant_writing"], offers=["web_development"],
                          focus_areas=causes, location="Elsewhere, EL")

    one_score, _, _ = score_pair(me, one_cause)
    all_score, _, _ = score_pair(me, all_causes)

    # Six shared causes are worth the cap, not six times the per-cause value.
    assert all_score - one_score == MAX_FOCUS_BONUS - SHARED_FOCUS
    assert MAX_FOCUS_BONUS < MUTUAL_BONUS


def test_shared_focus_does_not_create_a_match(session, make_org):
    """Caring about the same thing is not a partnership.

    find_matches selects on needs/offers overlap alone, so an organization
    with everything in common except something to exchange never reaches
    scoring at all.
    """
    causes = ["food_security", "environment_climate", "veterans"]
    me = make_org(needs=["web_development"], offers=["grant_writing"],
                  focus_areas=causes)
    no_trade = make_org(needs=["legal"], offers=["translation"],
                        focus_areas=causes)

    names = [m["name"] for m in find_matches(session, me)]
    assert no_trade.name not in names


def test_incomplete_and_demo_profiles_stay_out_of_matches(session, make_org):
    """Half-filled rows say nothing useful, and examples are fictional."""
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    unfinished = make_org(needs=["grant_writing"], offers=["web_development"],
                          onboarding_complete=False)
    example = make_org(needs=["grant_writing"], offers=["web_development"],
                       is_demo=True)

    names = [m["name"] for m in find_matches(session, me)]
    assert unfinished.name not in names
    assert example.name not in names
    # ...but the examples-only view is exactly how those are surfaced.
    demo_names = [m["name"] for m in find_matches(session, me, demo_only=True)]
    assert example.name in demo_names


def test_an_org_never_matches_itself(session, make_org):
    me = make_org(needs=["web_development"], offers=["web_development"])
    assert me.name not in [m["name"] for m in find_matches(session, me)]


def test_mutual_matches_sort_ahead_of_higher_scoring_one_way(session, make_org):
    """Ordering, not just scoring: the first page is what people act on."""
    me = make_org(needs=["web_development", "design_branding"],
                  offers=["grant_writing"])
    make_org(name="pytest mutual", needs=["grant_writing"],
             offers=["web_development"])
    make_org(name="pytest one way",
             offers=["web_development", "design_branding"], needs=["legal"])

    results = find_matches(session, me)
    mutual_flags = [m["match_detail"]["mutual"] for m in results]
    # Every mutual match appears before every one-way one.
    assert mutual_flags == sorted(mutual_flags, reverse=True)

# --- Explaining the score ---------------------------------------------------
# The number is what the whole list is ordered by, and the page now shows how
# it was reached. That only helps if the parts add up to the total -- a
# breakdown that disagrees with the score beside it is worse than no
# breakdown, because it makes the ranking look broken rather than opaque.

def test_the_breakdown_adds_up_to_the_score(make_org, session):
    me = make_org(needs=["web_development", "volunteers"],
                  offers=["grant_writing"], location="Austin, TX",
                  focus_areas=["food_security"], organization_type="NGO")
    them = make_org(needs=["grant_writing"],
                    offers=["web_development", "volunteers"],
                    location="austin", focus_areas=["food_security"],
                    organization_type="Small Business")

    score, _reasons, detail = score_pair(me, them)
    parts = detail["breakdown"]

    assert parts, "a scoring match should be able to say why"
    assert sum(p["points"] for p in parts) == detail["raw_score"]
    assert detail["raw_score"] == score
    assert detail["capped"] is False


def test_a_capped_score_says_so(make_org):
    """Enough overlap to exceed 100 still displays as 100, so the page has to
    be able to explain why the parts sum higher than the total."""
    everything = ["web_development", "design_branding", "marketing_social",
                  "grant_writing", "legal", "accounting_finance"]
    me = make_org(needs=everything, offers=everything, location="Austin, TX",
                  organization_type="NGO")
    them = make_org(needs=everything, offers=everything, location="Austin, TX",
                    organization_type="Small Business")

    score, _reasons, detail = score_pair(me, them)
    assert score == detail["max_score"]
    assert detail["capped"] is True
    assert detail["raw_score"] > score
    assert sum(p["points"] for p in detail["breakdown"]) == detail["raw_score"]


def test_every_reason_has_a_matching_component(make_org):
    """reasons and breakdown describe the same components, so a score cannot
    name a factor in prose that contributed nothing."""
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    them = make_org(needs=["grant_writing"], offers=["web_development"])

    _score, reasons, detail = score_pair(me, them)
    assert len(reasons) == len(detail["breakdown"])
