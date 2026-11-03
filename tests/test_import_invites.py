"""manage.py import-invites: invited profiles from a spreadsheet.

The command opens its own session, so it is handed one on the test's
connection; and it imports notify_invitation from notifications rather than
through app, so that is patched here rather than by the autouse fixture.
"""

import os

import pytest
from sqlalchemy.orm import Session

import manage
from models import Organization

EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "tools", "invites-example.csv")


@pytest.fixture
def run(connection, monkeypatch, make_org):
    inviter = make_org(name="pytest importer")
    mailed = []
    monkeypatch.setattr(manage, "SessionLocal", lambda: Session(
        bind=connection, join_transaction_mode="create_savepoint",
        expire_on_commit=False))
    monkeypatch.setattr("notifications.notify_invitation",
                        lambda *args: mailed.append(args))

    def _run(path, *extra):
        return manage.main(["import-invites", str(path),
                            "--from", inviter.email, *extra])
    _run.mailed = mailed
    _run.inviter = inviter
    return _run


def _csv(tmp_path, body):
    path = tmp_path / "invites.csv"
    path.write_text(body)
    return path


def _named(session, name):
    return session.query(Organization).filter(
        Organization.name == name).one_or_none()


def test_the_example_imports_prefilled_and_claimable(
        run, session, client, capsys):
    assert run(EXAMPLE) == 0
    riverside = _named(session, "Riverside Community Trust")
    assert riverside.claim_token_hash is not None
    assert riverside.invited_by_id == run.inviter.id
    assert riverside.offers == ["volunteers", "event_space"]
    assert riverside.website_url == "https://riversidetrust.example"
    # Mailed when the row had an address, printed when it did not.
    assert [args[2] for args in run.mailed] == ["hello@riversidetrust.example"]
    printed = capsys.readouterr().out
    token = printed.split("claim.html?token=", 1)[1].split()[0]

    claimed = client.post(f"/api/invites/{token}/claim", json={
        "email": "pytest-printshop@example.com", "password": "Claim-1234!pass"})
    assert claimed.status_code == 201, claimed.get_json()
    me = client.get("/api/me").get_json()["organization"]
    assert me["name"] == "Bridgewater Print Shop"
    assert me["offers"] == ["printing_production"]
    assert me["onboarding_complete"] is False   # they confirm it in onboarding


def test_a_second_run_skips_what_exists(run, session):
    assert run(EXAMPLE) == 0
    assert run(EXAMPLE) == 0
    assert session.query(Organization).filter(
        Organization.name == "Riverside Community Trust").count() == 1


def test_one_bad_row_imports_nothing(run, session, tmp_path, capsys):
    path = _csv(tmp_path, "name,offers\n"
                          "pytest Good Org,Volunteers\n"
                          "pytest Bad Org,Juggling\n")
    assert run(path) == 1
    assert "unknown category 'Juggling'" in capsys.readouterr().err
    assert _named(session, "pytest Good Org") is None


def test_dry_run_writes_nothing(run, session, tmp_path):
    path = _csv(tmp_path, "name,email\npytest Dry Org,dry@example.com\n")
    assert run(path, "--dry-run") == 0
    assert _named(session, "pytest Dry Org") is None
    assert run.mailed == []


def test_unknown_columns_are_refused(run, tmp_path, capsys):
    assert run(_csv(tmp_path, "name,phone\npytest Org,555\n")) == 1
    assert "phone" in capsys.readouterr().err
