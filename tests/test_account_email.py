"""Changing the address an account signs in with.

There was no way to do it, so a typo at signup was unrecoverable without
somebody editing the database by hand.

The new address is held on the row rather than written straight to `email`.
An address is the one field that cannot be checked by looking at it, and
applying a typo immediately locks somebody out of the account the change was
meant to move: the login becomes an address they do not own, and the reset
link goes to an inbox that does not exist.
"""

PASSWORD = "Test1234!verify"
NEW = "pytest-moved@example.com"


def _request(client, **overrides):
    payload = {"password": PASSWORD, "email": NEW}
    payload.update(overrides)
    return client.post("/api/account/email", json=payload)


def test_the_login_does_not_move_until_the_link_is_opened(
        client, login, make_org, session):
    org = make_org()
    original = org.email
    login(org)

    assert _request(client).status_code == 202
    session.refresh(org)
    # Held, not applied.
    assert org.email == original
    assert org.pending_email == NEW
    # The old address still signs in.
    client.post("/logout")
    assert client.post("/login", json={
        "email": original, "password": PASSWORD}).status_code == 200


def test_opening_the_link_moves_it(client, login, make_org, session):
    org = make_org()
    original = org.email
    login(org)
    _request(client)
    session.refresh(org)
    token = org.pending_email_token
    client.post("/logout")

    response = client.post("/api/account/email/confirm", json={"token": token})
    assert response.status_code == 200
    assert response.get_json()["email"] == NEW

    session.refresh(org)
    assert org.email == NEW
    assert org.pending_email is None
    assert org.pending_email_token is None
    # Opening a link sent to the address is what verification asks for, so it
    # arrives verified rather than needing the same proof twice.
    assert org.email_verified is True

    # The new address signs in; the old one no longer does.
    assert client.post("/login", json={
        "email": NEW, "password": PASSWORD}).status_code == 200
    client.post("/logout")
    assert client.post("/login", json={
        "email": original, "password": PASSWORD}).status_code == 401


def test_it_needs_the_current_password(client, login, make_org):
    """A session cookie on a borrowed browser should not be enough to point
    somebody else's account at an attacker's inbox."""
    login(make_org())
    assert _request(client, password="").status_code == 400
    assert _request(client, password="not-the-password").status_code == 403


def test_a_malformed_or_disposable_address_is_refused(client, login, make_org):
    login(make_org())
    for bad in ("not-an-address", "", "someone@mailinator.com"):
        response = _request(client, email=bad)
        assert response.status_code == 400
        assert response.get_json()["field"] == "email"


def test_an_address_already_in_use_is_refused(client, login, make_org):
    other = make_org()
    login(make_org())
    response = _request(client, email=other.email)
    assert response.status_code == 409
    assert response.get_json()["field"] == "email"


def test_moving_to_your_own_address_is_refused(client, login, make_org):
    org = make_org()
    login(org)
    assert _request(client, email=org.email).status_code == 400


def test_a_change_can_be_cancelled(client, login, make_org, session):
    org = make_org()
    login(org)
    _request(client)
    assert client.delete("/api/account/email").status_code == 200
    session.refresh(org)
    assert org.pending_email is None
    assert org.pending_email_token is None


def test_a_token_is_single_use(client, login, make_org, session):
    org = make_org()
    login(org)
    _request(client)
    session.refresh(org)
    token = org.pending_email_token
    assert client.post("/api/account/email/confirm",
                       json={"token": token}).status_code == 200
    assert client.post("/api/account/email/confirm",
                       json={"token": token}).status_code == 404


def test_an_unknown_token_is_refused(client):
    assert client.post("/api/account/email/confirm",
                       json={"token": "nonsense"}).status_code == 404
    assert client.post("/api/account/email/confirm", json={}).status_code == 400


def test_the_address_being_taken_in_the_meantime_is_handled(
        client, login, make_org, session):
    """Request and confirmation are days apart, so the check at request time
    is not enough on its own."""
    org = make_org()
    login(org)
    _request(client)
    session.refresh(org)
    token = org.pending_email_token
    client.post("/logout")

    # Somebody else registers it in between.
    squatter = make_org()
    squatter.email = NEW
    session.commit()

    response = client.post("/api/account/email/confirm", json={"token": token})
    assert response.status_code == 409
    session.refresh(org)
    assert org.email != NEW
    # The dead request is cleared rather than left to fail forever.
    assert org.pending_email is None


def test_both_addresses_are_told(client, login, make_org, outbox):
    """The old one especially: changing the login moves where every future
    reset link goes, so this is the only warning that lands somewhere the
    real account holder still reads."""
    login(make_org())
    _request(client)
    kinds = [s[0] for s in outbox]
    assert "notify_email_change_requested" in kinds
    assert "notify_email_change_notice" in kinds


def test_it_is_rate_limited(client, login, make_org):
    login(make_org())
    for i in range(5):
        _request(client, email=f"pytest-move{i}@example.com")
    assert _request(client, email="pytest-move9@example.com").status_code == 429
