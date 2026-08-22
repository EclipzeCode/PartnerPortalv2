"""Inviting an organization, and that organization claiming the profile.

The cold-start path: an org whose needs and offers overlap with nobody can
bring the partner it already has in mind. These pin the two properties that
make it safe to expose -- an invited profile is invisible until somebody
claims it, and the link is single-use.
"""

from conftest import PASSWORD


def _invite(client, name="pytest invited org"):
    return client.post("/api/invites", json={"name": name})


def test_an_invited_profile_is_invisible_until_it_is_claimed(
        client, login, make_org):
    """Otherwise this is a way to put a name in the directory that the
    organization named never agreed to."""
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    login(me)

    created = _invite(client, "pytest Riverside Trust")
    assert created.status_code == 201

    # Not in the directory, not in matches, and it has no public profile.
    directory = client.get("/api/organizations").get_data(as_text=True)
    assert "pytest Riverside Trust" not in directory
    assert "pytest Riverside Trust" not in client.get(
        "/api/matches").get_data(as_text=True)

    invite_id = created.get_json()["invite"]["id"]
    assert client.get(f"/api/organizations/{invite_id}/public").status_code == 404


def test_the_link_says_who_is_inviting(client, login, make_org):
    """An invitation from nobody is a signup form that arrived by surprise."""
    me = make_org(name="pytest Coders Over Borders",
                  needs=["web_development"], offers=["grant_writing"])
    login(me)
    token = _invite(client).get_json()["invite"]["claim_url"].split("token=")[1]

    # Unauthenticated: whoever opens this has no account yet.
    client.post("/logout")
    body = client.get(f"/api/invites/{token}").get_json()["invite"]
    assert body["invited_by"] == "pytest Coders Over Borders"
    assert body["name"] == "pytest invited org"


def test_claiming_creates_an_account_and_spends_the_link(
        client, login, make_org):
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    login(me)
    token = _invite(client).get_json()["invite"]["claim_url"].split("token=")[1]
    client.post("/logout")

    claimed = client.post(f"/api/invites/{token}/claim", json={
        "name": "pytest Riverside Trust",
        "email": "pytest-claimer@example.com",
        "password": "Claimed-Pass-7!",
    })
    assert claimed.status_code == 201
    org = claimed.get_json()["organization"]
    assert org["email"] == "pytest-claimer@example.com"
    # Claiming signs you in, so the next step is the profile itself.
    assert client.get("/api/me").status_code == 200
    # ...but the address is not verified by opening a link anyone could have
    # been forwarded.
    assert org["email_verified"] is False

    # Single use.
    assert client.get(f"/api/invites/{token}").status_code == 404
    assert client.post(f"/api/invites/{token}/claim", json={
        "email": "pytest-second@example.com", "password": "Claimed-Pass-7!",
    }).status_code == 404

    # And the account works from the front door afterwards.
    client.post("/logout")
    assert client.post("/login", json={
        "email": "pytest-claimer@example.com", "password": "Claimed-Pass-7!",
    }).status_code == 200


def test_a_claim_will_not_take_an_address_already_registered(
        client, login, make_org):
    existing = make_org(needs=["web_development"], offers=["grant_writing"])
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    login(me)
    token = _invite(client).get_json()["invite"]["claim_url"].split("token=")[1]
    client.post("/logout")

    response = client.post(f"/api/invites/{token}/claim", json={
        "email": existing.email, "password": "Claimed-Pass-7!",
    })
    assert response.status_code == 409
    assert response.get_json()["field"] == "email"
    # The invitation is not spent by a failed attempt.
    assert client.get(f"/api/invites/{token}").status_code == 200


def test_only_the_sender_can_withdraw_an_invitation(client, login, make_org):
    me = make_org(needs=["web_development"], offers=["grant_writing"])
    someone_else = make_org(needs=["web_development"], offers=["grant_writing"])

    login(me)
    invite_id = _invite(client).get_json()["invite"]["id"]
    client.post("/logout")

    login(someone_else)
    # Same answer as an invitation that does not exist, so one org cannot
    # probe for another's.
    assert client.delete(f"/api/invites/{invite_id}").status_code == 404
    client.post("/logout")

    login(me)
    assert client.delete(f"/api/invites/{invite_id}").status_code == 200
    assert client.get("/api/invites").get_json()["invites"] == []


def test_an_unfinished_profile_cannot_invite(client, login, make_org):
    """An invitation says who it is from."""
    me = make_org(needs=["web_development"], offers=["grant_writing"],
                  onboarding_complete=False)
    login(me)
    response = _invite(client)
    assert response.status_code == 409
    assert response.get_json()["needs_onboarding"] is True
