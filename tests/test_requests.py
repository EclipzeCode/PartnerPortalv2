"""The requests board: posting, the limits on it, and answering a request.

Answering is an ordinary proposal carrying request_id, so most of what is
pinned here is the seam between the two: who a response may go to, what it
has to include, and the one place the board is allowed to add to a profile.
"""

from datetime import date, timedelta

import pytest

from models import Organization, PartnerRequest


@pytest.fixture
def poster(make_org):
    return make_org(name="pytest poster",
                    needs=["event_space"], offers=["volunteers"])


@pytest.fixture
def helper(make_org):
    return make_org(name="pytest helper",
                    needs=["volunteers"], offers=["event_space"])


def _post(client, **extra):
    body = {"kind": "need", "category": "event_space",
            "title": "Hall for a Saturday fundraiser"}
    body.update(extra)
    return client.post("/api/requests", json=body)


def test_a_request_is_posted_and_shows_on_the_public_board(
        client, login, poster):
    login(poster)
    response = _post(client, quantity={"amount": 2000, "unit": "sqft"})
    assert response.status_code == 201, response.get_json()
    req = response.get_json()["request"]
    assert req["status"] == "open"
    assert req["quantity_label"] == "2,000 sq ft"
    # No date given: up for the default window.
    assert req["expires_on"] == (date.today() + timedelta(days=30)).isoformat()

    client.post("/logout")
    board = client.get("/api/requests").get_json()
    assert req["id"] in [r["id"] for r in board["requests"]]
    assert board["signed_in"] is False


def test_posting_adds_the_category_to_the_profile(
        client, login, poster, session):
    """A have for something the profile does not offer could never go into
    a proposal, so posting it lists it."""
    login(poster)
    response = _post(client, kind="have", category="mentors",
                     title="Two mentors free this spring")
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["added_to_profile"] == "offers"
    session.expire_all()
    assert "mentors" in session.get(Organization, poster.id).offers


def test_bad_input_is_refused_by_field(client, login, poster):
    login(poster)
    assert _post(client, kind="maybe").get_json()["field"] == "kind"
    assert _post(client, category="nonsense").get_json()["field"] == "category"
    assert _post(client, title="  ").get_json()["field"] == "title"
    past = (date.today() - timedelta(days=1)).isoformat()
    assert _post(client, needed_by=past).get_json()["field"] == "needed_by"
    far = (date.today() + timedelta(days=400)).isoformat()
    assert _post(client, needed_by=far).get_json()["field"] == "needed_by"


def test_open_requests_are_capped(client, login, poster):
    login(poster)
    for n in range(5):
        assert _post(client, title=f"Request {n}").status_code == 201
    assert _post(client, title="One too many").status_code == 409


def test_an_expired_request_leaves_the_board(client, login, poster, session):
    login(poster)
    rid = _post(client).get_json()["request"]["id"]
    req = session.get(PartnerRequest, rid)
    req.expires_on = date.today() - timedelta(days=1)
    session.commit()
    ids = [r["id"] for r in client.get("/api/requests").get_json()["requests"]]
    assert rid not in ids
    mine = client.get("/api/requests/mine").get_json()["requests"]
    assert [r["status"] for r in mine if r["id"] == rid] == ["expired"]


def test_only_the_poster_can_close_it(client, login, poster, helper):
    login(poster)
    rid = _post(client).get_json()["request"]["id"]
    login(helper)
    assert client.post(f"/api/requests/{rid}/close").status_code == 404
    login(poster)
    response = client.post(f"/api/requests/{rid}/close",
                           json={"status": "filled"})
    assert response.get_json()["request"]["status"] == "filled"
    ids = [r["id"] for r in client.get("/api/requests").get_json()["requests"]]
    assert rid not in ids


def test_answering_a_need_is_a_proposal_linked_to_it(
        client, login, poster, helper):
    login(poster)
    rid = _post(client).get_json()["request"]["id"]

    login(helper)
    board = client.get("/api/requests").get_json()["requests"]
    assert [r["fits"] for r in board if r["id"] == rid] == [True]
    response = client.post("/api/proposals", json={
        "recipient_id": poster.id,
        "proposer_gives": ["event_space"],
        "recipient_gives": ["volunteers"],
        "request_id": rid,
    })
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["proposal"]["request_id"] == rid

    # The poster sees who answered; everyone else sees only the count.
    login(poster)
    data = client.get(f"/api/requests/{rid}").get_json()["request"]
    assert data["response_count"] == 1
    assert data["responses"][0]["organization"] == "pytest helper"
    login(helper)
    assert "responses" not in client.get(
        f"/api/requests/{rid}").get_json()["request"]


def test_a_response_must_include_what_was_asked_for(
        client, login, poster, make_org):
    login(poster)
    rid = _post(client).get_json()["request"]["id"]
    other = make_org(needs=["volunteers"], offers=["event_space", "mentors"])
    login(other)
    response = client.post("/api/proposals", json={
        "recipient_id": poster.id,
        "proposer_gives": ["mentors"],
        "recipient_gives": ["volunteers"],
        "request_id": rid,
    })
    assert response.status_code == 400
    assert response.get_json()["field"] == "proposer_gives"


def test_answering_adds_the_needed_category_to_the_responder(
        client, login, poster, make_org, session):
    """The one click the board promises: a responder who does not list the
    category yet can still answer, and their profile learns it."""
    login(poster)
    rid = _post(client).get_json()["request"]["id"]
    newcomer = make_org(needs=["volunteers"], offers=["mentors"])
    login(newcomer)
    response = client.post("/api/proposals", json={
        "recipient_id": poster.id,
        "proposer_gives": ["event_space"],
        "recipient_gives": ["volunteers"],
        "request_id": rid,
    })
    assert response.status_code == 201, response.get_json()
    session.expire_all()
    assert "event_space" in session.get(Organization, newcomer.id).offers


def test_the_unlisted_rule_still_holds_without_a_request(
        client, login, poster, make_org):
    newcomer = make_org(needs=["volunteers"], offers=["mentors"])
    login(newcomer)
    response = client.post("/api/proposals", json={
        "recipient_id": poster.id,
        "proposer_gives": ["event_space"],
        "recipient_gives": ["volunteers"],
    })
    assert response.status_code == 400


def test_a_closed_request_cannot_be_answered(client, login, poster, helper):
    login(poster)
    rid = _post(client).get_json()["request"]["id"]
    client.post(f"/api/requests/{rid}/close")
    login(helper)
    response = client.post("/api/proposals", json={
        "recipient_id": poster.id,
        "proposer_gives": ["event_space"],
        "recipient_gives": ["volunteers"],
        "request_id": rid,
    })
    assert response.status_code == 409


def test_blocks_hide_requests_both_ways(client, login, poster, helper):
    login(poster)
    rid = _post(client).get_json()["request"]["id"]
    login(helper)
    client.post("/api/blocks", json={"organization_id": poster.id})
    ids = [r["id"] for r in client.get("/api/requests").get_json()["requests"]]
    assert rid not in ids
    assert client.get(f"/api/requests/{rid}").status_code == 404


def test_a_matching_request_reaches_the_bell(client, login, poster, helper):
    login(poster)
    rid = _post(client).get_json()["request"]["id"]
    login(helper)
    items = client.get("/api/notifications").get_json()["notifications"]
    match = [i for i in items if i["kind"] == "request_match"]
    assert [i["request_id"] for i in match] == [rid]
    assert match[0]["href"] == f"requests.html?id={rid}"

    # Dismissable, since it is news rather than work.
    key = match[0]["key"]
    assert client.post("/api/notifications/dismiss",
                       json={"key": key}).status_code == 200
    items = client.get("/api/notifications").get_json()["notifications"]
    assert not [i for i in items if i["kind"] == "request_match"]


# --- The requests email --------------------------------------------------------

def _emailed(outbox):
    """{organization id: [request ids]} for each requests email sent."""
    return {args[0].id: [r.id for r in args[1]]
            for kind, args, _ in outbox if kind == "notify_matching_requests"}


def test_a_new_request_emails_the_organizations_it_fits(
        client, login, poster, helper, make_org, outbox):
    bystander = make_org(needs=["volunteers"], offers=["mentors"])
    login(poster)
    rid = _post(client).get_json()["request"]["id"]
    sent = _emailed(outbox)
    # The helper offers event space; the bystander does not, and the
    # poster never hears about their own request.
    assert sent.get(helper.id) == [rid]
    assert bystander.id not in sent
    assert poster.id not in sent


def test_at_most_one_email_a_day_and_the_next_catches_up(
        client, login, poster, helper, session, outbox):
    login(poster)
    first = _post(client, title="First").get_json()["request"]["id"]
    second = _post(client, title="Second").get_json()["request"]["id"]
    # One email to the helper, for the first; the second waits.
    to_helper = [args for kind, args, _ in outbox
                 if kind == "notify_matching_requests" and args[0].id == helper.id]
    assert [[r.id for r in args[1]] for args in to_helper] == [[first]]

    # A day later, the next post's email lists everything since the last one.
    org = session.get(Organization, helper.id)
    from datetime import datetime, timezone
    org.requests_emailed_at = datetime.now(timezone.utc) - timedelta(days=2)
    session.commit()
    outbox.clear()
    third = _post(client, title="Third").get_json()["request"]["id"]
    assert set(_emailed(outbox)[helper.id]) == {first, second, third}


def test_the_requests_email_can_be_switched_off(
        client, login, poster, helper, session, outbox):
    org = session.get(Organization, helper.id)
    org.email_preferences = {"requests": False}
    session.commit()
    login(poster)
    _post(client)
    assert helper.id not in _emailed(outbox)


def test_blocked_organizations_are_not_emailed(
        client, login, poster, helper, outbox):
    login(helper)
    client.post("/api/blocks", json={"organization_id": poster.id})
    login(poster)
    _post(client)
    assert helper.id not in _emailed(outbox)


# --- Sorting ---------------------------------------------------------------------

def test_ending_soon_sorts_by_date(client, login, poster):
    login(poster)
    late = _post(client, title="Late",
                 needed_by=(date.today() + timedelta(days=60)).isoformat())
    soon = _post(client, title="Soon",
                 needed_by=(date.today() + timedelta(days=3)).isoformat())
    ids = [r["id"] for r in client.get(
        f"/api/requests?org={poster.id}&sort=soon").get_json()["requests"]]
    assert ids.index(soon.get_json()["request"]["id"]) < ids.index(
        late.get_json()["request"]["id"])
