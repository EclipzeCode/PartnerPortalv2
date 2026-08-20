"""How much of the account list /register will hand over.

Signup cannot keep this secret outright. "That email is already registered"
is an oracle, and the only reply that is not one is the reply a new signup
gets -- which means accepting the attempt and mailing the existing address to
say somebody tried. With no channel to that address the person is shown a
success for an account they do not have, cannot sign in, and is told nothing
anywhere, which is worse than the disclosure.

So what these cover is the part that is fixable: how fast the answer is, how
many answers one connection gets, and whether the endpoint says anything
extra when it stops answering.
"""

import time

import bcrypt

import app as app_module
from models import Organization

PASSWORD = "Str0ng!Passphrase42"


def _signup(client, email, name="Probe Org"):
    return client.post("/register", json={
        "name": name, "email": email, "password": PASSWORD,
    })


def _free(prefix="pytest-enum"):
    return f"{prefix}-{time.time_ns()}@example.com"


def test_a_taken_address_is_still_answered_plainly(client, make_org):
    """The disclosure is deliberate. Someone signing up who already has an
    account needs to be told, and there is nowhere else to tell them."""
    existing = make_org()
    response = _signup(client, existing.email)
    assert response.status_code == 409
    assert "already registered" in response.get_json()["error"]


def test_the_answer_does_not_arrive_faster_for_a_taken_address(
        client, make_org, monkeypatch):
    """The oracle that survives changing the message.

    Returning early on a taken address skipped bcrypt and the insert, which
    made the refusal measurably quicker than a signup -- about 490ms of
    difference, readable off a stopwatch, whatever the two replies said.
    Both answers now pay for one hash and one write.
    """
    calls = {"hash": 0, "commit": 0}

    real_hash = bcrypt.hashpw
    monkeypatch.setattr(
        app_module.bcrypt, "hashpw",
        lambda *a, **k: (calls.__setitem__("hash", calls["hash"] + 1),
                         real_hash(*a, **k))[1])

    # Created before counting: make_org hashes a password of its own, and
    # app_module.bcrypt is the same module object it uses.
    existing = make_org()

    app_module._rate_buckets.clear()
    calls["hash"] = 0
    _signup(client, existing.email)
    taken_hashes = calls["hash"]

    app_module._rate_buckets.clear()
    calls["hash"] = 0
    _signup(client, _free())
    free_hashes = calls["hash"]

    # The expensive half of the work happens either way.
    assert taken_hashes == 1
    assert free_hashes == 1


def test_a_taken_address_costs_a_write_like_a_free_one(client, make_org, session):
    """No "is it taken" query first: the insert is attempted and the unique
    index decides. Checking first meant only free addresses paid for a round
    trip to the database, which is its own clock."""
    existing = make_org()
    before = session.query(Organization).count()
    assert _signup(client, existing.email).status_code == 409
    # Refused, and nothing left behind by the attempt.
    assert session.query(Organization).count() == before


def test_one_connection_is_told_only_so_many_times(client, make_org):
    existing_a = make_org()
    existing_b = make_org()
    existing_c = make_org()

    assert _signup(client, existing_a.email).status_code == 409
    assert _signup(client, existing_b.email).status_code == 409
    # Budget spent.
    assert _signup(client, existing_c.email).status_code == 429


def test_spending_the_budget_closes_the_endpoint_for_every_address(
        client, make_org):
    """The part that matters. Refusing only taken addresses after the budget
    would be the same oracle with a new status code -- a 429 for taken and a
    201 for free still answers the question."""
    for _ in range(app_module.MAX_EXISTENCE_DISCLOSURES):
        assert _signup(client, make_org().email).status_code == 409

    taken = _signup(client, make_org().email)
    free = _signup(client, _free())
    assert taken.status_code == 429
    assert free.status_code == 429
    assert taken.get_json()["error"] == free.get_json()["error"]


def test_ordinary_signups_do_not_spend_the_budget(client):
    """Only being told costs. Somebody registering three new organizations
    from one office should not be locked out by it."""
    for _ in range(3):
        assert _signup(client, _free()).status_code == 201
    # Still able to be told once.
    assert not app_module.rate_limit_reached(
        "register_exists", "127.0.0.1",
        app_module.MAX_EXISTENCE_DISCLOSURES,
        app_module.EXISTENCE_DISCLOSURE_WINDOW)


def test_a_duplicate_arrives_as_a_409_not_a_500(client, make_org):
    """The duplicate is now caught by the unique index rather than by a
    lookup beforehand, so this is the path that used to be a server error
    when two signups for one address raced each other."""
    existing = make_org()
    response = _signup(client, existing.email)
    assert response.status_code == 409
    assert response.headers["Content-Type"].startswith("application/json")


# --- The same disclosure, from the signed-in side ---------------------------

def test_the_email_change_route_keeps_the_same_budget(client, login, make_org):
    others = [make_org() for _ in range(3)]
    me = make_org()
    login(me)

    assert client.post("/api/account/email", json={
        "password": "Test1234!verify", "email": others[0].email,
    }).status_code == 409
    assert client.post("/api/account/email", json={
        "password": "Test1234!verify", "email": others[1].email,
    }).status_code == 409
    # Spent, and the route stops answering rather than answering differently.
    assert client.post("/api/account/email", json={
        "password": "Test1234!verify", "email": others[2].email,
    }).status_code == 429
    assert client.post("/api/account/email", json={
        "password": "Test1234!verify", "email": _free(),
    }).status_code == 429


def test_login_and_forgot_password_remain_silent(client, make_org):
    """The two routes that already got this right, pinned so they stay that
    way -- they are the reason signup stands out."""
    existing = make_org()

    known = client.post("/login", json={
        "email": existing.email, "password": "wrong-password"})
    unknown = client.post("/login", json={
        "email": _free(), "password": "wrong-password"})
    assert known.status_code == unknown.status_code == 401
    assert known.get_json() == unknown.get_json()

    known = client.post("/forgot-password", json={"email": existing.email})
    unknown = client.post("/forgot-password", json={"email": _free()})
    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json()
