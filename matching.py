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

from sqlalchemy import and_, func, literal, or_, select

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


def _directions(me):
    """The two overlap tests, as SQL, or None if nothing can match `me`.

    `they_give` is "this organization offers something I need" and `i_give`
    is "it needs something I offer" -- the same two questions rank_pair asks
    in Python, expressed as the `&&` the GIN indexes accelerate. An empty
    list on my side makes its direction impossible rather than universal:
    overlapping with nothing is nothing, which is why each is only built when
    there is something to compare against.

    Returned as the pair rather than pre-combined, because the callers want
    them combined differently -- with OR for "is this a match at all" and
    with AND for "is it a two-way one" -- and those two have to be built from
    the same expressions or the count of mutual matches can disagree with the
    list they are counted from.
    """
    from models import Organization

    they_give = Organization.offers.overlap(me.needs) if me.needs else None
    i_give = Organization.needs.overlap(me.offers) if me.offers else None
    if they_give is None and i_give is None:
        return None
    return they_give, i_give


def _present(*conditions):
    """The conditions that exist, for a caller that may have been given None."""
    return [c for c in conditions if c is not None]


def match_counts(session, me, *, demo=False):
    """(total, mutual) -- how many matches there are, without building any.

    Two numbers the dashboard leads with, and it used to get them by pulling
    every organization overlapping `me` across the network and scoring each
    one in Python. Both are countable in SQL, and this is the whole reason:

      * A candidate is selected on exactly the condition that makes its score
        non-zero. rank_pair returns 0 when they_give and i_give are both
        empty, and the WHERE below is `they_give OR i_give` -- so every row
        the query returns scores above zero and every row it excludes scores
        zero. `total` is therefore the count of that query, not something
        that has to be worked out per row.

      * `mutual` is the same two expressions under AND rather than OR, which
        is rank_pair's definition of a two-way match with nothing else in it.

    The bonuses -- location, organization type, shared focus -- do not appear
    here and must not. They change what a match is *worth*, never whether it
    is one; rank_pair returns early on the two overlaps before any of them is
    considered. That is what keeps these counts honest without a second copy
    of the weights living in SQL.

    One query, not two: count(*) and a FILTERed count read the same scan.
    """
    directions = _directions(me)
    if directions is None:
        return 0, 0
    they_give, i_give = directions

    from models import Organization

    both_ways = they_give is not None and i_give is not None
    stmt = select(
        func.count(),
        # count(*) FILTER (WHERE ...) rather than a second query: the two
        # numbers are read off one scan.
        func.count().filter(and_(they_give, i_give)) if both_ways
        # One of my own lists is empty, so that direction cannot happen for
        # anybody and nothing is mutual. A literal rather than a filter that
        # can never match, so the database is not asked to evaluate a
        # contradiction once per row.
        else literal(0),
    ).where(
        Organization.id != me.id,
        Organization.onboarding_complete.is_(True),
        Organization.hidden_at.is_(None),
        or_(*_present(they_give, i_give)),
    )
    if demo is not None:
        stmt = stmt.where(Organization.is_demo.is_(demo))

    total, mutual = session.execute(stmt).one()
    return total, mutual


def _mutual_candidates(session, me, *, demo=False):
    """Only the two-way matches, as rows cheap enough to rank.

    The narrow half of _candidates. Ranking is mutual-first before it is
    score-first (see _rank_key), so when there are enough of these to fill a
    shortlist, nothing one-directional can reach it however well it scores --
    which means the far larger one-way set never has to leave the database.
    """
    directions = _directions(me)
    if directions is None:
        return []
    they_give, i_give = directions
    if they_give is None or i_give is None:
        return []      # a direction that cannot happen makes mutual impossible

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
        Organization.hidden_at.is_(None),
        they_give,
        i_give,
    )
    if demo is not None:
        stmt = stmt.where(Organization.is_demo.is_(demo))
    return session.execute(stmt).all()


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

    directions = _directions(me)
    if directions is None:
        return []
    they_give, i_give = directions
    return session.execute(stmt.where(or_(*_present(they_give, i_give)))).all()


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


def rank_directory(session, me, rows, *, offset=0, limit=None):
    """One page of `rows`, ordered by how well each fits `me`.

    Returns (organizations, total). The directory's "Best match" sort, and
    the reason it lives here rather than in app.py: ordering by fit is
    _rank_key, and a second definition of "best" written next to the
    directory would be free to disagree with the matches page about which of
    two organizations is the better partner. There is one answer to that
    question in this codebase and this is where it is kept.

    Where this differs from find_matches is what it *keeps*. A match list is
    organizations you could trade with, so anything scoring zero is not a
    weak match, it is not a match, and find_matches drops it. The directory
    is every organization -- that is the whole point of it being a separate
    surface -- so nothing is dropped here and the ones with no overlap sort
    to the bottom. They arrive there on their own: score zero can never be
    mutual, so _rank_key already puts them behind everything that scored.

    `rows` are the narrow rows the caller selected, not full organizations.
    Only the page that survives paging is fetched in full, which is the same
    bargain _candidates and _hydrate strike everywhere else in this file --
    and it is what makes sorting the whole filtered directory by fit
    affordable enough to offer at all.
    """
    def entry(them):
        score, mutual, *_ = rank_pair(me, them)
        return mutual, score, them.name, them

    ordered = sorted((entry(them) for them in rows),
                     key=lambda r: _rank_key(r[:3]))
    total = len(ordered)
    page = ordered[offset:] if limit is None else ordered[offset:offset + limit]
    return _hydrate(session, [r[3] for r in page]), total


def match_overview(session, me, top=5):
    """How many matches, how many are two-way, and the best few.

    What the dashboard actually needs. It used to call find_matches, which
    answers a different question -- "give me every match, fully rendered" --
    and then threw almost all of it away.

    Same scoring as everywhere else; the difference is how little of the
    directory has to cross the network to answer it.

    Returns (total, mutual_count, top_matches).

    Three steps, and the middle one is the point:

    1. The two counts come from match_counts, in SQL. They used to be the
       length of a ranked list, which meant ranking everything that overlaps
       `me` to produce two integers.

    2. The shortlist is taken from the *mutual* candidates alone whenever
       there are at least `top` of them. That is not a heuristic: _rank_key
       orders on `not mutual` before it orders on score, so every two-way
       match outranks every one-directional one however lopsided the scores
       are, and a shortlist that can be filled from the mutual set is already
       final. On any account with five two-way matches -- which is what an
       established profile in a working directory looks like -- the
       one-directional set is never fetched at all, and that is the set that
       grows with the size of the directory.

    3. Only when there are fewer than `top` mutual matches does the full
       overlap scan happen, and then it is the old path exactly.

    The fallback is deliberately not cleverer than that. Picking the best
    one-directional matches without looking at them would mean ordering on
    score in SQL, and score is rank_pair's arithmetic -- weights, bonuses,
    the cap -- which this file exists to keep in one place. A second copy in
    SQL would be free to disagree with the first about what a match is worth,
    which is a worse failure than a scan. The honest bound on that case is a
    materialized score, which is a different change.
    """
    total, mutual_count = match_counts(session, me)
    if not total:
        return 0, 0, []

    if mutual_count >= top:
        ranked, _ = _rank(me, _mutual_candidates(session, me))
    else:
        ranked, _ = _rank(me, _candidates(session, me))

    best = [_entry(me, org)
            for org in _hydrate(session, [r[3] for r in ranked[:top]])]
    return total, mutual_count, best
