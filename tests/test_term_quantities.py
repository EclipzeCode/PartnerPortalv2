"""How much of each term a proposal commits to.

Quantities sit beside the category arrays rather than replacing them, so the
two can disagree if nothing keeps them in step. Most of what follows pins
that they cannot.
"""

import pytest

from units import DEFAULT_UNITS, VALID_UNITS, format_quantity
from categories import VALID_CATEGORIES


@pytest.fixture
def pair(make_org):
    proposer = make_org(name="pytest proposer",
                        needs=["event_space"], offers=["volunteers"])
    recipient = make_org(name="pytest recipient",
                         needs=["volunteers"], offers=["event_space"])
    return proposer, recipient


def _propose(client, recipient, **extra):
    return client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["volunteers"],
        "recipient_gives": ["event_space"],
        **extra,
    })


def test_every_category_has_a_default_unit():
    """The default is what keeps a quantity from being friction: choosing a
    category has already chosen how it is measured."""
    assert set(DEFAULT_UNITS) == VALID_CATEGORIES
    assert set(DEFAULT_UNITS.values()) <= VALID_UNITS


def test_quantities_ride_along_with_the_terms(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    response = _propose(client, recipient, proposer_quantities={
        "volunteers": {"amount": 30, "unit": "people"},
    }, recipient_quantities={
        "event_space": {"amount": 4000, "unit": "sqft"},
    })
    assert response.status_code == 201
    proposal = response.get_json()["proposal"]

    # The label lists every surface already renders now carry the amount, so
    # the card, the agreement and both emails pick it up without changing.
    assert proposal["proposer_gives_labels"] == ["Volunteers - 30 people"]
    assert proposal["recipient_gives_labels"] == [
        "Event or meeting space - 4,000 sq ft"]
    # ...and the structured form is there for anything that has to edit it.
    term = proposal["proposer_gives_terms"][0]
    assert term["slug"] == "volunteers"
    assert term["amount"] == 30
    assert term["unit"] == "people"


def test_a_term_without_an_amount_reads_as_it_always_did(client, login, pair):
    """Every proposal sent before quantities existed is this case."""
    proposer, recipient = pair
    login(proposer)
    proposal = _propose(client, recipient).get_json()["proposal"]
    assert proposal["proposer_gives_labels"] == ["Volunteers"]
    assert proposal["proposer_gives_terms"][0]["amount"] is None
    assert proposal["proposer_gives_terms"][0]["text"] == ""


def test_a_quantity_cannot_qualify_a_term_that_is_not_in_the_proposal(
        client, login, pair):
    """Otherwise the two columns disagree about what was agreed."""
    proposer, recipient = pair
    login(proposer)
    proposal = _propose(client, recipient, proposer_quantities={
        "volunteers": {"amount": 30, "unit": "people"},
        # Not among proposer_gives, and not one of this org's offers either.
        "funding_grants": {"amount": 5000, "unit": "dollars"},
    }).get_json()["proposal"]

    assert list(proposal["proposer_gives_terms"][0].keys())  # sanity
    assert len(proposal["proposer_gives_terms"]) == 1
    assert "funding_grants" not in str(proposal["proposer_gives_labels"])


def test_editing_the_terms_prunes_an_orphaned_quantity(client, login, make_org):
    """Removing a term has to take its amount with it, even when the edit
    says nothing about quantities."""
    proposer = make_org(needs=["event_space"],
                        offers=["volunteers", "food_supplies"])
    recipient = make_org(needs=["volunteers", "food_supplies"],
                         offers=["event_space"])
    login(proposer)
    proposal_id = client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["volunteers", "food_supplies"],
        "recipient_gives": ["event_space"],
        "proposer_quantities": {
            "volunteers": {"amount": 30, "unit": "people"},
            "food_supplies": {"amount": 200, "unit": "items"},
        },
    }).get_json()["proposal"]["id"]

    updated = client.patch(f"/api/proposals/{proposal_id}", json={
        "proposer_gives": ["volunteers"],
    }).get_json()["proposal"]

    assert updated["proposer_gives_labels"] == ["Volunteers - 30 people"]
    assert [t["slug"] for t in updated["proposer_gives_terms"]] == ["volunteers"]


def test_the_escape_hatch_needs_a_label(client, login, pair):
    """`other` with no label is a number nobody can read."""
    proposer, recipient = pair
    login(proposer)

    response = _propose(client, recipient, proposer_quantities={
        "volunteers": {"amount": 12, "unit": "other"},
    })
    assert response.status_code == 400
    assert response.get_json()["field"] == "quantities"

    response = _propose(client, recipient, proposer_quantities={
        "volunteers": {"amount": 12, "unit": "other", "detail": "coach loads"},
    })
    assert response.status_code == 201
    assert response.get_json()["proposal"]["proposer_gives_labels"] == [
        "Volunteers - 12 coach loads"]


def test_a_nonsense_amount_is_refused(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    for amount in ("many", -5, 0, 99_999_999):
        response = _propose(client, recipient, proposer_quantities={
            "volunteers": {"amount": amount, "unit": "people"},
        })
        assert response.status_code == 400, amount
        assert response.get_json()["field"] == "quantities"


def test_quantities_reach_the_public_agreement(client, login, pair):
    """The summary is what somebody shows a funder, and "event space" without
    an amount is the thing this feature exists to stop."""
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient, recipient_quantities={
        "event_space": {"amount": 4000, "unit": "sqft"},
    }).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    token = client.post(
        f"/api/proposals/{proposal_id}/accept").get_json()["proposal"]["share_token"]
    client.post("/logout")

    summary = client.get(f"/api/partnerships/{token}").get_json()["partnership"]
    recipient_party = summary["parties"][1]
    assert recipient_party["gives"] == ["Event or meeting space - 4,000 sq ft"]
    # And the proposer's side reads it as what they receive.
    assert summary["parties"][0]["receives"] == [
        "Event or meeting space - 4,000 sq ft"]


def test_the_vocabulary_is_served_to_the_client(client):
    """The proposal form builds its picker from this rather than carrying its
    own copy, which would drift from what the server validates."""
    body = client.get("/api/categories").get_json()
    slugs = {u["slug"] for u in body["units"]}
    assert slugs == VALID_UNITS
    assert body["default_units"]["event_space"] == "sqft"
    assert body["default_units"]["volunteers"] == "people"


@pytest.mark.parametrize("amount,unit,detail,expected", [
    (30, "people", None, "30 people"),
    (1, "people", None, "1 person"),
    (4000, "sqft", None, "4,000 sq ft"),
    (2500, "dollars", None, "$2,500"),
    (2.5, "hours", None, "2.5 hours"),
    (200, "other", "meals", "200 meals"),
    (None, "people", None, ""),
])
def test_quantities_are_written_the_way_somebody_would_say_them(
        amount, unit, detail, expected):
    assert format_quantity(amount, unit, detail) == expected
