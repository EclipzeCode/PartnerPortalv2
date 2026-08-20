"""Bidirectional matching.

The product claim is that a partnership works when *both* sides get something,
so the score is built around two questions asked in both directions:

    they_give = their offers  ∩  my needs      -- what I get out of it
    i_give    = my offers     ∩  their needs   -- what they get out of it

An org that satisfies both is a mutual match and is ranked far above one that
only satisfies one, because a one-sided match is just a request for a favour.
That asymmetry is the whole point, so the bonus for mutuality is large enough
that no amount of one-directional overlap can outrank it.

Candidate selection happens in SQL (see find_matches) using the GIN-indexed
`&&` operator; scoring happens here, where the exact overlaps are also needed
to explain the result to the user.
"""

from sqlalchemy import or_, select

from categories import focus_labels_for, labels_for

# Weights. Kept as named constants so tuning is a visible, reviewable change.
POINTS_PER_THEY_GIVE = 12   # each category they offer that I need
POINTS_PER_I_GIVE = 8       # each category I offer that they need
MUTUAL_BONUS = 30           # both directions satisfied at all
SAME_LOCATION = 10
REMOTE_COMPATIBLE = 4
COMPLEMENTARY_TYPE = 5
# Working on the same thing. Kept small, and capped below, on purpose: a
# shared cause makes a partnership easier to talk about, but it is not itself
# an exchange, and this file's whole claim is that a partnership works when
# both sides get something. Uncapped, an organization ticking eight of the
# same boxes could outscore one that actually has what you need, which would
# invert exactly the ranking the weights above exist to produce.
SHARED_FOCUS = 6
MAX_FOCUS_BONUS = 12

MAX_SCORE = 100


def _overlap(a, b):
    """Categories present in both lists, in the order they appear in `a`."""
    other = set(b or [])
    return [item for item in (a or []) if item in other]


def _same_location(a, b):
    """Loose location comparison.

    Locations are free text ("Austin, TX" vs "austin"), so compare on the
    first comma-separated component, case-folded. This is intentionally
    forgiving -- a missed location match only costs a few points.
    """
    if not a or not b:
        return False
    first_a = a.split(",")[0].strip().casefold()
    first_b = b.split(",")[0].strip().casefold()
    return bool(first_a) and first_a == first_b


def score_pair(me, them):
    """Score `them` as a partner for `me`.

    Returns (score, reasons, detail) where detail carries the actual category
    overlaps so the UI can name them rather than saying "you're a good match".
    """
    they_give = _overlap(them.offers, me.needs)
    i_give = _overlap(me.offers, them.needs)

    # No exchange in either direction is not a weak match, it is not a match.
    #
    # Everything below the two overlap terms -- same location, different
    # organization type, shared causes -- separates candidates that already
    # have something to trade. On their own they described a pair with
    # nothing to exchange as a 5, and "5% match" is a claim about a
    # partnership that has no basis at all.
    #
    # This never arose while find_matches was the only caller: its SQL selects
    # on `offers && needs` in one direction or the other, so every candidate
    # it scored had already passed this test. The directory scores everyone,
    # which is what made an unearned score visible.
    if not they_give and not i_give:
        return 0, [], {
            "they_give": [], "they_give_labels": [],
            "i_give": [], "i_give_labels": [],
            "mutual": False,
            "shared_focus": [], "shared_focus_labels": [],
            "breakdown": [], "raw_score": 0, "capped": False,
            "max_score": MAX_SCORE,
        }

    score = 0
    reasons = []
    # The same components as `reasons`, carrying the points each one
    # contributed. A score is a number this file made up, and "87" on its own
    # asks the reader to trust it -- which is a lot to ask of the thing the
    # whole product is ranked by. The arithmetic is already being done here;
    # this stops it being thrown away before anyone can see it.
    breakdown = []

    def award(points, label):
        nonlocal score
        score += points
        breakdown.append({"label": label, "points": points})

    if they_give:
        labels = labels_for(they_give)
        award(POINTS_PER_THEY_GIVE * len(they_give),
              "They offer " + str(len(they_give))
              + (" thing" if len(they_give) == 1 else " things") + " you need")
        reasons.append("They offer " + _join(labels) + ", which you need")

    if i_give:
        labels = labels_for(i_give)
        award(POINTS_PER_I_GIVE * len(i_give),
              "You offer " + str(len(i_give))
              + (" thing" if len(i_give) == 1 else " things") + " they need")
        reasons.append("You offer " + _join(labels) + ", which they need")

    mutual = bool(they_give and i_give)
    if mutual:
        award(MUTUAL_BONUS, "Two-way match")
        reasons.insert(0, "Two-way match — you each have something the other needs")

    if _same_location(me.location, them.location):
        award(SAME_LOCATION, "Same location")
        reasons.append(f"Both based in {them.location}")
    elif me.remote_friendly and them.remote_friendly:
        award(REMOTE_COMPATIBLE, "Both open to remote")
        reasons.append("Both open to remote partnerships")

    if (me.organization_type and them.organization_type
            and me.organization_type != them.organization_type):
        award(COMPLEMENTARY_TYPE, "Different kind of organization")
        reasons.append(
            f"Different kind of organization ({them.organization_type})"
        )

    # Shared focus areas rank candidates; they never create one. Nothing here
    # widens the pool -- find_matches still selects on needs/offers overlap,
    # so two organizations that care about the same cause but have nothing to
    # exchange are still not a match, which is the same line the rest of this
    # file draws.
    shared_focus = _overlap(me.focus_areas, them.focus_areas)
    if shared_focus:
        award(min(SHARED_FOCUS * len(shared_focus), MAX_FOCUS_BONUS),
              "Working on the same causes")
        labels = focus_labels_for(shared_focus)
        reasons.append("You both work on " + _join(labels))

    # The cap is part of the explanation, not something to hide: a breakdown
    # adding to 118 beside a score of 100 reads as an arithmetic error unless
    # the page can say the total was capped.
    total = min(score, MAX_SCORE)
    return total, reasons, {
        "they_give": they_give,
        "they_give_labels": labels_for(they_give),
        "i_give": i_give,
        "i_give_labels": labels_for(i_give),
        "mutual": mutual,
        "shared_focus": shared_focus,
        "shared_focus_labels": focus_labels_for(shared_focus),
        "breakdown": breakdown,
        "raw_score": score,
        "capped": score > MAX_SCORE,
        "max_score": MAX_SCORE,
    }


def _join(labels):
    """Human list: 'A', 'A and B', 'A, B and C'."""
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f" and {labels[-1]}"


def find_matches(session, me, limit=50, mutual_only=False, demo_only=False):
    """Rank other organizations as partners for `me`.

    Only orgs with at least one category in common in either direction are
    considered -- everything else scores nothing, so pulling it out of the
    database would be wasted work.

    Seeded example organizations are excluded by default: a real signup should
    never be paired with something fictional. `demo_only=True` returns exactly
    those instead, for the clearly-labelled "example matches" view shown when
    the real directory is still small.
    """
    from models import Organization

    stmt = select(Organization).where(
        Organization.id != me.id,
        Organization.onboarding_complete.is_(True),
        Organization.is_demo.is_(demo_only),
    )

    # `&&` is "arrays overlap" and is what the GIN indexes accelerate. An org
    # with no categories at all matches nobody, which is correct.
    conditions = []
    if me.needs:
        conditions.append(Organization.offers.overlap(me.needs))
    if me.offers:
        conditions.append(Organization.needs.overlap(me.offers))

    if not conditions:
        return []

    stmt = stmt.where(or_(*conditions))

    results = []
    for them in session.scalars(stmt):
        score, reasons, detail = score_pair(me, them)
        if score <= 0:
            continue
        if mutual_only and not detail["mutual"]:
            continue
        entry = them.public_dict()
        entry.update({
            "match_score": score,
            "reasons": reasons,
            "match_detail": detail,
        })
        results.append(entry)

    # Mutual matches first, then score, then name for a stable order.
    results.sort(
        key=lambda r: (
            not r["match_detail"]["mutual"],
            -r["match_score"],
            (r["name"] or "").casefold(),
        )
    )
    return results[:limit]
