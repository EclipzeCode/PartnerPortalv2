"""match_overview, now that it counts in SQL and narrows what it ranks.

It used to pull every organization overlapping the caller across the network
and score each one in Python to produce two integers and five cards. The two
integers are now aggregates, and the five cards are taken from the mutual
candidates alone whenever there are enough of them -- which rests on a claim
worth testing rather than asserting, namely that _rank_key orders on
mutuality before score, so a shortlist filled from the two-way matches is
already final.

The safety net for all of it is the same idea: a slow, obviously-correct
reference that ranks everything the old way, checked against what
match_overview returns. If the fast path and the reference ever disagree, the
optimization is wrong, and that is the only thing here worth failing on.
"""

import pytest

import matching
from matching import match_counts, match_overview, rank_pair


def _reference(session, me, top=5):
    """What match_overview did before: rank everything, then slice.

    Deliberately written the slow way, straight through _candidates and
    rank_pair, so it has no structure in common with the implementation it is
    checking.
    """
    rows = matching._candidates(session, me)
    ranked = []
    mutual = 0
    for them in rows:
        score, is_mutual, *_ = rank_pair(me, them)
        if score <= 0:
            continue
        if is_mutual:
            mutual += 1
        ranked.append((is_mutual, score, them.name, them))
    ranked.sort(key=lambda r: matching._rank_key(r[:3]))
    return len(ranked), mutual, [r[3].id for r in ranked[:top]]


def _check(session, me, top=5, *, full_scan=None):
    """match_overview agrees with the reference, on all three values.

    `full_scan` additionally pins *which* path ran. Without it a test cannot
    tell the shortcut working from the shortcut never being taken and the old
    code quietly producing the same answer -- which is the way an
    optimization's tests pass while the optimization does nothing.
    """
    calls = []
    original = matching._candidates

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    matching._candidates = spy
    try:
        total, mutual, best = match_overview(session, me, top=top)
    finally:
        matching._candidates = original

    if full_scan is not None:
        assert bool(calls) is full_scan, (
            f"expected full_scan={full_scan}, "
            f"_candidates called {len(calls)} time(s)")

    ref_total, ref_mutual, ref_ids = _reference(session, me, top=top)
    assert (total, mutual) == (ref_total, ref_mutual)
    assert [o["id"] for o in best] == ref_ids
    return total, mutual, best


NEEDS = ["web_development", "legal", "grant_writing"]
OFFERS = ["event_space", "volunteers", "mentors"]


# Counts are asserted as deltas, never as absolutes.
#
# These tests run against the project's real database, alongside whatever
# organizations already live in it -- the seeded examples and any real
# signups. An assertion that `total == 4` is really an assertion about the
# contents of that directory, and it fails the day somebody registers an
# organization that happens to offer web development. What this file is
# actually about is that adding N matchable organizations moves the numbers
# by N, and that match_overview agrees with the reference either way.
def _baseline(session, me):
    return match_counts(session, me)


def test_counts_and_shortlist_match_the_reference(session, make_org):
    """The general case: a mix of two-way, one-way and unrelated."""
    me = make_org(name="pytest me", needs=NEEDS, offers=OFFERS,
                  focus_areas=["education"], location="Austin, TX")
    base_total, base_mutual = _baseline(session, me)
    for i in range(4):
        make_org(name=f"pytest mutual {i}",
                 offers=["web_development"], needs=["event_space"],
                 location="Austin, TX" if i % 2 else "Boston, MA")
    for i in range(6):
        make_org(name=f"pytest oneway {i}",
                 offers=["legal", "grant_writing"], needs=["translation"])
    for i in range(3):
        make_org(name=f"pytest reverse {i}",
                 offers=["translation"], needs=["volunteers", "mentors"])
    make_org(name="pytest unrelated", offers=["translation"], needs=["tutors"])

    total, mutual, _ = _check(session, me)
    assert mutual - base_mutual == 4
    # Thirteen added that match in some direction; the unrelated one does not.
    assert total - base_total == 13


def test_the_mutual_shortcut_is_taken_and_still_correct(session, make_org):
    """Five two-way matches, so the one-way set must never be fetched.

    The agreement with the reference is what makes it correct; full_scan is
    what makes it a test of the optimization rather than of the answer.
    """
    me = make_org(name="pytest me", needs=NEEDS, offers=OFFERS)
    base_total, base_mutual = _baseline(session, me)
    for i in range(5):
        make_org(name=f"pytest mutual {i}",
                 offers=["web_development", "legal"],
                 needs=["event_space", "volunteers"])
    # A one-directional match with a big overlap. It scores well and must
    # still lose to every two-way match, which is the ordering claim the
    # shortcut depends on.
    loud = make_org(name="pytest loud one way",
                    offers=NEEDS, needs=["translation"])

    total, mutual, best = _check(session, me, full_scan=False)
    assert mutual - base_mutual == 5
    assert loud.id not in [o["id"] for o in best]
    # ...and it really does outscore some of them on points alone.
    assert max(rank_pair(me, o)[0] for o in [loud]) > 0


def test_the_full_scan_is_used_when_there_are_too_few_mutual(session,
                                                             make_org):
    """Below `top` two-way matches, the shortlist has to include one-way ones.

    `top` is derived from the mutual count rather than fixed at five. How
    many two-way matches exist depends on the directory this runs against,
    so a hardcoded five decides which path runs by accident -- and the
    accident is invisible, because both paths return the same answer.
    """
    me = make_org(name="pytest me", needs=NEEDS, offers=OFFERS)
    base_total, base_mutual = _baseline(session, me)
    make_org(name="pytest only mutual",
             offers=["web_development"], needs=["event_space"])
    for i in range(4):
        make_org(name=f"pytest oneway {i}", offers=["legal"],
                 needs=["translation"])

    mutual = match_counts(session, me)[1]
    total, _m, best = _check(session, me, top=mutual + 2, full_scan=True)
    assert mutual - base_mutual == 1
    # Filled out past the two-way matches with one-directional ones.
    assert len(best) == mutual + 2


def test_exactly_top_mutual_is_the_boundary(session, make_org):
    """Where the two paths meet. Checked from both sides of it."""
    me = make_org(name="pytest me", needs=NEEDS, offers=OFFERS)
    for i in range(3):
        make_org(name=f"pytest mutual {i}",
                 offers=["web_development"], needs=["event_space"])
    for i in range(4):
        make_org(name=f"pytest oneway {i}", offers=["legal"],
                 needs=["translation"])

    # Taken from the database rather than assumed: the boundary is at
    # whatever the real mutual count is, which includes whatever the
    # directory already held.
    mutual = match_counts(session, me)[1]
    assert mutual >= 3
    _check(session, me, top=mutual, full_scan=False)      # count == top
    _check(session, me, top=mutual + 1, full_scan=True)   # count < top


def test_an_organization_that_matches_nothing_added_is_not_counted(session,
                                                                   make_org):
    me = make_org(needs=["translation"], offers=["tutors"])
    base_total, base_mutual = _baseline(session, me)
    stranger = make_org(offers=["legal"], needs=["event_space"])

    total, mutual, best = _check(session, me)
    assert (total, mutual) == (base_total, base_mutual)
    assert stranger.id not in [o["id"] for o in best]


def test_the_mutual_query_returns_only_mutual_matches(session, make_org):
    """The narrowing itself, asserted on the rows rather than on the answer.

    Everything else in this file would still pass if _mutual_candidates
    fetched the whole overlapping directory: _rank re-sorts whatever it is
    given and mutual matches come first regardless, so the shortlist would be
    identical and only the cost would be wrong. Since the cost is the entire
    point of the change, it needs an assertion of its own -- this is the one
    test here that fails if the query stops being narrow while staying
    correct.
    """
    me = make_org(name="pytest me", needs=NEEDS, offers=OFFERS)
    make_org(name="pytest mutual",
             offers=["web_development"], needs=["event_space"])
    make_org(name="pytest oneway", offers=["legal"], needs=["translation"])
    make_org(name="pytest reverse", offers=["translation"], needs=["mentors"])

    rows = matching._mutual_candidates(session, me)
    assert rows, "expected at least the two-way match created above"
    for row in rows:
        assert rank_pair(me, row)[1] is True, f"{row.name} is not a two-way match"

    # And it is the whole mutual set, not merely a subset of it: exactly the
    # rows _candidates returns that rank_pair calls mutual.
    expected = {r.id for r in matching._candidates(session, me)
                if rank_pair(me, r)[1]}
    assert {r.id for r in rows} == expected


def test_an_organization_with_no_categories_matches_nobody(session, make_org):
    """Both directions impossible, so the query is never even run."""
    me = make_org(needs=[], offers=[])
    make_org(offers=["legal"], needs=["event_space"])
    assert match_counts(session, me) == (0, 0)
    assert match_overview(session, me) == (0, 0, [])


def test_one_empty_side_makes_nothing_mutual(session, make_org):
    """Needs but no offers: matches are possible, two-way ones are not.

    The branch in match_counts that returns a literal zero rather than a
    filter, and the early return in _mutual_candidates that goes with it.
    """
    me = make_org(name="pytest me", needs=NEEDS, offers=[])
    base_total, base_mutual = _baseline(session, me)
    for i in range(3):
        make_org(name=f"pytest gives {i}", offers=["legal"], needs=NEEDS)

    total, mutual, best = _check(session, me)
    assert total - base_total == 3
    # No offers of my own, so nothing can be two-way -- for the organizations
    # added here or for any already in the directory.
    assert mutual == 0 and base_mutual == 0
    assert matching._mutual_candidates(session, me) == []


def test_hidden_unfinished_and_demo_orgs_are_not_counted(session, make_org):
    """The counts ask the same eligibility question the candidate query does."""
    from datetime import datetime, timezone

    me = make_org(name="pytest me", needs=NEEDS, offers=OFFERS)
    base_total, base_mutual = _baseline(session, me)
    real = make_org(name="pytest real",
                    offers=["web_development"], needs=["event_space"])
    hidden = make_org(name="pytest hidden",
                      offers=["web_development"], needs=["event_space"])
    hidden.hidden_at = datetime.now(timezone.utc)
    make_org(name="pytest unfinished", offers=["web_development"],
             needs=["event_space"], onboarding_complete=False)
    make_org(name="pytest demo", offers=["web_development"],
             needs=["event_space"], is_demo=True)
    session.commit()

    total, mutual, best = _check(session, me)
    # Four added, one of them eligible.
    assert total - base_total == 1
    assert mutual - base_mutual == 1
    ids = [o["id"] for o in best]
    assert real.id in ids
    assert hidden.id not in ids


@pytest.mark.parametrize("top", [1, 2, 5, 10])
def test_it_agrees_with_the_reference_at_every_shortlist_size(session,
                                                              make_org, top):
    """`top` decides which path is taken, so it is what to vary."""
    me = make_org(name="pytest me", needs=NEEDS, offers=OFFERS,
                  focus_areas=["education"], location="Austin, TX",
                  organization_type="NGO")
    for i in range(6):
        make_org(name=f"pytest mutual {i}",
                 offers=["web_development", "legal"][: (i % 2) + 1],
                 needs=["event_space", "volunteers"][: (i % 2) + 1],
                 focus_areas=["education"] if i % 3 else [],
                 location="Austin, TX" if i % 2 else "Boston, MA",
                 organization_type="Small Business" if i % 2 else "NGO")
    for i in range(5):
        make_org(name=f"pytest oneway {i}", offers=["grant_writing"],
                 needs=["translation"])

    _check(session, me, top=top)
