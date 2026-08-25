"""Screening organization names for a public directory.

An organization's name is the least optional, most public thing about its
profile: it is what search results, match cards, and public profile pages
lead with, and unlike the description or links there is no way to leave it
blank. That makes it the one field worth actively screening rather than just
length-checking.

This is a plain word-boundary filter, not a general-purpose profanity engine.
It normalizes common leetspeak substitutions ("5h1t" -> "shit") and Unicode
look-alikes (fullwidth/circled letters) before matching each blocked term on
a word boundary, which also keeps it from flagging innocent words that merely
contain one as a substring (e.g. "Scunthorpe", "class", "assistant"). What it
will not catch is a term deliberately broken up with punctuation or spaces
("f u c k") -- closing that gap means matching substrings instead of whole
words, which trades these false negatives for false positives on ordinary
names. For a nonprofit directory, the plain and lightly-obfuscated case is
the realistic threat; a determined bad actor typing punctuation-spaced slurs
is not the case this needs to optimize for.

--- Two lists, not one ---------------------------------------------------

The version of this that shipped first had one list and one answer, and it
turned real organizations away at the door. "Coon Rapids Food Shelf" names a
city in Minnesota. "Cripple Creek" is a town in Colorado. "Fuck Cancer" is an
actual registered nonprofit. Every one of those was refused at signup, at
onboarding, and at invite creation, with a message that named no reason and
no way forward -- and no support inbox behind it, because the contact form is
delivered by mail and mail does not yet leave this app.

So a word is not enough to decide with. The split below is by how much doubt
the term itself carries:

* HARD_BLOCKED is the set where there is no plausible reading. No
  organization is called these, in any language, by accident or otherwise.
  These are refused.

* SOFT_FLAGGED is everything ambiguous: terms that are a slur or a vulgarity
  in one usage and a place name, a surname, a piece of geography or a
  deliberate act of reclamation in another. These are *allowed through* and
  the row is marked, because the cost of being wrong in the two directions is
  not symmetric. A flagged name that turns out to be fine costs somebody a
  glance at a log line. A refused name that was fine costs a real
  organization its account, silently, with no way to appeal.

The line between the two lists is a judgment call and is meant to be moved.
If a term in HARD_BLOCKED starts turning away real organizations, it belongs
in SOFT_FLAGGED; that is a one-line change and needs no migration.

ALLOWED_PHRASES then handles the known-innocent cases so the review queue is
not permanently full of Coon Rapids. It suppresses the *flag*, not a block --
a soft term was going to be allowed either way, so all this decides is
whether anybody is asked to look at it.
"""

import re
import unicodedata

# No plausible reading as anything but a slur. Refused outright.
#
# Deliberately smaller than it could be. A term only earns a place here if
# refusing every organization whose name contains it is the right answer
# without ever seeing the name -- which is a strong claim, and the reason
# most of the original list moved to SOFT_FLAGGED below.
HARD_BLOCKED = frozenset({
    "nigger", "niggers", "nigga", "niggas", "sandnigger",
    "kike", "kikes",
    "faggot", "faggots",
    "chink", "chinks",
    "gook", "gooks",
    "spic", "spics",
    "wetback", "wetbacks",
    "beaner", "beaners",
    "raghead", "ragheads",
    "towelhead", "towelheads",
    "tranny", "trannies",
    "shemale", "shemales",
    "retard", "retarded",
    "cunt", "cunts",
    "motherfucker", "motherfuckers",
    "cocksucker", "cocksuckers",
})

# Ambiguous. Allowed through, and the row is marked so somebody can look.
#
# Every entry here has at least one real reading. The place names and
# surnames are the obvious half -- Coon Rapids, Cripple Creek, Dick as a
# given name, a dyke as an embankment, Gypsy Moth. The less obvious half is
# that emphatic profanity in a nonprofit's name is a deliberate and fairly
# common choice: "Fuck Cancer" has been a registered charity for years, and a
# directory that refuses it is wrong about its own sector.
SOFT_FLAGGED = frozenset({
    # Vulgarity. Real organizations use some of these on purpose.
    "fuck", "fucking", "fucker", "fuckers", "shit", "shitty", "bullshit",
    "asshole", "assholes", "bastard", "bastards", "bitch", "bitches",
    "dick", "dickhead", "prick", "cock", "twat", "twats", "wanker",
    "wankers", "slut", "sluts", "whore", "whores", "piss", "pissed",
    "douche", "douchebag",
    # Slurs that are also ordinary words, place names or surnames, or that
    # the communities they were aimed at have taken back and now use of
    # themselves. A directory that refuses these refuses the organizations
    # most likely to be doing the work.
    "coon", "coons", "jap", "japs", "paki", "pakis",
    "cripple", "cripples", "gypsy", "gypsies", "dyke", "dykes",
    "fag", "fags",
})

# Folded phrases that make a soft match innocent. Written as they come out of
# _fold() -- lower case, leetspeak already resolved -- because that is what
# they are matched against.
#
# Only ever suppresses a flag. Nothing here can unblock a HARD_BLOCKED term,
# so a phrase added carelessly cannot open a hole; the worst it does is stop
# one name reaching a reviewer.
ALLOWED_PHRASES = (
    "coon rapids",      # Minnesota
    "coon valley",      # Wisconsin
    "coon creek",
    "cripple creek",    # Colorado
    "gypsy moth",
    "gypsy hill",
    "dyke road",
    "dyke marsh",
    "jap ridge",
)

# Leetspeak substitutions folded before matching, so obvious character
# swaps ("5h1t", "n1gg3r") land on the same blocked term as the plain word.
_LEET_TABLE = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
    "$": "s", "@": "a", "|": "i",
})


def _pattern(terms):
    return re.compile(
        r"\b(?:" + "|".join(re.escape(t) for t in sorted(terms)) + r")\b"
    )


_HARD_RE = _pattern(HARD_BLOCKED)
_SOFT_RE = _pattern(SOFT_FLAGGED)


def _fold(text):
    # NFKC folds fullwidth, circled, and other Unicode compatibility
    # look-alikes (e.g. the fullwidth "ｆｕｃｋ") down to plain ASCII. NFKD
    # afterward separates accented letters ("ü") from their diacritics so
    # the combining marks can be dropped, folding "fücking" to "fucking".
    nfkc = unicodedata.normalize("NFKC", text or "")
    nfkd = unicodedata.normalize("NFKD", nfkc)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return stripped.lower().translate(_LEET_TABLE)


def _without_allowed(folded):
    """`folded` with every known-innocent phrase removed.

    Removed rather than used to wave the whole name through, so a name that
    contains an allowed phrase *and* something else is still judged on the
    something else: "Coon Rapids" is a city, "Coon Rapids Fuckery" is still
    worth a look.
    """
    for phrase in ALLOWED_PHRASES:
        folded = folded.replace(phrase, " ")
    return folded


def screen_name(name):
    """(problem, flagged) for a name headed for the public directory.

    `problem` is None when the name may be used, or a reason written for the
    person typing it. `flagged` says the name matched something ambiguous and
    should be recorded for review -- it is never a reason to refuse, and a
    caller that ignores it still behaves correctly, just without the record.
    """
    folded = _fold(name)
    if _HARD_RE.search(folded):
        return (
            "That name matched our list of blocked words. If that is wrong, "
            "please get in touch and we will sort it out."
        ), False
    return None, bool(_SOFT_RE.search(_without_allowed(folded)))


def name_problem(name):
    """Only the refusal, for callers that do not record the flag.

    Kept so that "is this name allowed" stays a question with a one-value
    answer wherever the flag has nowhere to go.
    """
    return screen_name(name)[0]
