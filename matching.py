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

from categories import labels_for

# Weights. Kept as named constants so tuning is a visible, reviewable change.
POINTS_PER_THEY_GIVE = 12   # each category they offer that I need
POINTS_PER_I_GIVE = 8       # each category I offer that they need
MUTUAL_BONUS = 30           # both directions satisfied at all
SAME_LOCATION = 10
REMOTE_COMPATIBLE = 4
COMPLEMENTARY_TYPE = 5

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

    score = 0
    reasons = []

    if they_give:
        score += POINTS_PER_THEY_GIVE * len(they_give)
        labels = labels_for(they_give)
        reasons.append("They offer " + _join(labels) + ", which you need")

    if i_give:
        score += POINTS_PER_I_GIVE * len(i_give)
        labels = labels_for(i_give)
        reasons.append("You offer " + _join(labels) + ", which they need")

    mutual = bool(they_give and i_give)
    if mutual:
        score += MUTUAL_BONUS
        reasons.insert(0, "Two-way match — you each have something the other needs")

    if _same_location(me.location, them.location):
        score += SAME_LOCATION
        reasons.append(f"Both based in {them.location}")
    elif me.remote_friendly and them.remote_friendly:
        score += REMOTE_COMPATIBLE
        reasons.append("Both open to remote partnerships")

    if (me.organization_type and them.organization_type
            and me.organization_type != them.organization_type):
        score += COMPLEMENTARY_TYPE
        reasons.append(
            f"Different kind of organization ({them.organization_type})"
        )

    return min(score, MAX_SCORE), reasons, {
        "they_give": they_give,
        "they_give_labels": labels_for(they_give),
        "i_give": i_give,
        "i_give_labels": labels_for(i_give),
        "mutual": mutual,
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


def find_matches(session, me, limit=50, mutual_only=False):
    """Rank other organizations as partners for `me`.

    Only orgs with at least one category in common in either direction are
    considered -- everything else scores nothing, so pulling it out of the
    database would be wasted work.
    """
    from models import Organization

    stmt = select(Organization).where(
        Organization.id != me.id,
        Organization.onboarding_complete.is_(True),
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
