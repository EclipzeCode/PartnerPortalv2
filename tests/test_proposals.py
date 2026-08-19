"""The proposal lifecycle.

This is the transaction the whole product exists to produce, and most of what
governs it is a rule about who may do what to a row that already exists.
Those are the rules that break quietly: a permission check that stops firing
still returns 200, and a state machine that stops guarding lets an agreed
partnership be declined out from under both parties.
"""

import pytest


@pytest.fixture
def pair(make_org):
    """A proposer and a recipient with something to exchange either way."""
    proposer = make_org(name="pytest proposer",
                        needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(name="pytest recipient",
                         needs=["grant_writing"], offers=["web_development"])
    return proposer, recipient


def _propose(client, recipient, **overrides):
    payload = {
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
        "timeline": "one_year",
        "message": "Proposed by the test suite.",
    }
    payload.update(overrides)
    return client.post("/api/proposals", json=payload)


# --- Creating -------------------------------------------------------------

def test_a_proposal_needs_something_from_both_sides(client, login, pair):
    """A one-sided proposal is a request for a favour, and the premise here
    is the exchange -- so it is refused rather than stored as a partnership."""
    proposer, recipient = pair
    login(proposer)

    assert _propose(client, recipient, proposer_gives=[]).status_code == 400
    assert _propose(client, recipient, recipient_gives=[]).status_code == 400
    # Unknown slugs are cleaned out, which can empty a side that looked full.
    assert _propose(client, recipient,
                    proposer_gives=["not_a_real_slug"]).status_code == 400
    assert client.get("/api/proposals").get_json()["proposals"] == []


def test_a_proposal_cannot_be_sent_to_yourself_or_an_example(
        client, login, pair, make_org):
    proposer, _ = pair
    example = make_org(needs=["grant_writing"], offers=["web_development"],
                       is_demo=True)
    unfinished = make_org(needs=["grant_writing"], offers=["web_development"],
                          onboarding_complete=False)
    login(proposer)

    assert _propose(client, proposer).status_code == 400
    assert _propose(client, example).status_code == 400
    assert _propose(client, unfinished).status_code == 404


def test_an_unfinished_profile_cannot_propose(client, login, make_org, pair):
    """Nothing to propose with until the profile says what it brings."""
    _, recipient = pair
    incomplete = make_org(onboarding_complete=False)
    login(incomplete)
    assert _propose(client, recipient).status_code == 409


def test_an_invalid_timeline_is_refused(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    assert _propose(client, recipient, timeline="whenever").status_code == 400
    # Absent is fine -- the field is optional.
    assert _propose(client, recipient, timeline="").status_code == 201


def test_only_one_live_proposal_per_direction(client, login, pair):
    """The partial unique index, which is what stops a double-clicked submit
    showing the recipient the same request twice."""
    proposer, recipient = pair
    login(proposer)

    assert _propose(client, recipient).status_code == 201
    assert _propose(client, recipient).status_code == 409
    assert len(client.get("/api/proposals").get_json()["proposals"]) == 1


def test_the_reverse_direction_is_a_separate_proposal(client, login, pair):
    """The index is directional: both organizations may ask each other."""
    proposer, recipient = pair
    login(proposer)
    assert _propose(client, recipient).status_code == 201
    client.post("/logout")

    login(recipient)
    assert _propose(client, proposer).status_code == 201
    assert len(client.get("/api/proposals").get_json()["proposals"]) == 2


def test_the_recipient_is_told(client, login, pair, outbox):
    """Without the email a proposal sits invisible until someone happens to
    open their dashboard."""
    proposer, recipient = pair
    login(proposer)
    _propose(client, recipient)
    assert [kind for kind, _, _ in outbox] == ["notify_proposal_created"]


# --- Who may act ----------------------------------------------------------

def test_only_the_recipient_can_accept_or_decline(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]

    # The proposer is a party to it, so this is 403 -- they may see it, but
    # answering their own proposal is not theirs to do.
    assert client.post(f"/api/proposals/{proposal_id}/accept").status_code == 403
    assert client.post(f"/api/proposals/{proposal_id}/decline").status_code == 403
    client.post("/logout")

    login(recipient)
    assert client.post(f"/api/proposals/{proposal_id}/accept").status_code == 200


def test_only_the_proposer_can_withdraw(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    assert client.post(f"/api/proposals/{proposal_id}/withdraw").status_code == 403
    client.post("/logout")

    login(proposer)
    assert client.post(f"/api/proposals/{proposal_id}/withdraw").status_code == 200


def test_a_stranger_gets_404_not_403(client, login, pair, make_org):
    """403 would confirm the id exists, turning these routes into a way to
    probe for other organizations' proposals."""
    proposer, recipient = pair
    stranger = make_org(needs=["web_development"], offers=["grant_writing"])
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(stranger)
    for path in ("", "/accept", "/decline", "/withdraw"):
        method = client.get if path == "" else client.post
        assert method(f"/api/proposals/{proposal_id}{path}").status_code == 404, path
    assert client.get("/api/proposals").get_json()["proposals"] == []


# --- State machine --------------------------------------------------------

@pytest.mark.parametrize("first,second", [
    ("accept", "accept"), ("accept", "decline"),
    ("decline", "accept"), ("decline", "decline"),
])
def test_a_settled_proposal_cannot_be_answered_again(
        client, login, pair, first, second):
    """Otherwise an agreed partnership could be declined out from under both
    parties, or a decline quietly reopened."""
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    assert client.post(f"/api/proposals/{proposal_id}/{first}").status_code == 200
    assert client.post(f"/api/proposals/{proposal_id}/{second}").status_code == 409


def test_a_settled_proposal_cannot_be_withdrawn(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    client.post(f"/api/proposals/{proposal_id}/accept")
    client.post("/logout")

    login(proposer)
    assert client.post(f"/api/proposals/{proposal_id}/withdraw").status_code == 409


def test_a_closed_proposal_frees_the_direction_again(client, login, pair):
    """The unique index only covers pending rows, so a withdrawn or declined
    proposal does not lock the pair out of ever asking again."""
    proposer, recipient = pair
    login(proposer)
    first_id = _propose(client, recipient).get_json()["proposal"]["id"]
    assert client.post(f"/api/proposals/{first_id}/withdraw").status_code == 200
    assert _propose(client, recipient).status_code == 201


# --- The agreement --------------------------------------------------------

def test_the_share_token_is_minted_only_on_acceptance(client, login, pair):
    """A token on a pending proposal would publish an agreement neither side
    has made."""
    proposer, recipient = pair
    login(proposer)
    created = _propose(client, recipient).get_json()["proposal"]
    assert created["share_token"] is None
    client.post("/logout")

    login(recipient)
    accepted = client.post(
        f"/api/proposals/{created['id']}/accept").get_json()
    assert accepted["proposal"]["share_token"]
    assert accepted["share_url"].endswith(accepted["proposal"]["share_token"])


def test_only_an_accepted_partnership_resolves_publicly(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    # Nothing to fetch while it is pending, and a guessed token finds nothing.
    assert client.get("/api/partnerships/not-a-real-token").status_code == 404

    login(recipient)
    token = client.post(
        f"/api/proposals/{proposal_id}/accept").get_json()["proposal"]["share_token"]
    client.post("/logout")

    # Deliberately readable with no account: that is what makes it shareable
    # with a board or a funder.
    public = client.get(f"/api/partnerships/{token}")
    assert public.status_code == 200
    assert len(public.get_json()["partnership"]["parties"]) == 2


def test_the_public_agreement_carries_no_contact_details(client, login, make_org):
    """Served to anyone holding the link, so it says who agreed to what and
    nothing about how to reach them."""
    proposer = make_org(needs=["web_development"], offers=["grant_writing"],
                        contact_email="proposer@example.com",
                        contact_phone="+1 555 0101")
    recipient = make_org(needs=["grant_writing"], offers=["web_development"],
                         contact_email="recipient@example.com",
                         contact_phone="+1 555 0202")
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    token = client.post(
        f"/api/proposals/{proposal_id}/accept").get_json()["proposal"]["share_token"]
    client.post("/logout")

    body = client.get(f"/api/partnerships/{token}").get_data(as_text=True)
    for secret in ("proposer@example.com", "recipient@example.com",
                   "555 0101", "555 0202", proposer.email, recipient.email):
        assert secret not in body, secret


def test_declining_leaves_nothing_publicly_readable(client, login, pair):
    proposer, recipient = pair
    login(proposer)
    proposal_id = _propose(client, recipient).get_json()["proposal"]["id"]
    client.post("/logout")

    login(recipient)
    declined = client.post(
        f"/api/proposals/{proposal_id}/decline").get_json()["proposal"]
    assert declined["status"] == "declined"
    assert declined["share_token"] is None


def test_both_sides_see_the_proposal_from_their_own_direction(client, login, pair):
    """The same row reads as outgoing to one party and incoming to the other,
    and only the recipient is offered a response."""
    proposer, recipient = pair
    login(proposer)
    _propose(client, recipient)
    mine = client.get("/api/proposals").get_json()
    assert mine["proposals"][0]["direction"] == "outgoing"
    assert mine["proposals"][0]["can_respond"] is False
    assert mine["proposals"][0]["can_withdraw"] is True
    assert mine["counts"]["outgoing_pending"] == 1
    client.post("/logout")

    login(recipient)
    theirs = client.get("/api/proposals").get_json()
    assert theirs["proposals"][0]["direction"] == "incoming"
    assert theirs["proposals"][0]["can_respond"] is True
    assert theirs["proposals"][0]["can_withdraw"] is False
    assert theirs["counts"]["incoming_pending"] == 1
