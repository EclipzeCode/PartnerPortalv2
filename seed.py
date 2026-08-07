"""Load demo organizations so the matching engine has something to chew on.

    python seed.py          # insert demo orgs (skips ones already present)
    python seed.py --reset  # delete demo orgs first

These are fictional, use .example.org addresses, and have no password set --
they are unclaimed profiles, not accounts. That is deliberate: it is the same
shape a real org's profile takes before they sign up, so you can pre-create a
profile for an org you are recruiting and let them claim it later.

The pairs are built to demonstrate two-way matches: Coders Over Borders needs
what Riverside Tech offers and vice versa, and so on down the list.
"""

import sys

from db import SessionLocal
from models import Organization

DEMO_DOMAIN = ".example.org"

DEMO_ORGS = [
    dict(
        email="hello@codersoverborders" + DEMO_DOMAIN,
        name="Coders Over Borders", organization_type="Non-profit",
        location="Austin, TX", remote_friendly=True,
        offers=["web_development", "it_support"],
        needs=["funding_grants", "marketing_social", "interns"],
        offers_note="We build and maintain websites for small nonprofits.",
        needs_note="We need help getting the word out, and funding to keep going.",
        description="We build free websites and internal tools for small "
                    "nonprofits that cannot afford an agency.",
        partnership_goals="Reach more organizations that need technical help.",
        contact_phone="555-0142",
    ),
    dict(
        email="partnerships@riversidetech" + DEMO_DOMAIN,
        name="Riverside Tech", organization_type="Small Business",
        location="Austin, TX", remote_friendly=False,
        offers=["interns", "mentors", "office_space"],
        needs=["web_development", "community_network"],
        offers_note="We can host interns and provide engineering mentors.",
        needs_note="We want to connect with community organizations locally.",
        description="A 40-person software shop that wants to give local "
                    "students real engineering experience.",
        partnership_goals="Build a pipeline of local student talent.",
        contact_phone="555-0198",
    ),
    dict(
        email="connect@greenearth" + DEMO_DOMAIN,
        name="Green Earth Initiative", organization_type="NGO",
        location="Portland, OR", remote_friendly=True,
        offers=["volunteers", "community_network"],
        needs=["event_space", "legal", "transportation"],
        offers_note="800 active volunteers we can mobilise for a good cause.",
        needs_note="We need somewhere to hold events and help with filings.",
        description="Environmental nonprofit organising community cleanups "
                    "and education programmes.",
        partnership_goals="Run bigger events without renting venues.",
        contact_phone="555-0173",
    ),
    dict(
        email="bookings@lakesidecc" + DEMO_DOMAIN,
        name="Lakeside Community Centre", organization_type="Community Org",
        location="Portland, OR", remote_friendly=False,
        offers=["event_space", "kitchen_facilities", "storage_warehouse"],
        needs=["volunteers", "marketing_social"],
        offers_note="200-person hall and a commercial kitchen, free most weekends.",
        needs_note="We need hands on deck and help filling our calendar.",
        description="Neighbourhood centre with a hall and commercial kitchen "
                    "sitting empty most weekends.",
        partnership_goals="Fill the calendar with programming that serves the area.",
        contact_phone="555-0119",
    ),
    dict(
        email="studio@meridian" + DEMO_DOMAIN,
        name="Studio Meridian", organization_type="Small Business",
        location="Chicago, IL", remote_friendly=True,
        offers=["design_branding", "photography_video", "printing_production"],
        needs=["youth_audience", "community_network"],
        offers_note="Two pro-bono nonprofit rebrands a year, plus print work.",
        needs_note="We want to work with causes reaching young people.",
        description="Small design studio that donates branding work to causes "
                    "our team cares about.",
        partnership_goals="Do work that matters alongside our commercial projects.",
        contact_phone="555-0166",
    ),
    dict(
        email="team@apeers" + DEMO_DOMAIN,
        name="APEERS", organization_type="Non-profit",
        location="Chicago, IL", remote_friendly=False,
        offers=["youth_audience", "mentors", "training_workshops"],
        needs=["design_branding", "funding_grants"],
        offers_note="Direct access to 300 high school students and our mentors.",
        needs_note="Our brand is a decade old and we need grant support.",
        description="Peer mentorship programme serving 300 high school students.",
        partnership_goals="Look as professional as the work we actually do.",
        contact_phone="555-0155",
    ),
    dict(
        email="intake@northgatelegal" + DEMO_DOMAIN,
        name="Northgate Legal Aid", organization_type="Non-profit",
        location="Boston, MA", remote_friendly=True,
        offers=["legal", "board_members"],
        needs=["web_development", "data_analysis"],
        offers_note="Incorporation, 501(c)(3) filings and contract review, free.",
        needs_note="Our site is unusable and we cannot measure our impact.",
        description="Free legal support for small nonprofits: filings, "
                    "contracts, governance.",
        partnership_goals="Help more orgs while spending less time on admin.",
        contact_phone="555-0187",
    ),
    dict(
        email="ops@harvesttable" + DEMO_DOMAIN,
        name="Harvest Table", organization_type="Non-profit",
        location="Denver, CO", remote_friendly=False,
        offers=["food_supplies", "transportation", "storage_warehouse"],
        needs=["volunteers", "data_analysis", "grant_writing"],
        offers_note="Warehouse capacity and refrigerated trucks.",
        needs_note="We need volunteer coordination and help writing grants.",
        description="Regional food bank distributing to 40 partner sites.",
        partnership_goals="Move more food with the capacity we already have.",
        contact_phone="555-0121",
    ),
    dict(
        email="contact@openline" + DEMO_DOMAIN,
        name="Openline Consulting", organization_type="Consulting Firm",
        location="Denver, CO", remote_friendly=True,
        offers=["grant_writing", "strategy_consulting", "data_analysis"],
        needs=["community_network", "design_branding"],
        offers_note="Grant writing, fundraising strategy and board training.",
        needs_note="We need introductions to orgs ready to grow.",
        description="We help small nonprofits build fundraising programmes.",
        partnership_goals="Find organizations at the point where we can help most.",
        contact_phone="555-0107",
    ),
    dict(
        email="hello@cedarvalleyarts" + DEMO_DOMAIN,
        name="Cedar Valley Arts Collective", organization_type="Community Org",
        location="Nashville, TN", remote_friendly=False,
        offers=["event_space", "training_workshops", "equipment_lending"],
        needs=["grant_writing", "accounting_finance", "volunteers"],
        offers_note="Gallery space, teaching artists and equipment to borrow.",
        needs_note="Nobody here knows how to write a grant or keep books.",
        description="Artist collective running workshops and community shows.",
        partnership_goals="Get on a stable financial footing.",
        contact_phone="555-0192",
    ),
    dict(
        email="info@brightpath" + DEMO_DOMAIN,
        name="Bright Path Tutoring", organization_type="Small Business",
        location="Boston, MA", remote_friendly=True,
        offers=["tutors", "training_workshops"],
        needs=["youth_audience", "legal"],
        offers_note="200 donated tutoring hours a year.",
        needs_note="We need to reach students, and help with our contracts.",
        description="Tutoring company donating hours to community programmes.",
        partnership_goals="Get our donated hours to students who need them.",
        contact_phone="555-0134",
    ),
    dict(
        email="hello@summitmarketing" + DEMO_DOMAIN,
        name="Summit Marketing Co.", organization_type="Small Business",
        location="Denver, CO", remote_friendly=True,
        offers=["marketing_social", "media_press", "corporate_network"],
        needs=["volunteers", "event_space"],
        offers_note="One donated campaign per quarter, plus press contacts.",
        needs_note="We need help staffing our own community events.",
        description="Boutique marketing agency donating campaign work to "
                    "local causes.",
        partnership_goals="Put our skills behind visible community work.",
        contact_phone="555-0148",
    ),
]


def seed(reset=False):
    db = SessionLocal()
    try:
        if reset:
            removed = db.query(Organization).filter(
                Organization.email.like("%" + DEMO_DOMAIN)
            ).delete(synchronize_session=False)
            db.commit()
            print(f"Removed {removed} demo organizations.")

        added = skipped = 0
        for spec in DEMO_ORGS:
            exists = db.query(Organization).filter(
                Organization.email == spec["email"]
            ).one_or_none()
            if exists is not None:
                skipped += 1
                continue
            db.add(Organization(
                **spec,
                contact_email=spec["email"],
                onboarding_complete=True,
                password_hash=None,  # unclaimed profile, cannot be logged into
            ))
            added += 1
        db.commit()
        print(f"Added {added} organizations, skipped {skipped} already present.")

        total = db.query(Organization).count()
        print(f"organizations table now holds {total} rows.")
    finally:
        db.close()


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
