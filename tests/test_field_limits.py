"""Input that is too long, and terms neither side offered.

Both of these reached Postgres before anything checked them. An over-length
name arrived as StringDataRightTruncation -- a DataError, which is not an
IntegrityError and so was caught nowhere, surfacing as a 500 for someone who
typed a long organization name. Proposal terms were filtered against the
category vocabulary and nothing else, so a request could commit either side
to providing something it had never listed.
"""

from categories import VALID_CATEGORIES


def test_register_rejects_an_over_length_name(client):
    """A 300-character name is a 400 naming the field, not a 500."""
    response = client.post("/register", json={
        "name": "N" * 300,
        "email": "pytest-longname@example.com",
        "password": "Test1234!verify",
    })
    assert response.status_code == 400
    body = response.get_json()
    assert body["field"] == "name"
    assert "255" in body["error"]


def test_onboarding_rejects_over_length_fields(client, make_org, login):
    """Every String column written from the form is checked against its width."""
    org = make_org(offers=["volunteers"], needs=["funding_grants"])
    login(org)

    base = {
        "organization_name": "pytest onboarding org",
        "organization_type": "NGO",
        "location": "Testville, TS",
        "needs": ["funding_grants"],
        "offers": ["volunteers"],
    }

    # contact_phone is the narrowest column at 32, and the easiest to exceed
    # by accident -- a number with an extension is already close.
    response = client.post("/api/onboarding", json={
        **base, "contact_phone": "+1 (555) 555-5555 extension 12345678901234",
    })
    assert response.status_code == 400
    assert response.get_json()["field"] == "contact_phone"

    response = client.post("/api/onboarding", json={**base, "location": "L" * 300})
    assert response.status_code == 400
    assert response.get_json()["field"] == "location"

    # Text columns have no width to overflow, but were unbounded entirely.
    response = client.post("/api/onboarding", json={**base, "description": "D" * 5000})
    assert response.status_code == 400
    assert response.get_json()["field"] == "description"


def test_onboarding_accepts_a_name_at_the_limit(client, make_org, login):
    """The cap is the column width, not one short of it."""
    org = make_org(offers=["volunteers"], needs=["funding_grants"])
    login(org)
    response = client.post("/api/onboarding", json={
        "organization_name": "N" * 255,
        "organization_type": "NGO",
        "location": "Testville, TS",
        "needs": ["funding_grants"],
        "offers": ["volunteers"],
    })
    assert response.status_code == 200


def _propose(client, recipient, **overrides):
    payload = {
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["volunteers"],
    }
    payload.update(overrides)
    return client.post("/api/proposals", json=payload)


def test_proposal_terms_must_be_on_the_proposer_s_own_offer_list(
        client, make_org, login):
    """You cannot commit yourself to something you never said you offer."""
    proposer = make_org(offers=["grant_writing"], needs=["volunteers"])
    recipient = make_org(offers=["volunteers"], needs=["grant_writing"])
    login(proposer)

    response = _propose(client, recipient, proposer_gives=["legal"])
    assert response.status_code == 400
    body = response.get_json()
    assert body["field"] == "proposer_gives"
    assert "Legal help" in body["error"]


def test_proposal_terms_must_be_on_the_recipient_s_own_offer_list(
        client, make_org, login):
    """The one that matters: an agreement must not claim they offered
    something they never listed. That claim is what reaches their inbox and
    the public summary page."""
    proposer = make_org(offers=["grant_writing"], needs=["volunteers"])
    recipient = make_org(offers=["volunteers"], needs=["grant_writing"])
    login(proposer)

    response = _propose(client, recipient, recipient_gives=["funding_grants"])
    assert response.status_code == 400
    body = response.get_json()
    assert body["field"] == "recipient_gives"
    assert "Funding or grants" in body["error"]


def test_a_valid_slug_is_not_enough_on_its_own(client, make_org, login):
    """The category exists and is spelled correctly -- that was the only
    check before, and it is not the question being asked."""
    proposer = make_org(offers=["grant_writing"], needs=["volunteers"])
    recipient = make_org(offers=["volunteers"], needs=["grant_writing"])
    login(proposer)

    assert "office_space" in VALID_CATEGORIES
    assert _propose(client, recipient,
                    recipient_gives=["office_space"]).status_code == 400


def test_terms_drawn_from_both_offer_lists_are_accepted(client, make_org, login):
    """The path the form actually takes still works."""
    proposer = make_org(offers=["grant_writing"], needs=["volunteers"])
    recipient = make_org(offers=["volunteers"], needs=["grant_writing"])
    login(proposer)

    response = _propose(client, recipient)
    assert response.status_code == 201, response.get_data(as_text=True)


def test_proposal_message_is_capped(client, make_org, login):
    proposer = make_org(offers=["grant_writing"], needs=["volunteers"])
    recipient = make_org(offers=["volunteers"], needs=["grant_writing"])
    login(proposer)

    response = _propose(client, recipient, message="m" * 5000)
    assert response.status_code == 400
    assert response.get_json()["field"] == "message"
