"""Blocking inappropriate organization names.

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
"""

import re
import unicodedata

# Slurs (racial, ethnic, homophobic, transphobic, ableist, misogynistic) and
# strong profanity/vulgarity. Deliberately excludes mild words ("hell",
# "damn", "crap") that have common non-offensive uses (place names, idioms)
# and would produce more false positives than value.
BLOCKED_TERMS = frozenset({
    # Profanity / vulgarity
    "fuck", "fucking", "fucker", "fuckers", "motherfucker", "motherfuckers",
    "shit", "shitty", "bullshit", "asshole", "assholes", "bastard",
    "bastards", "bitch", "bitches", "cunt", "cunts", "dick", "dickhead",
    "prick", "cock", "cocksucker", "twat", "twats", "wanker", "wankers",
    "slut", "sluts", "whore", "whores", "piss", "pissed", "douche",
    "douchebag", "retard", "retarded",
    # Slurs
    "nigger", "nigga", "niggers", "niggas", "chink", "chinks", "gook",
    "gooks", "spic", "spics", "wetback", "wetbacks", "beaner", "beaners",
    "kike", "kikes", "raghead", "ragheads", "towelhead", "towelheads",
    "sandnigger", "faggot", "faggots", "fag", "fags", "dyke", "dykes",
    "tranny", "trannies", "shemale", "shemales", "gypsy", "gypsies",
    "coon", "coons", "jap", "japs", "paki", "pakis", "cripple", "cripples",
})

# Leetspeak substitutions folded before matching, so obvious character
# swaps ("5h1t", "n1gg3r") land on the same blocked term as the plain word.
_LEET_TABLE = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
    "$": "s", "@": "a", "|": "i",
})

_BLOCKED_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in sorted(BLOCKED_TERMS)) + r")\b"
)


def _fold(text):
    # NFKC folds fullwidth, circled, and other Unicode compatibility
    # look-alikes (e.g. the fullwidth "ｆｕｃｋ") down to plain ASCII. NFKD
    # afterward separates accented letters ("ü") from their diacritics so
    # the combining marks can be dropped, folding "fücking" to "fucking".
    nfkc = unicodedata.normalize("NFKC", text)
    nfkd = unicodedata.normalize("NFKD", nfkc)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return stripped.lower().translate(_LEET_TABLE)


def name_problem(name):
    """None if `name` is fine for a public directory, otherwise why it isn't."""
    if _BLOCKED_RE.search(_fold(name)):
        return "an appropriate organization name"
    return None
