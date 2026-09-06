"""What a password change does to sessions already open on the account.

Worth pinning rather than checking by hand: nothing visible breaks if this
regresses. The session simply keeps working, which is what it did before and
looks identical from the outside.
"""

from conftest import PASSWORD


def test_changing_the_password_ends_other_sessions(link_token, client, make_org, login):
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


def test_a_reset_ends_every_session(link_token, client, session, make_org, login):
    """The path somebody locked out of their own account takes."""
    org = make_org(needs=["web_development"], offers=["grant_writing"])
    login(org)
    assert client.get("/api/me").status_code == 200

    assert client.post(
        "/forgot-password", json={"email": org.email}).status_code == 200
    session.refresh(org)

    fresh = client.application.test_client()
    assert fresh.post("/api/reset-password", json={
        "token": link_token('notify_password_reset'),
        "password": "Recovered-Pass-3!",
    }).status_code == 200
    # Whoever completed the reset is signed in on that client.
    assert fresh.get("/api/me").status_code == 200

    # The session that existed before the reset is gone.
    assert client.get("/api/me").status_code == 401


def test_one_account_cannot_be_guessed_at_indefinitely(link_token, client, make_org):
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


# --- What the row holds -----------------------------------------------------
# The three link tokens were stored exactly as they were mailed, so anything
# that could read the table could use them: a backup, a replica, a dump handed
# over for debugging. Not hashes to crack -- working links.

def _reset_row(session, org):
    session.refresh(org)
    return org.password_reset_token_hash


def test_the_reset_token_is_not_what_is_stored(client, make_org, session,
                                               link_token):
    """The property the hashing exists for, asserted directly."""
    org = make_org()
    assert client.post("/forgot-password",
                       json={"email": org.email}).status_code == 200

    mailed = link_token("notify_password_reset")
    stored = _reset_row(session, org)

    assert stored, "nothing was stored for the reset"
    assert mailed, "nothing was mailed"
    # The one assertion that matters: a reader of this table does not have
    # the token.
    assert stored != mailed
    # SHA-256 hex, which is what the String(64) column is sized for.
    assert len(stored) == 64
    assert all(c in "0123456789abcdef" for c in stored)


def test_the_mailed_token_still_works(client, make_org, session, link_token):
    """Hashing is only worth anything if the link in the email still opens.

    The pair to the test above: it would also pass if the token were simply
    broken, and a reset nobody can complete is not a security improvement.
    """
    org = make_org()
    client.post("/forgot-password", json={"email": org.email})
    mailed = link_token("notify_password_reset")

    assert client.post("/api/reset-password", json={
        "token": mailed,
        "password": "Recovered-Pass-9!",
    }).status_code == 200

    # Spent, so the column is cleared rather than left holding a used digest.
    assert _reset_row(session, org) is None


def test_the_stored_digest_is_not_itself_a_token(client, make_org, session,
                                                 link_token):
    """Submitting what the database holds must not reset anything.

    The failure this guards against is a lookup that compares the incoming
    value against the column without hashing it first -- which would leave
    the row's contents usable exactly as before, with the hashing only
    making it look fixed.
    """
    org = make_org()
    client.post("/forgot-password", json={"email": org.email})
    link_token("notify_password_reset")
    stored = _reset_row(session, org)

    # 404, the same answer any unknown token gets -- the digest names no row,
    # because what the lookup hashes is what was submitted.
    assert client.post("/api/reset-password", json={
        "token": stored,
        "password": "Should-Not-Work-9!",
    }).status_code == 404
