"""Shared fixtures.

Isolation is by transaction rollback rather than a scratch database. The
models use Postgres ARRAY columns, so there is no SQLite fallback to fall
back to, and creating a database on Neon needs privileges this project does
not assume. Instead every test runs inside one transaction on a single
connection, which is rolled back when it finishes -- so a test can commit as
much as it likes and still leave nothing behind.

The part that makes that work for route tests is join_transaction_mode:
without it a handler's db.commit() would land in the real database and
outlive the rollback. "create_savepoint" turns each commit into a savepoint
release inside the outer transaction, which the rollback then discards.

Everything a test creates is named with a `pytest-` prefix, so anything that
does escape -- a crash between commit and rollback -- is identifiable rather
than mixed in with real data.
"""

import os
import sys
import uuid

import pytest
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import db as db_module  # noqa: E402
from models import Organization  # noqa: E402


@pytest.fixture(autouse=True)
def no_outbound_email(monkeypatch):
    """Stop the suite sending real mail, and record what it would have sent.

    RESEND_API_KEY is set in .env and notifications.py reads it fresh on every
    call, so an unpatched test that creates a proposal really does post to
    Resend -- addressed to a pytest-*@example.com account that does not exist.
    Patching the names app.py imported is enough to keep every send inside
    the process.

    Autouse rather than opt-in: forgetting it on one test is all it takes,
    and the failure is invisible from here.
    """
    sent = []

    def _record(kind):
        def _fn(*args, **kwargs):
            sent.append((kind, args, kwargs))
        return _fn

    for name in ("notify_proposal_created", "notify_proposal_responded",
                 "notify_email_verification", "notify_password_changed",
                 "notify_password_reset", "notify_contact_message",
                 "notify_completion_marked", "notify_partnership_completed",
                 "notify_partnership_ended"):
        monkeypatch.setattr(app_module, name, _record(name))
    return sent


@pytest.fixture
def outbox(no_outbound_email):
    """What the app tried to send during this test."""
    return no_outbound_email


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Clear the in-memory rate limiter between tests.

    Every test signs in from the same address, and /login allows twenty
    attempts per IP per fifteen minutes -- so a full run trips the limit
    partway through and later tests fail with 429 for reasons that have
    nothing to do with what they assert. The buckets live in a module-level
    dict rather than the database, so the transaction rollback does not
    touch them.

    Clearing here rather than raising the limits keeps the production
    behaviour under test elsewhere, and makes each test independent of how
    many ran before it.
    """
    # The sweep timer goes with the buckets. Left alone, a test that pushed
    # it into the future would silently disable eviction for everything that
    # ran after it -- the same cross-test dependence this fixture exists to
    # remove.
    app_module._rate_buckets.clear()
    app_module._rate_sweep_after = 0.0
    yield
    app_module._rate_buckets.clear()
    app_module._rate_sweep_after = 0.0


@pytest.fixture
def connection():
    """One connection with an open transaction, rolled back after the test."""
    conn = db_module.engine.connect()
    transaction = conn.begin()
    try:
        yield conn
    finally:
        # Unconditional: a test that raised must still leave nothing behind.
        transaction.rollback()
        conn.close()


def _session_for(conn):
    return Session(
        bind=conn,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )


@pytest.fixture
def session(connection):
    """A session for tests that talk to the models directly."""
    s = _session_for(connection)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client(connection, monkeypatch):
    """A Flask test client whose handlers share the test's transaction.

    get_db is replaced rather than SessionLocal: it is the single place every
    handler reaches for a session, so patching it catches all of them without
    depending on how each one was written.
    """
    monkeypatch.setattr(app_module, "get_db", lambda: _session_for(connection))
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client


PASSWORD = "Test1234!verify"


@pytest.fixture
def make_org(session):
    """Create a complete, matchable organization.

    Written straight to the database rather than through /register, because
    that route is rate limited to five an hour per address -- a limit that
    silently stopped a test organization being created during development and
    made an assertion pass for the wrong reason.
    """
    import bcrypt

    # The cheapest cost bcrypt accepts. Production hashes at its default of
    # 12, which is ~0.2s a call by design -- across the orgs these tests
    # create, and the logins that verify them, that was most of the suite's
    # own runtime. Nothing here asserts anything about hashing strength, and
    # checkpw reads the cost from the hash, so logins verify at this cost
    # too.
    salt = bcrypt.gensalt(rounds=4)

    created = []

    def _make(name=None, *, needs=(), offers=(), focus_areas=(),
              location="Testville, TS", organization_type="NGO",
              onboarding_complete=True, is_demo=False,
              description="Created by the test suite.", **extra):
        suffix = uuid.uuid4().hex[:10]
        org = Organization(
            email=f"pytest-{suffix}@example.com",
            password_hash=bcrypt.hashpw(PASSWORD.encode(), salt).decode(),
            name=name or f"pytest org {suffix}",
            organization_type=organization_type,
            location=location,
            needs=list(needs),
            offers=list(offers),
            focus_areas=list(focus_areas),
            description=description,
            onboarding_complete=onboarding_complete,
            email_verified=True,
            is_demo=is_demo,
            **extra,
        )
        session.add(org)
        session.commit()
        created.append(org)
        return org

    return _make


@pytest.fixture
def login(client):
    """Sign the test client in as `org`, and hand back that same client."""
    def _login(org):
        response = client.post(
            "/login", json={"email": org.email, "password": PASSWORD})
        assert response.status_code == 200, response.get_data(as_text=True)
        return client
    return _login
