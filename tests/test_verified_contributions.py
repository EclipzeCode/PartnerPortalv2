"""Verified contributions: totals of what partners confirmed an org delivered.

Only completed partnerships count, and only the side the *other* party said
delivered. Public only when the organization opts in and at least
MIN_VERIFIED_PARTNERS different partners have confirmed.
"""

from datetime import datetime, timezone

import pytest

import app as app_module
from models import Partnership


@pytest.fixture
def giver(make_org):
    return make_org(name="pytest giver")


def _completed(session, giver, partner, *, delivered=True, giver_proposes=True,
               gives=("volunteers",), quantities=None,
               status=Partnership.COMPLETED):
    """A partnership in which `giver` gave `gives`, judged by `partner`."""
    proposer, recipient = (giver, partner) if giver_proposes else (partner, giver)
    side = "proposer" if giver_proposes else "recipient"
    other = "recipient" if giver_proposes else "proposer"
    p = Partnership(**{
        "proposer_id": proposer.id, "recipient_id": recipient.id,
        "proposer_name": proposer.name, "recipient_name": recipient.name,
        "status": status,
        f"{side}_gives": list(gives), f"{other}_gives": ["event_space"],
        f"{side}_quantities": quantities or {},
        f"{side}_delivered": delivered,
        "completed_at": datetime.now(timezone.utc),
    })
    session.add(p)
    session.commit()
    return p


def test_totals_count_only_what_the_partner_confirmed(
        session, giver, make_org):
    a, b, c, d = (make_org() for _ in range(4))
    _completed(session, giver, a, quantities={
        "volunteers": {"amount": 10, "unit": "people"}})
    # Same category, other direction, other partner: adds up.
    _completed(session, giver, b, giver_proposes=False, quantities={
        "volunteers": {"amount": 5, "unit": "people"}})
    # The partner said they did not deliver: excluded.
    _completed(session, giver, c, delivered=False, quantities={
        "volunteers": {"amount": 100, "unit": "people"}})
    # Not completed: excluded.
    _completed(session, giver, d, status=Partnership.ACCEPTED, quantities={
        "volunteers": {"amount": 100, "unit": "people"}})

    verified = app_module.verified_contributions(session, giver)
    assert verified["partners"] == 2
    assert verified["totals"] == [{
        "category": "volunteers", "label": "Volunteers", "amount": 15.0,
        "unit": "people", "text": "15 people"}]


def test_units_in_one_dimension_add_up(session, giver, make_org):
    _completed(session, giver, make_org(), gives=["grant_writing"],
               quantities={"grant_writing": {"amount": 2, "unit": "days"}})
    _completed(session, giver, make_org(), gives=["grant_writing"],
               quantities={"grant_writing": {"amount": 3, "unit": "hours"}})
    # `other` has no dimension, so it is named as delivered but not totaled.
    _completed(session, giver, make_org(), gives=["translation"],
               quantities={"translation": {"amount": 4, "unit": "other",
                                           "detail": "pamphlets"}})

    verified = app_module.verified_contributions(session, giver)
    assert [t["text"] for t in verified["totals"]] == ["19 hours"]
    assert verified["delivered"] == ["Grant writing", "Translation & interpreting"]


def _public(client, org):
    return client.get(f"/api/organizations/{org.id}/public").get_json()[
        "organization"]


def test_public_only_when_opted_in_and_three_partners_confirm(
        client, session, giver, make_org):
    partners = [make_org() for _ in range(3)]
    for partner in partners[:2]:
        _completed(session, giver, partner)

    giver.stats_public = True
    session.commit()
    assert "verified" not in _public(client, giver)       # two partners

    # A third partnership with a partner already counted is still two.
    _completed(session, giver, partners[0])
    assert "verified" not in _public(client, giver)

    _completed(session, giver, partners[2])
    shown = _public(client, giver)["verified"]
    assert shown["partners"] == 3 and shown["partnerships"] == 4

    giver.stats_public = False
    session.commit()
    assert "verified" not in _public(client, giver)


def test_the_dashboard_always_shows_your_own(client, login, session, giver,
                                             make_org):
    _completed(session, giver, make_org())
    login(giver)
    verified = client.get("/api/dashboard").get_json()["verified"]
    assert verified["partners"] == 1
    assert verified["min_partners"] == app_module.MIN_VERIFIED_PARTNERS


def test_the_setting(client, login, giver, session):
    login(giver)
    assert client.patch("/api/settings",
                        json={"stats_public": "yes"}).status_code == 400
    response = client.patch("/api/settings", json={"stats_public": True})
    assert response.status_code == 200, response.get_json()
    session.refresh(giver)
    assert giver.stats_public is True
