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

    Anything unrecognised is dropped rather than raising: a stale category in
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


def label_for(slug):
    """Display label for a slug, falling back to the slug itself."""
    return CATEGORY_LABELS.get(slug, slug)


def labels_for(slugs):
    return [label_for(s) for s in slugs or []]
