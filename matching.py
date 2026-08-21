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


def rank_pair(me, them):
    """The arithmetic, with none of the prose.

    Split out so that counting and ranking matches does not also cost
    building them. The dashboard asks how many matches there are, how many
    are two-way, and for the best five -- and used to get a full
    public_dict, a reasons list and a points breakdown for every
    organization overlapping the caller in order to answer that.

    score_pair is a thin wrapper over this rather than a second
    implementation. There is one place the weights are applied, so the fast
    path and the explained path cannot drift into disagreeing about what a
    match is worth -- which matters more here than anywhere else in this
    file, because the whole product is ranked by it.

    Returns (score, mutual, parts, they_give, i_give, shared_focus) where
    `parts` is [(key, points)] in the order the points were awarded.
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
    if not they_give and not i_give:
        return 0, False, [], [], [], []

    parts = []
    if they_give:
        parts.append(("they_give", POINTS_PER_THEY_GIVE * len(they_give)))
    if i_give:
        parts.append(("i_give", POINTS_PER_I_GIVE * len(i_give)))

    mutual = bool(they_give and i_give)
    if mutual:
        parts.append(("mutual", MUTUAL_BONUS))

    if _same_location(me.location, them.location):
        parts.append(("location", SAME_LOCATION))
    elif me.remote_friendly and them.remote_friendly:
        parts.append(("remote", REMOTE_COMPATIBLE))

    if (me.organization_type and them.organization_type
            and me.organization_type != them.organization_type):
        parts.append(("type", COMPLEMENTARY_TYPE))

    # Shared focus areas rank candidates; they never create one. Nothing here
    # widens the pool -- find_matches still selects on needs/offers overlap,
    # so two organizations that care about the same cause but have nothing to
    # exchange are still not a match.
    shared_focus = _overlap(me.focus_areas, them.focus_areas)
    if shared_focus:
        parts.append(("focus", min(SHARED_FOCUS * len(shared_focus),
                                   MAX_FOCUS_BONUS)))

    raw = sum(points for _, points in parts)
    return min(raw, MAX_SCORE), mutual, parts, they_give, i_give, shared_focus


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def score_pair(me, them):
    """Score `them` as a partner for `me`, with the reasons behind it.

    Returns (score, reasons, detail) where detail carries the actual category
    overlaps so the UI can name them rather than saying "you're a good match".

    The number comes from rank_pair; everything added here is language.

    Each reason is {"kind": key, "text": sentence}. It used to be the sentence
    alone, which threw away the one thing the caller could not work out for
    itself: two of these describe a direction -- something coming toward you,
    something going out from you -- and that is the distinction the whole
    product is built on. The frontend colours those two directions everywhere
    else it can, and here it was reduced to matching on the words "They offer"
    at the front of a string, which is a parser waiting to break the first
    time this wording is edited. The key is already in hand at the moment the
    sentence is written; it costs nothing to keep it.
    """
    score, mutual, parts, they_give, i_give, shared_focus = rank_pair(me, them)

    if not parts:
        return 0, [], {
            "they_give": [], "they_give_labels": [],
            "i_give": [], "i_give_labels": [],
            "mutual": False,
            "shared_focus": [], "shared_focus_labels": [],
            "breakdown": [], "raw_score": 0, "capped": False,
            "max_score": MAX_SCORE,
        }

    # What each component is called in the breakdown shown beside the score.
    # A score is a number this file made up, and "87" on its own asks the
    # reader to trust it -- which is a lot to ask of the thing the whole
    # product is ranked by.
    labels = {
        "they_give": lambda: "They offer "
                             + _plural(len(they_give), "thing") + " you need",
        "i_give": lambda: "You offer "
                          + _plural(len(i_give), "thing") + " they need",
        "mutual": lambda: "Two-way match",
        "location": lambda: "Same location",
        "remote": lambda: "Both open to remote",
        "type": lambda: "Different kind of organization",
        "focus": lambda: "Working on the same causes",
    }
    breakdown = [{"label": labels[key](), "points": points}
                 for key, points in parts]

    # Said in the order they are awarded, except the two-way line, which goes
    # first because it is the whole claim the ranking is built on.
    #
    # The kind travels with the sentence. "they_give" and "i_give" are the two
    # directions of the exchange and the UI paints them accordingly; the rest
    # are context and are left neutral.
    sentences = {
        "they_give": lambda: "They offer " + _join(labels_for(they_give))
                             + ", which you need",
        "i_give": lambda: "You offer " + _join(labels_for(i_give))
                          + ", which they need",
        "location": lambda: f"Both based in {them.location}",
        "remote": lambda: "Both open to remote partnerships",
        "type": lambda: "Different kind of organization "
                        f"({them.organization_type})",
        "focus": lambda: "You both work on "
                         + _join(focus_labels_for(shared_focus)),
    }
    reasons = [{"kind": key, "text": sentences[key]()}
               for key, _ in parts if key in sentences]
    if mutual:
        reasons.insert(0, {
            "kind": "mutual",
            "text": "Two-way match — you each have something the other needs",
        })

    raw = sum(points for _, points in parts)
    # The cap is part of the explanation, not something to hide: a breakdown
    # adding to 118 beside a score of 100 reads as an arithmetic error unless
    # the page can say the total was capped.
    return score, reasons, {
        "they_give": they_give,
        "they_give_labels": labels_for(they_give),
        "i_give": i_give,
        "i_give_labels": labels_for(i_give),
        "mutual": mutual,
        "shared_focus": shared_focus,
        "shared_focus_labels": focus_labels_for(shared_focus),
        "breakdown": breakdown,
        "raw_score": raw,
        "capped": raw > MAX_SCORE,
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


def match_overview(session, me, top=5):
    """How many matches, how many are two-way, and the best few.

    What the dashboard actually needs. It used to call find_matches, which
    answers a different question -- "give me every match, fully rendered" --
    and then threw almost all of it away: three numbers and five cards out
    of a full public_dict, reasons list and points breakdown built for every
    organization overlapping the caller.

    Same SQL and same scoring; the difference is that the prose is built for
    `top` organizations instead of all of them. Everything else is the
    arithmetic in rank_pair, which is what the two paths share.

    Returns (total, mutual_count, top_matches).
    """
    from models import Organization

    stmt = select(Organization).where(
        Organization.id != me.id,
        Organization.onboarding_complete.is_(True),
        Organization.is_demo.is_(False),
    )
    conditions = []
    if me.needs:
        conditions.append(Organization.offers.overlap(me.needs))
    if me.offers:
        conditions.append(Organization.needs.overlap(me.offers))
    if not conditions:
        return 0, 0, []
    stmt = stmt.where(or_(*conditions))

    ranked = []
    mutual_count = 0
    for them in session.scalars(stmt):
        score, mutual, parts, *_ = rank_pair(me, them)
        if score <= 0:
            continue
        if mutual:
            mutual_count += 1
        ranked.append((not mutual, -score, (them.name or "").casefold(), them))

    # The same ordering find_matches applies: two-way first, then score, then
    # name. Sorted on the tuple rather than a key function so the comparison
    # is the one written above and nothing falls back to comparing rows.
    ranked.sort(key=lambda r: r[:3])

    best = []
    for _, _, _, them in ranked[:top]:
        score, reasons, detail = score_pair(me, them)
        entry = them.public_dict()
        entry.update({
            "match_score": score,
            "reasons": reasons,
            "match_detail": detail,
        })
        best.append(entry)

    return len(ranked), mutual_count, best
