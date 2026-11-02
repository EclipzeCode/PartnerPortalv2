"""Recording a partnership that already happened, and the partner confirming it.

A recorded partnership is a proposal with origin "recorded": pending on the
partner, confirmed with accept, corrected with a counter, denied with a
decline. What is pinned here is where it differs -- past ones complete on
confirmation, the listed-offers rule does not apply, an absent partner gets
an invitation -- and that an unconfirmed one is never public.
"""

from datetime import date, timedelta

import pytest

import app as app_module
from models import Block, Organization, Partnership

PAST = {"starts_on": (date.today() - timedelta(days=90)).isoformat(),
        "ends_on": (date.today() - timedelta(days=30)).isoformat()}
ONGOING = {"starts_on": (date.today() - timedelta(days=30)).isoformat(),
           "ends_on": (date.today() + timedelta(days=30)).isoformat()}


@pytest.fixture
def recorder(make_org):
    return make_org(name="pytest recorder", offers=["volunteers"])


@pytest.fixture
def partner(make_org):
    # Offers nothing at all: a recorded partnership is history, so what they
    # list today does not limit what they gave then.
    return make_org(name="pytest partner")


def _record(client, partner=None, **extra):
    body = {"proposer_gives": ["volunteers"],
            "recipient_gives": ["event_space"],
            "proposer_quantities": {"volunteers": {"amount": 12}},
            "delivered": True, **PAST}
    if partner is not None:
        body["partner_id"] = partner.id
    body.update(extra)
    return client.post("/api/partnerships/recorded", json=body)


def test_recording_with_an_organization_on_the_site(
        client, login, recorder, partner, outbox):
    login(recorder)
    response = _record(client, partner)
    assert response.status_code == 201, response.get_json()
    p = response.get_json()["proposal"]
    assert p["origin"] == "recorded"
    assert p["status"] == "pending"
    assert p["share_token"] is None
    assert [name for name, _, _ in outbox] == ["notify_proposal_created"]

    login(partner)
    seen = client.get(f"/api/proposals/{p['id']}").get_json()["proposal"]
    assert seen["awaiting_you"] is True
    kinds = [n["kind"] for n in
             client.get("/api/notifications").get_json()["notifications"]]
    assert "partnership_recorded" in kinds


def test_confirming_a_past_one_completes_it(
        client, login, recorder, partner, session):
    login(recorder)
    pid = _record(client, partner).get_json()["proposal"]["id"]

    login(partner)
    response = client.post(f"/api/proposals/{pid}/accept",
                           json={"delivered": False})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["proposal"]["status"] == "completed"

    row = session.get(Partnership, pid)
    session.refresh(row)
    assert row.completed_at is not None
    assert row.recipient_delivered is True     # the recorder's answer
    assert row.proposer_delivered is False     # the confirmer's
    assert row.share_token


def test_confirming_an_ongoing_one_accepts_it(
        client, login, recorder, partner):
    login(recorder)
    pid = _record(client, partner, **ONGOING).get_json()["proposal"]["id"]
    login(partner)
    response = client.post(f"/api/proposals/{pid}/accept")
    assert response.get_json()["proposal"]["status"] == "accepted"


def test_editing_skips_the_listed_offers_rule(
        client, login, recorder, partner):
    login(recorder)
    pid = _record(client, partner).get_json()["proposal"]["id"]
    login(partner)
    response = client.patch(f"/api/proposals/{pid}",
                            json={"recipient_gives": ["mentors"]})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["proposal"]["countered"] is True


def test_we_did_not_partner_is_a_decline(
        client, login, recorder, partner, outbox):
    login(recorder)
    pid = _record(client, partner).get_json()["proposal"]["id"]
    login(partner)
    response = client.post(f"/api/proposals/{pid}/decline")
    assert response.get_json()["proposal"]["status"] == "declined"
    assert outbox[-1][0] == "notify_proposal_responded"


def test_an_unconfirmed_one_is_never_public(
        client, login, recorder, partner, make_org):
    login(recorder)
    pid = _record(client, partner).get_json()["proposal"]["id"]

    login(make_org())
    assert client.get(f"/api/proposals/{pid}").status_code == 404
    # Nothing counts it until it is confirmed.
    for org in (recorder, partner):
        login(org)
        counts = client.get("/api/proposals").get_json()["counts"]
        assert counts["completed"] == 0


def test_recording_with_an_invite(client, login, recorder, outbox, session):
    login(recorder)
    response = _record(client, partner_name="pytest Not Here Yet",
                       partner_email="pytest-invitee@example.com")
    assert response.status_code == 201, response.get_json()
    body = response.get_json()
    assert body["emailed_to"] == "pytest-invitee@example.com"
    name, args, kwargs = outbox[-1]
    assert name == "notify_invitation" and kwargs["proposal"] is not None

    # The claim page shows the partnership, and after claiming it is waiting.
    token = body["invite"]["claim_url"].split("token=", 1)[1]
    client.post("/logout")
    invite = client.get(f"/api/invites/{token}").get_json()["invite"]
    assert invite["recorded"]["by"] == "pytest recorder"
    assert invite["recorded"]["they_gave"] == ["Volunteers - 12 people"]

    claimed = client.post(f"/api/invites/{token}/claim", json={
        "email": "pytest-claimer@example.com",
        "password": "Claim-1234!pass"})
    assert claimed.status_code == 201, claimed.get_json()
    pid = body["proposal"]["id"]
    assert client.get(f"/api/proposals/{pid}").get_json()[
        "proposal"]["awaiting_you"] is True


def test_revoking_the_invite_removes_the_recorded_partnership(
        client, login, recorder, session):
    login(recorder)
    body = _record(client, partner_name="pytest Revoked").get_json()
    client.delete(f"/api/invites/{body['invite']['id']}")
    session.expire_all()
    assert session.get(Partnership, body["proposal"]["id"]) is None


def test_it_must_have_started_already(client, login, recorder, partner):
    login(recorder)
    response = _record(client, partner,
                       starts_on=(date.today() + timedelta(days=1)).isoformat(),
                       ends_on=None)
    assert response.status_code == 400
    assert response.get_json()["field"] == "starts_on"


def test_blocks_hold(client, login, recorder, partner, session):
    session.add(Block(blocker_id=partner.id, blocked_id=recorder.id))
    session.commit()
    login(recorder)
    assert _record(client, partner).status_code == 403


def test_verification_is_required(
        client, login, recorder, partner, session, monkeypatch):
    monkeypatch.setattr(app_module, "REQUIRE_EMAIL_VERIFICATION", True)
    recorder.email_verified = False
    session.commit()
    login(recorder)
    response = _record(client, partner)
    assert response.status_code == 403
    assert response.get_json()["needs_verification"] is True


def test_the_outstanding_cap(client, login, recorder, monkeypatch):
    monkeypatch.setattr(app_module, "MAX_PENDING_RECORDED", 1)
    login(recorder)
    assert _record(client, partner_name="pytest First").status_code == 201
    assert _record(client, partner_name="pytest Second").status_code == 429
