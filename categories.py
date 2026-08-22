"""Canonical need/offer categories.

Matching used to compare free text with substring checks, which meant
"we need help with web development" never matched an org offering
"Web Development, Design" -- neither string contains the other. Structured
slugs make an overlap a real, checkable fact instead of a coincidence.

Both sides of the platform use the same vocabulary: what one org *offers* is
drawn from the same list as what another org *needs*. That symmetry is what
makes bidirectional matching possible at all.

Slugs are the stable identifier and are what lands in the database. Labels are
display-only and can be reworded freely. Never rename a slug without a
migration -- existing rows store the slug, not the label.
"""

# Ordered groups, used to lay out the onboarding form.
CATEGORY_GROUPS = [
    ("Skills & services", [
        ("web_development", "Website & app development"),
        ("design_branding", "Design & branding"),
        ("marketing_social", "Marketing & social media"),
        ("grant_writing", "Grant writing"),
        ("legal", "Legal help"),
        ("accounting_finance", "Accounting & bookkeeping"),
        ("it_support", "IT & tech support"),
        ("data_analysis", "Data & evaluation"),
        ("translation", "Translation & interpreting"),
        ("photography_video", "Photography & video"),
        ("training_workshops", "Training & workshops"),
        ("strategy_consulting", "Strategy & planning"),
    ]),
    ("Space & equipment", [
        ("event_space", "Event or meeting space"),
        ("office_space", "Office or desk space"),
        ("kitchen_facilities", "Kitchen facilities"),
        ("storage_warehouse", "Storage or warehouse"),
        ("transportation", "Transportation & delivery"),
        ("equipment_lending", "Equipment lending"),
        ("printing_production", "Printing & production"),
    ]),
    ("People", [
        ("volunteers", "Volunteers"),
        ("mentors", "Mentors"),
        ("interns", "Interns"),
        ("tutors", "Tutors & instructors"),
        ("board_members", "Board members & advisors"),
    ]),
    ("Audience & reach", [
        ("youth_audience", "Access to young people"),
        ("senior_audience", "Access to seniors"),
        ("community_network", "Community network"),
        ("media_press", "Media & press contacts"),
        ("corporate_network", "Corporate connections"),
        ("donor_network", "Donor network"),
    ]),
    ("Direct support", [
        ("funding_grants", "Funding or grants"),
        ("in_kind_donations", "In-kind donations"),
        ("food_supplies", "Food & supplies"),
    ]),
]

# slug -> label, flattened for lookups.
CATEGORY_LABELS = {
    slug: label
    for _group, entries in CATEGORY_GROUPS
    for slug, label in entries
}

VALID_CATEGORIES = frozenset(CATEGORY_LABELS)

# What an organization works on, as opposed to what it needs or offers.
#
# A separate vocabulary from CATEGORY_GROUPS on purpose. Needs and offers are
# two sides of one exchange and are drawn from the same list, which is what
# makes an overlap between them meaningful. A focus area is neither -- "we
# work on food security" is not something anyone trades, it is who the
# organization is -- so putting it in that list would let it be picked as a
# need or an offer and quietly corrupt matching.
#
# Deliberately causes rather than credentials. Nothing here is verified, and
# nothing here is scored: these say what an organization works on, and the
# only thing done with them is showing two organizations where they overlap.
# Counting them into a rating would turn a list of self-declared ticks into
# something that reads as a measure of how much good a group actually does,
# which is a claim this data cannot support.
FOCUS_AREAS = [
    ("environment_climate", "Environment & climate"),
    ("food_security", "Food security & hunger"),
    ("housing_homelessness", "Housing & homelessness"),
    ("education_youth", "Education & youth"),
    ("health_wellbeing", "Health & wellbeing"),
    ("mental_health", "Mental health"),
    ("racial_equity", "Racial equity"),
    ("disability_inclusion", "Disability & accessibility"),
    ("gender_equality", "Gender equality"),
    ("lgbtq_inclusion", "LGBTQ+ inclusion"),
    ("immigrants_refugees", "Immigrants & refugees"),
    ("seniors_aging", "Seniors & aging"),
    ("veterans", "Veterans & military families"),
    ("arts_culture", "Arts & culture"),
    ("animal_welfare", "Animal welfare"),
    ("economic_opportunity", "Jobs & economic opportunity"),
    ("civic_engagement", "Civic engagement"),
    ("digital_inclusion", "Digital inclusion"),
]

FOCUS_AREA_LABELS = dict(FOCUS_AREAS)

# How big the two vocabularies are. Named here rather than counted at each call
# site: the dashboard draws "needs listed, n of 33" as a ratio, and a 33 typed
# into a stylesheet or a script is a number that goes stale the first time a
# category is added.
CATEGORY_TOTAL = sum(len(entries) for _name, entries in CATEGORY_GROUPS)
FOCUS_TOTAL = len(FOCUS_AREAS)
VALID_FOCUS_AREAS = frozenset(FOCUS_AREA_LABELS)

# How long a proposed partnership is meant to run. Slugs are stored; labels are
# display-only, same rule as categories.
TIMELINE_OPTIONS = [
    ("one_off", "One-off — a single event or project"),
    ("one_month", "About a month"),
    ("three_months", "About three months"),
    ("six_months", "About six months"),
    ("one_year", "About a year"),
    ("ongoing", "Ongoing, no end date"),
]

TIMELINE_LABELS = dict(TIMELINE_OPTIONS)
VALID_TIMELINES = frozenset(TIMELINE_LABELS)

ORGANIZATION_TYPES = [
    "Non-profit",
    "NGO",
    "Community Org",
    "Small Business",
    "Startup",
    "Social Enterprise",
    "School or University",
    "Government Agency",
    "Foundation",
    "Consulting Firm",
    "Other",
]


def clean_categories(values):
    """Filter arbitrary client input down to known slugs.

    Anything unrecognized is dropped rather than raising: a stale category in
    an old browser tab should not fail the whole submission. Order is preserved
    and duplicates removed so stored arrays stay stable and comparable.
    """
    if not isinstance(values, (list, tuple)):
        return []
    seen = []
    for value in values:
        if isinstance(value, str) and value in VALID_CATEGORIES and value not in seen:
            seen.append(value)
    return seen


def clean_focus_areas(values):
    """Same filtering as clean_categories, against the focus vocabulary."""
    if not isinstance(values, (list, tuple)):
        return []
    seen = []
    for value in values:
        if isinstance(value, str) and value in VALID_FOCUS_AREAS and value not in seen:
            seen.append(value)
    return seen


def label_for(slug):
    """Display label for a slug, falling back to the slug itself."""
    return CATEGORY_LABELS.get(slug, slug)


def labels_for(slugs):
    return [label_for(s) for s in slugs or []]


def focus_label_for(slug):
    return FOCUS_AREA_LABELS.get(slug, slug)


def focus_labels_for(slugs):
    return [focus_label_for(s) for s in slugs or []]
