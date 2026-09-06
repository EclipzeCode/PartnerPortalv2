"""Two requests arriving at once.

Every other file here runs inside one transaction on one connection, rolled
back when the test ends. That is the right isolation for almost everything
and exactly the wrong isolation for this: a row lock cannot serialize two
callers when there is only one connection to serialize, so a test written
against the shared fixtures would pass whether or not the lock existed.

So these run against the real database on their own connections, commit for
real, and delete what they made afterward. That is slower and less tidy than
the rest of the suite, and it is the only arrangement in which the thing
being asserted is actually true or false.

What is being asserted is the postcondition, not the interleaving. Two
threads released from a barrier are *likely* to overlap, not certain to, so
a passing run does not prove the two requests collided -- but the assertions
are ones that cannot hold if the locking is removed, and the rounds are
repeated so that a regression has several chances to show itself. A test
that is merely probabilistic at catching a regression is still the only
thing standing between this and the bug coming back silently.
"""

import threading
import uuid

import pytest
import sqlalchemy as sa

import app as app_module
import db as db_module
from models import Organization, Partnership

from conftest import PASSWORD, CsrfClient

ROUNDS = 3


@pytest.fixture
def real_client():
    """A client whose handlers get real, independent sessions.

    The shared `client` fixture points get_db at the test's one connection,
    which is what makes rollback isolation work everywhere else. Here each
    request must be able to hold its own transaction -- and block on somebody
    else's -- so get_db is left alone and every call gets a fresh session out
    of the pool.
    """
    app_module.app.config.update(TESTING=True)
    app_module.app.test_client_class = CsrfClient
    return lambda: app_module.app.test_client()


def _sql(statement, **params):
    db = db_module.SessionLocal()
    try:
        result = db.execute(sa.text(statement), params)
        rows = result.fetchall() if result.returns_rows else None
        db.commit()
        return rows
    finally:
        db.close()


@pytest.fixture
def committed():
    """Two organizations that really exist, and a factory for partnerships.

    Named with the same `pytest-` prefix as everything else, so anything a
    crash strands is identifiable rather than mixed in with real data.
    """
    import bcrypt

    salt = bcrypt.gensalt(rounds=4)
    ids = []
    db = db_module.SessionLocal()
    try:
        pair = []
        for role in ("proposer", "recipient"):
            suffix = uuid.uuid4().hex[:10]
            org = Organization(
                email=f"pytest-race-{suffix}@example.com",
                password_hash=bcrypt.hashpw(PASSWORD.encode(), salt).decode(),
                name=f"pytest race {role} {suffix}",
                organization_type="NGO",
                location="Testville, TS",
                needs=["web_development"] if role == "proposer" else ["grant_writing"],
                offers=["grant_writing"] if role == "proposer" else ["web_development"],
                focus_areas=[],
                description="Created by the concurrency tests.",
                onboarding_complete=True,
                email_verified=True,
            )
            db.add(org)
            pair.append(org)
        db.commit()
        proposer, recipient = pair
        ids = [proposer.id, recipient.id]
        emails = (proposer.email, recipient.email)

        def make_partnership(status=Partnership.ACCEPTED):
            # The party snapshot is NOT NULL and is normally written by
            # snapshot_parties() at creation. Set from the live rows here,
            # which is the same thing that method does -- it reads the
            # relationships, and this row is built from ids alone.
            row = Partnership(
                proposer_id=proposer.id,
                recipient_id=recipient.id,
                proposer_name=proposer.name,
                proposer_type=proposer.organization_type,
                proposer_location=proposer.location,
                recipient_name=recipient.name,
                recipient_type=recipient.organization_type,
                recipient_location=recipient.location,
                proposer_gives=["grant_writing"],
                recipient_gives=["web_development"],
                status=status,
            )
            fresh = db_module.SessionLocal()
            try:
                fresh.add(row)
                fresh.commit()
                return row.id
            finally:
                fresh.close()

        yield emails, make_partnership
    finally:
        db.close()
        if ids:
            # Partnerships first: the organization FKs are ON DELETE SET NULL,
            # so removing the orgs would orphan the rows rather than take them
            # with it. Messages and notifications hang off the partnership
            # with CASCADE and go on their own.
            _sql(
                "DELETE FROM partnerships "
                "WHERE proposer_id = ANY(:ids) OR recipient_id = ANY(:ids)",
                ids=ids,
            )
            _sql("DELETE FROM email_outbox WHERE to_addr LIKE 'pytest-race-%'")
            _sql("DELETE FROM organizations WHERE id = ANY(:ids)", ids=ids)


def _sign_in(make_client, email):
    client = make_client()
    response = client.post("/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.get_data(as_text=True)
    return client


def _race(make_client, emails, path, bodies=(None, None)):
    """Both organizations POST `path` as simultaneously as two threads manage.

    Returns the two responses' status codes. Each thread signs in first and
    waits on the barrier, so the sign-in round trips are not part of what is
    being raced -- only the request under test is.
    """
    barrier = threading.Barrier(2)
    results = [None, None]

    def run(index):
        try:
            client = _sign_in(make_client, emails[index])
            barrier.wait(timeout=30)
            response = client.post(path, json=bodies[index] or {})
            results[index] = response.status_code
        except Exception as error:            # noqa: BLE001 - reported below
            results[index] = error

    threads = [threading.Thread(target=run, args=(i,)) for i in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    for outcome in results:
        assert not isinstance(outcome, Exception), outcome
    return results


def _status_of(partnership_id):
    rows = _sql(
        "SELECT status, completed_at, proposer_completed_at, "
        "recipient_completed_at FROM partnerships WHERE id = :id",
        id=partnership_id,
    )
    return rows[0]


# --- Completing -------------------------------------------------------------

def test_two_completes_at_once_close_the_partnership(real_client, committed):
    """The bug this locking exists for, and the worst one it prevented.

    Unlocked, both sides read the other's timestamp as absent, both wrote
    their own, and both computed "are we both done" from the copy they had
    read before the other committed -- so neither closed it. The partnership
    then sat in `accepted` with both timestamps set, and the guard against
    marking twice refused both organizations forever. An agreement both
    parties had finished, permanently unclosable.
    """
    emails, make_partnership = committed

    for _ in range(ROUNDS):
        pid = make_partnership()
        codes = _race(make_client=real_client, emails=emails,
                      path=f"/api/proposals/{pid}/complete")

        # Both are legitimate: the first closes its own side, the second
        # closes the partnership. Neither is refused, because marking your
        # own side complete is a thing each party may do exactly once.
        assert codes == [200, 200], codes

        status, completed_at, proposer_at, recipient_at = _status_of(pid)
        assert proposer_at is not None and recipient_at is not None
        assert status == Partnership.COMPLETED, (
            f"both sides marked complete and the partnership is still "
            f"{status!r} -- the row lock in _load_party_proposal is what "
            f"stops this"
        )
        assert completed_at is not None


def test_the_repair_closes_a_partnership_wedged_by_the_old_race(client, login,
                                                                make_org,
                                                                session):
    """Rows the unlocked version already stranded, on the shared fixtures.

    This one needs no concurrency at all -- the corrupt state is written
    directly, which is the only way to produce it now that the lock stops it
    arising. Without the repair both organizations get "you have already
    marked this" forever and the agreement can never close.
    """
    from datetime import datetime, timedelta, timezone

    proposer = make_org(name="pytest wedged proposer",
                        needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(name="pytest wedged recipient",
                         needs=["grant_writing"], offers=["web_development"])

    earlier = datetime.now(timezone.utc) - timedelta(hours=2)
    later = datetime.now(timezone.utc) - timedelta(hours=1)
    wedged = Partnership(
        proposer_id=proposer.id,
        recipient_id=recipient.id,
        proposer_name=proposer.name,
        proposer_type=proposer.organization_type,
        proposer_location=proposer.location,
        recipient_name=recipient.name,
        recipient_type=recipient.organization_type,
        recipient_location=recipient.location,
        proposer_gives=["grant_writing"],
        recipient_gives=["web_development"],
        status=Partnership.ACCEPTED,
        proposer_completed_at=earlier,
        recipient_completed_at=later,
    )
    session.add(wedged)
    session.commit()

    login(proposer)
    response = client.post(f"/api/proposals/{wedged.id}/complete")
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["awaiting_other_side"] is False

    session.refresh(wedged)
    assert wedged.status == Partnership.COMPLETED
    # The later of the two timestamps, not "now": that is the moment the
    # second side actually declared it finished, and it was already recorded.
    assert wedged.completed_at is not None
    assert abs((wedged.completed_at - later).total_seconds()) < 1


# --- Answering --------------------------------------------------------------

def test_accept_and_decline_at_once_leave_one_answer(real_client, committed):
    """Only the recipient may answer, so this races the two sides' verbs.

    The proposer withdraws while the recipient accepts. Both used to pass
    their own `status == pending` guard and both used to write, so the
    proposal ended up with one side's answer and the other side's
    notification -- each party told a different thing had happened.
    """
    emails, make_partnership = committed

    for _ in range(ROUNDS):
        pid = make_partnership(status=Partnership.PENDING)

        barrier = threading.Barrier(2)
        results = {}

        def answer(index, verb):
            client = _sign_in(real_client, emails[index])
            barrier.wait(timeout=30)
            results[verb] = client.post(
                f"/api/proposals/{pid}/{verb}", json={}).status_code

        threads = [
            threading.Thread(target=answer, args=(0, "withdraw")),
            threading.Thread(target=answer, args=(1, "accept")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        # Exactly one wins; the loser is refused with a conflict rather than
        # overwriting the answer that landed first.
        codes = sorted(results.values())
        assert codes == [200, 409], results

        status = _status_of(pid)[0]
        assert status in (Partnership.ACCEPTED, Partnership.WITHDRAWN), status


def test_two_accepts_at_once_mint_one_share_token(real_client, committed):
    """A double-click used to mint the token twice.

    The second overwrote the first, so a link copied out of the first
    response 404'd -- and both accepts mailed the proposer.
    """
    emails, make_partnership = committed

    for _ in range(ROUNDS):
        pid = make_partnership(status=Partnership.PENDING)

        barrier = threading.Barrier(2)
        codes = []
        lock = threading.Lock()

        def accept():
            # Both threads are the recipient: this is one person's two
            # clicks, not two organizations.
            client = _sign_in(real_client, emails[1])
            barrier.wait(timeout=30)
            response = client.post(f"/api/proposals/{pid}/accept", json={})
            with lock:
                codes.append(response.status_code)

        threads = [threading.Thread(target=accept) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert sorted(codes) == [200, 409], codes
        assert _status_of(pid)[0] == Partnership.ACCEPTED
