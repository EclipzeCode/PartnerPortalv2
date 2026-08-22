"""How much of something a partnership commits to.

A proposal used to say "provides: Event space" and stop there. That is enough
to match on and not enough to agree to: it cannot tell 4,000 square feet from
a cupboard, and it leaves the delivery verdict each side records at completion
(Partnership.proposer_delivered) with no stated standard to judge against.

The vocabulary here is deliberately small, and it is small because of one
thing: **the category supplies the noun, the unit only supplies the
dimension.** "Volunteers" plus 30 plus `people` reads as "30 volunteers"
without `volunteers` ever having to be a unit. That is what stops this list
growing with the category list -- the 33 categories in categories.py map onto
the twelve entries below, and a new category almost always reuses one.

Slugs are the stable identifier and are what lands in the database. Labels are
display-only. Same rule as categories.py: never rename a slug without a
migration.

`other` is the escape hatch, and shipping it is what makes a closed list
survivable -- nobody is ever blocked from describing what they actually have.
It carries a free-text label, renders normally, and is excluded from every
rollup because there is no dimension to roll it up into. Its usage is the
signal for what belongs in this list: a unit that keeps showing up as `other`
has earned a slug.
"""

# (slug, singular, plural, dimension, to_base)
#
# `dimension` is what may be summed together. Two units share a dimension only
# when adding them produces something true: hours and days do, hours and
# sessions do not. `to_base` converts into the dimension's base unit -- hours
# for time, square feet for area -- so a rollup can total "2 days and 3 hours"
# without storing anything other than what was typed.
#
# A dimension of None never aggregates.
UNITS = [
    ("hours",        "hour",        "hours",        "time",         1),
    # Eight, not twenty-four: a day of somebody's time is a working day, and
    # this unit is only ever used for effort. Space measured in days would be
    # `hours` with a bigger number.
    ("days",         "day",         "days",         "time",         8),
    ("people",       "person",      "people",       "people",       1),
    ("sessions",     "session",     "sessions",     "sessions",     1),
    ("items",        "item",        "items",        "items",        1),
    ("places",       "place",       "places",       "places",       1),
    ("trips",        "trip",        "trips",        "trips",        1),
    ("sqft",         "sq ft",       "sq ft",        "area",         1),
    ("sqm",          "sq m",        "sq m",         "area",   10.7639),
    ("dollars",      "dollar",      "dollars",      "money",        1),
    ("deliverables", "deliverable", "deliverables", "deliverables", 1),
    ("other",        "",            "",             None,        None),
]

UNIT_LABELS = {slug: plural for slug, _s, plural, _d, _b in UNITS}
UNIT_SINGULARS = {slug: singular for slug, singular, _p, _d, _b in UNITS}
UNIT_DIMENSIONS = {slug: dimension for slug, _s, _p, dimension, _b in UNITS}
UNIT_TO_BASE = {slug: base for slug, _s, _p, _d, base in UNITS}
VALID_UNITS = frozenset(UNIT_LABELS)

# The unit picked for a category before anybody touches the control.
#
# This is what keeps quantities from being friction. Most proposals need a
# number and nothing else, because choosing "Event space" has already chosen
# square feet. Every category in categories.py appears here; a category with
# no sensible default would be one whose unit the person has to think about,
# and there are none.
#
# Defaults, not restrictions. Any unit may be selected for any category --
# somebody lending a kitchen by the session rather than by the hour is not
# wrong, and a 33x12 matrix of permitted combinations would mostly teach
# people to reach for `other`.
DEFAULT_UNITS = {
    # Skills & services -- time, except where the thing handed over is a
    # finished piece rather than the effort behind it.
    "web_development": "hours",
    "design_branding": "hours",
    "marketing_social": "hours",
    "grant_writing": "hours",
    "legal": "hours",
    "accounting_finance": "hours",
    "it_support": "hours",
    "data_analysis": "hours",
    "translation": "hours",
    "photography_video": "deliverables",
    "training_workshops": "sessions",
    "strategy_consulting": "hours",

    # Space & equipment -- floor area where the space is the point, places
    # where a desk is, hours where it is access to a facility.
    "event_space": "sqft",
    "office_space": "places",
    "kitchen_facilities": "hours",
    "storage_warehouse": "sqft",
    "transportation": "trips",
    "equipment_lending": "items",
    "printing_production": "items",

    # People -- all of them count people. The category says which people.
    "volunteers": "people",
    "mentors": "people",
    "interns": "people",
    "tutors": "people",
    "board_members": "people",

    # Audience & reach -- also people: an audience reached, a network opened.
    "youth_audience": "people",
    "senior_audience": "people",
    "community_network": "people",
    "media_press": "people",
    "corporate_network": "people",
    "donor_network": "people",

    # Direct support -- money where there is a value, items where there is a
    # thing. In-kind donations take a value because that is how they are
    # reported to a funder.
    "funding_grants": "dollars",
    "in_kind_donations": "dollars",
    "food_supplies": "items",
}

# Ceilings, checked so a typo cannot become a headline. Generous enough that
# nothing real hits them: the largest honest value here is a dollar amount or
# a floor area.
MAX_AMOUNT = 10_000_000
MAX_UNIT_DETAIL = 100


def clean_unit(value):
    """A known unit slug, or None."""
    slug = (value or "").strip().lower()
    return slug if slug in VALID_UNITS else None


def default_unit_for(category_slug):
    """The unit a category starts on, or None if it is not a known category."""
    return DEFAULT_UNITS.get(category_slug)


def format_amount(amount):
    """A number written the way somebody would type it.

    Whole numbers lose the decimal point -- "30 volunteers", not
    "30.0 volunteers" -- and thousands are grouped, because four thousand
    square feet is hard to read as 4000.
    """
    if amount is None:
        return ""
    if float(amount) == int(amount):
        return f"{int(amount):,}"
    return f"{float(amount):,.2f}".rstrip("0").rstrip(".")


def format_quantity(amount, unit, detail=None):
    """"30 volunteers", "4,000 sq ft", "$2,500", or "" when there is none.

    Money reads as an amount of money rather than a count of dollars, which
    is the one unit whose label goes in front of the number.
    """
    if amount is None or not unit:
        return ""
    written = format_amount(amount)

    if unit == "other":
        return f"{written} {detail}".strip() if detail else written
    if unit == "dollars":
        return f"${written}"

    one = float(amount) == 1
    label = UNIT_SINGULARS[unit] if one else UNIT_LABELS[unit]
    return f"{written} {label}".strip()


def to_base(amount, unit):
    """`amount` in its dimension's base unit, or None if it does not roll up.

    What the profile totals in step three of this will be built on: two days
    and three hours are nineteen hours, and neither is a number of sessions.
    """
    if amount is None:
        return None
    factor = UNIT_TO_BASE.get(unit)
    if factor is None:
        return None
    return float(amount) * factor
