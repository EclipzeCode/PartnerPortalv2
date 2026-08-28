"""Bidirectional matching.

The product claim is that a partnership works when *both* sides get something,
so the score is built around two questions asked in both directions:

    they_give = their offers  ∩  my needs      -- what I get out of it
    i_give    = my offers     ∩  their needs   -- what they get out of it

An org that satisfies both is a mutual match and is ranked far above one that
only satisfies one, because a one-sided match is just a request for a favor.
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
    product is built on. The frontend colors those two directions everywhere
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


def _candidates(session, me, *, demo=False):
    """Every organization that could match `me`, as rows cheap enough to rank.

    Nine columns, not the whole row. Both callers below used to
    `select(Organization)` -- every description, every note, every URL, every
    token column on every organization that overlaps the caller -- in order to
    compute a number and, in match_overview's case, keep five of them. On the
    dashboard, which is the page every signed-in visit lands on, that is the
    whole overlapping directory pulled across the network to answer "how
    many".

    What comes back is a SQLAlchemy Row, and rank_pair and score_pair read it
    unchanged: both only ever touch attributes, and a Row named by column has
    them. Nothing about the scoring had to learn about this.

    The WHERE lived twice, once in each caller, and had already drifted --
    find_matches filtered `is_demo.is_(demo_only)` and match_overview
    hardcoded False. Same query now, with the one real difference as an
    argument.

    `demo` is tri-state: False for real organizations, True for the seeded
    examples, and None for both in one pass. The last exists because the
    matches page needs real matches and, only when there are none, the
    examples -- and asking for those separately meant scanning and ranking
    the whole overlapping directory twice for exactly the accounts that have
    no matches yet, which is every account on its first visit. is_demo comes
    back as a column so the caller can tell the two apart afterward.
    """
    from models import Organization

    stmt = select(
        Organization.id,
        Organization.name,
        Organization.needs,
        Organization.offers,
        Organization.focus_areas,
        Organization.location,
        Organization.remote_friendly,
        Organization.organization_type,
        Organization.is_demo,
    ).where(
        Organization.id != me.id,
        Organization.onboarding_complete.is_(True),
        # Hidden by an admin. Matching is discovery like the directory is, so
        # it asks the same question -- an organization taken out of the
        # listings should not reappear as somebody's top match.
        Organization.hidden_at.is_(None),
    )
    if demo is not None:
        stmt = stmt.where(Organization.is_demo.is_(demo))

    # `&&` is "arrays overlap" and is what the GIN indexes accelerate. An org
    # with no categories at all matches nobody, which is correct.
    conditions = []
    if me.needs:
        conditions.append(Organization.offers.overlap(me.needs))
    if me.offers:
        conditions.append(Organization.needs.overlap(me.offers))
    if not conditions:
        return []

    return session.execute(stmt.where(or_(*conditions))).all()


def _hydrate(session, rows):
    """The full organizations for `rows`, in the order given.

    One query for the whole page rather than one per row, and only for the
    ones that survived ranking -- which is the entire point of ranking on
    nine narrow columns first. `in_` on a primary key, so the database does the
    cheapest thing it knows how to do.
    """
    from models import Organization

    if not rows:
        return []
    ids = [row.id for row in rows]
    found = {
        org.id: org
        for org in session.query(Organization).filter(
            Organization.id.in_(ids)
        ).all()
    }
    # Missing means deleted between the two queries, which is a row that
    # should not be in the results anyway.
    return [found[i] for i in ids if i in found]


def _entry(me, them):
    """One organization as the frontend reads it: profile, score, reasons."""
    score, reasons, detail = score_pair(me, them)
    data = them.public_dict()
    data.update({
        "match_score": score,
        "reasons": reasons,
        "match_detail": detail,
    })
    return data


# Mutual matches first, then score, then name -- the one ordering both
# callers use, written once so they cannot drift on what "best" means.
def _rank_key(item):
    mutual, score, name = item
    return (not mutual, -score, (name or "").casefold())


def _rank(me, candidates, *, mutual_only=False):
    """Score `candidates` against `me` and put them in order.

    Returns (ranked, mutual_total), where each ranked entry is
    (mutual, score, name, row) and `mutual_total` counts the two-way matches
    among everything that scored -- not among what a caller goes on to keep,
    which is why it is counted here rather than off the truncated list.

    This loop was written out three times, identically except for whether it
    honored mutual_only. Three copies of "what counts as a match and in what
    order" is three chances for the dashboard's count to disagree with the
    list the matches page draws from the same data.
    """
    ranked = []
    mutual_total = 0
    for them in candidates:
        score, mutual, *_ = rank_pair(me, them)
        if score <= 0:
            continue
        if mutual_only and not mutual:
            continue
        if mutual:
            mutual_total += 1
        ranked.append((mutual, score, them.name, them))

    ranked.sort(key=lambda r: _rank_key(r[:3]))
    return ranked, mutual_total


# How many matches are ever built in full.
#
# There is a cap because every match past it costs a full row fetched and a
# reasons list written, and the page renders a shortlist rather than an index.
# It was fifty and it truncated silently -- an organization with more matches
# than that had no way of knowing, let alone of reaching the rest.
#
# Raised rather than paged, and that is a deliberate departure from what this
# was scoped as. The matches view filters what it is holding, in the browser,
# across every field on the card; paging it server-side would mean a search
# that can only see the page it is on, so typing a name three pages down
# would find nothing. Trading a silent truncation for a search that lies is
# not an improvement.
#
# So the number is generous enough that reaching it means something has
# genuinely changed about the size of this directory, the true total comes
# back beside the page so the truncation can be *said*, and the surface built
# for browsing everything -- the directory, which pages and searches in SQL --
# is where the page points when it happens.
MATCH_LIMIT = 200


def find_matches(session, me, limit=MATCH_LIMIT, mutual_only=False,
                 demo_only=False):
    """Rank other organizations as partners for `me`.

    Returns (matches, total, mutual_total). The last two count everything
    that matched, not what is being returned: a caller that only got `limit`
    of them still has to be able to say how many there were, which is the
    whole difference between a list that stops and a list that stops quietly.

    Only orgs with at least one category in common in either direction are
    considered -- everything else scores nothing, so pulling it out of the
    database would be wasted work.

    Seeded example organizations are excluded by default: a real signup should
    never be paired with something fictional. `demo_only=True` returns exactly
    those instead, for the clearly-labeled "example matches" view shown when
    the real directory is still small.

    Ranked on nine narrow columns, then the survivors are fetched in full. The cap
    is what makes that worth doing: at most `limit` organizations are ever
    hydrated, however many overlap.
    """
    ranked, mutual_total = _rank(me, _candidates(session, me, demo=demo_only),
                                 mutual_only=mutual_only)
    entries = [_entry(me, org)
               for org in _hydrate(session, [r[3] for r in ranked[:limit]])]
    return entries, len(ranked), mutual_total


def find_matches_with_examples(session, me, *, mutual_only=False,
                               limit=MATCH_LIMIT):
    """Real matches, plus the seeded examples when there are none -- one scan.

    What the matches page actually asks for, and it used to ask by calling
    find_matches twice: once for real organizations and, if that came back
    empty, again for the demo ones. Both calls run the same overlap query and
    rank everything it returns, so the account with nothing to show -- a new
    signup, which is exactly who the examples are for -- paid for the whole
    thing twice to be told so.

    One pass over both cohorts, split by is_demo afterward. The examples are
    only ranked out into entries when the real list is empty, so the common
    case does not build prose for organizations nobody will see.

    Returns (matches, total, mutual_total, examples), where the first three
    describe the real matches exactly as find_matches does and `examples` is
    empty whenever there is anything real to show.
    """
    rows = _candidates(session, me, demo=None)
    real = [r for r in rows if not r.is_demo]
    demo = [r for r in rows if r.is_demo]

    ranked, mutual_total = _rank(me, real, mutual_only=mutual_only)
    matches = [_entry(me, org)
               for org in _hydrate(session, [r[3] for r in ranked[:limit]])]

    examples = []
    if not matches:
        demo_ranked, _ = _rank(me, demo, mutual_only=mutual_only)
        examples = [
            _entry(me, org)
            for org in _hydrate(session, [r[3] for r in demo_ranked[:limit]])
        ]

    return matches, len(ranked), mutual_total, examples


def match_overview(session, me, top=5):
    """How many matches, how many are two-way, and the best few.

    What the dashboard actually needs. It used to call find_matches, which
    answers a different question -- "give me every match, fully rendered" --
    and then threw almost all of it away.

    Same candidates and same scoring; the difference is that only `top`
    organizations are fetched in full and given their prose. Everything else
    is the arithmetic in rank_pair, which is what the two paths share.

    Returns (total, mutual_count, top_matches).
    """
    ranked, mutual_count = _rank(me, _candidates(session, me))
    best = [_entry(me, org)
            for org in _hydrate(session, [r[3] for r in ranked[:top]])]
    return len(ranked), mutual_count, best
