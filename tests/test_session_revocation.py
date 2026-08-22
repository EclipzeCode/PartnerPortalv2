"""What a password change does to sessions already open on the account.

Worth pinning rather than checking by hand: nothing visible breaks if this
regresses. The session simply keeps working, which is what it did before and
looks identical from the outside.
"""

from conftest import PASSWORD


def test_changing_the_password_ends_other_sessions(client, make_org, login):
    """The other session is the one somebody is trying to lock out."""
    org = make_org(needs=["web_development"], offers=["grant_writing"])

    # Two independent clients on one account, as two browsers would be.
    login(org)
    assert client.get("/api/me").status_code == 200

    other = client.application.test_client()
    assert other.post("/login", json={
        "email": org.email, "password": PASSWORD,
    }).status_code == 200
    assert other.get("/api/me").status_code == 200

    assert client.post("/api/account/password", json={
        "current_password": PASSWORD,
        "new_password": "Replacement-Pass-2!",
    }).status_code == 200

    # The session that did the changing keeps working...
    assert client.get("/api/me").status_code == 200
    # ...and the one it was changed away from does not.
    assert other.get("/api/me").status_code == 401


def test_a_reset_ends_every_session(client, session, make_org, login):
    """The path somebody locked out of their own account takes."""
    org = make_org(needs=["web_development"], offers=["grant_writing"])
    login(org)
    assert client.get("/api/me").status_code == 200

    assert client.post(
        "/forgot-password", json={"email": org.email}).status_code == 200
    session.refresh(org)

    fresh = client.application.test_client()
    assert fresh.post("/api/reset-password", json={
        "token": org.password_reset_token,
        "password": "Recovered-Pass-3!",
    }).status_code == 200
    # Whoever completed the reset is signed in on that client.
    assert fresh.get("/api/me").status_code == 200

    # The session that existed before the reset is gone.
    assert client.get("/api/me").status_code == 401


def test_one_account_cannot_be_guessed_at_indefinitely(client, make_org):
    """The per-IP bucket does not see a distributed attempt on one address:
    every request can come from a different IP and stay under that limit
    while the account itself takes thousands of guesses."""
    org = make_org(needs=["web_development"], offers=["grant_writing"])

    statuses = [
        client.post("/login", json={
            "email": org.email, "password": "Wrong-Pass-9!",
        }).status_code
        for _ in range(11)
    ]
    assert statuses[0] == 401           # an ordinary rejection
    assert statuses[-1] == 429          # the account bucket closed it

    # The right password is refused too while the window is open, which is
    # what makes it a limit rather than a hint about which guess was close.
    assert client.post("/login", json={
        "email": org.email, "password": PASSWORD,
    }).status_code == 429
