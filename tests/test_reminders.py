"""The daily reminder job: what fires, when, and that it fires once.

Dates are moved by passing `now` to reminders.run rather than by backdating
rows, except where a row's own date is the point (a request's expiry, a
partnership's end date). The job reads the whole development database, so
every assertion is about the organizations a test made, never a total.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

import reminders
from models import Block, EmailOutbox, PartnerRequest, Partnership

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def fresh_now():
    """Re-read the clock per test. Rows are stamped by the database's now(),
    so a NOW taken when the module was imported falls further behind them
    with every minute the suite has been running, and the 5-day and 2-day
    thresholds stop being crossed."""
    global NOW
    NOW = datetime.now(timezone.utc)


def _partnership(session, proposer, recipient, **extra):
    p = Partnership(**{
        "proposer_id": proposer.id, "recipient_id": recipient.id,
        "status": Partnership.PENDING,
        "proposer_gives": ["volunteers"], "recipient_gives": ["event_space"],
        "proposer_name": proposer.name, "recipient_name": recipient.name,
        **extra})
    session.add(p)
    session.commit()
    return p


def _outbox_to(session, org):
    return session.query(EmailOutbox).filter(
        EmailOutbox.to_addr == org.email).all()


@pytest.fixture
def pair(make_org):
    return make_org(), make_org()


def test_a_proposal_waiting_five_days_is_reminded_once(session, pair):
    a, b = pair
    _partnership(session, a, b)

    assert b.id not in reminders.run(session, now=NOW + timedelta(days=4))

    sent = reminders.run(session, now=NOW + timedelta(days=5, minutes=1))
    assert len(sent[b.id]) == 1
    assert a.id not in sent       # not waiting on the proposer
    assert len(_outbox_to(session, b)) == 1

    # The next day's run, and a rerun after a crash, add nothing.
    assert b.id not in reminders.run(session, now=NOW + timedelta(days=6))
    assert len(_outbox_to(session, b)) == 1


def test_a_counter_starts_a_new_turn(session, pair):
    a, b = pair
    p = _partnership(session, a, b)
    reminders.run(session, now=NOW + timedelta(days=6))

    p.awaiting_side = Partnership.PROPOSER_SIDE
    p.countered_at = NOW + timedelta(days=7)
    session.commit()
    sent = reminders.run(session, now=NOW + timedelta(days=13))
    assert a.id in sent and b.id not in sent


def test_several_reminders_arrive_as_one_email(session, pair):
    a, b = pair
    _partnership(session, a, b)
    session.add(PartnerRequest(
        organization_id=b.id, kind="need", category="volunteers",
        title="pytest ending soon", expires_on=date.today() + timedelta(days=7)))
    session.commit()

    sent = reminders.run(session, now=NOW + timedelta(days=5, minutes=1))
    assert len(sent[b.id]) == 2
    mail = _outbox_to(session, b)
    assert len(mail) == 1
    assert mail[0].subject == "2 things are waiting on you"
    assert "Extend 30 days" in mail[0].body_text


def test_the_preference_switch_is_respected(session, pair):
    a, b = pair
    b.email_preferences = {"reminders": False}
    session.commit()
    _partnership(session, a, b)
    assert b.id not in reminders.run(session, now=NOW + timedelta(days=6))
    assert _outbox_to(session, b) == []


def test_settled_and_blocked_proposals_are_skipped(session, make_org):
    a, b, c = make_org(), make_org(), make_org()
    _partnership(session, a, b, status=Partnership.DECLINED)
    _partnership(session, a, c)
    session.add(Block(blocker_id=c.id, blocked_id=a.id))
    session.commit()

    sent = reminders.run(session, now=NOW + timedelta(days=6))
    assert b.id not in sent and c.id not in sent


def test_unclaimed_invites_are_skipped(session, make_org):
    a = make_org()
    invited = make_org(claim_token_hash="pytest-" + "0" * 57,
                       onboarding_complete=False)
    _partnership(session, a, invited)
    assert invited.id not in reminders.run(
        session, now=NOW + timedelta(days=6))


def test_past_end_date_reminds_at_three_and_fourteen_days(session, pair):
    a, b = pair
    p = _partnership(session, a, b, status=Partnership.ACCEPTED,
                     ends_on=date.today() - timedelta(days=3),
                     recipient_completed_at=NOW)

    sent = reminders.run(session, now=NOW)
    assert a.id in sent and b.id not in sent    # b already marked it
    assert a.id not in reminders.run(session, now=NOW)

    p.ends_on = date.today() - timedelta(days=14)
    session.commit()
    assert a.id in reminders.run(session, now=NOW)


def test_account_reminders(session, make_org):
    unfinished = make_org(onboarding_complete=False)
    unverified = make_org()
    unverified.email_verified = False
    session.commit()

    sent = reminders.run(session, now=NOW + timedelta(days=2, minutes=1))
    assert unfinished.id in sent and unverified.id not in sent

    sent = reminders.run(session, now=NOW + timedelta(days=3, minutes=1))
    assert unverified.id in sent and unfinished.id not in sent


def test_dry_run_writes_nothing(session, pair):
    a, b = pair
    _partnership(session, a, b)
    lines = []
    sent = reminders.run(session, now=NOW + timedelta(days=6),
                         dry_run=True, out=lines.append)
    assert b.id in sent
    assert any(b.name in line for line in lines)
    assert _outbox_to(session, b) == []
    # Still due for real.
    assert b.id in reminders.run(session, now=NOW + timedelta(days=6))


def test_extending_a_request(client, login, make_org, session):
    org = make_org()
    req = PartnerRequest(organization_id=org.id, kind="need",
                         category="volunteers", title="pytest extend",
                         expires_on=date.today() + timedelta(days=2))
    session.add(req)
    session.commit()

    login(org)
    response = client.post(f"/api/requests/{req.id}/extend")
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["request"]["expires_on"] == (
        date.today() + timedelta(days=32)).isoformat()

    # Capped at the furthest a new request may go.
    for _ in range(6):
        client.post(f"/api/requests/{req.id}/extend")
    session.expire_all()
    assert req.expires_on == date.today() + timedelta(days=180)
    assert client.post(f"/api/requests/{req.id}/extend").status_code == 409

    other = make_org()
    login(other)
    assert client.post(f"/api/requests/{req.id}/extend").status_code == 404


# --- The weekly new-matches email -------------------------------------------

@pytest.fixture
def only_ours(session):
    """Hide every organization that exists before the test, inside its
    transaction, so real recent signups on the shared database cannot match."""
    from models import Organization
    session.query(Organization).update({"hidden_at": NOW})
    session.commit()


def _matches_to(session, org):
    return [m for m in _outbox_to(session, org) if "match" in m.subject]


def test_a_new_match_is_sent_once(session, make_org, only_ours):
    me = make_org(needs=["mentors"], offers=["volunteers"])
    them = make_org(offers=["mentors"])
    make_org(offers=["legal"])                  # no overlap: never listed

    sent = reminders.run_matches(session, now=NOW)
    assert len(sent[me.id]) == 1 and them.name in sent[me.id][0]
    assert _matches_to(session, me)[0].subject == \
        "A new organization matches yours"

    # Not again this week, and not ever for the same organization.
    assert me.id not in reminders.run_matches(session, now=NOW)
    assert me.id not in reminders.run_matches(session, now=NOW + timedelta(days=8))


def test_at_most_five_and_the_rest_next_week(session, make_org, only_ours):
    me = make_org(needs=["mentors"])
    for _ in range(7):
        make_org(offers=["mentors"])

    assert len(reminders.run_matches(session, now=NOW)[me.id]) == 5
    assert me.id not in reminders.run_matches(session, now=NOW + timedelta(days=3))
    assert len(reminders.run_matches(
        session, now=NOW + timedelta(days=7, minutes=1))[me.id]) == 2


def test_matches_respect_the_switch_and_blocks(session, make_org, only_ours):
    me = make_org(needs=["mentors"])
    blocked = make_org(offers=["mentors"])
    session.add(Block(blocker_id=me.id, blocked_id=blocked.id))
    quiet = make_org(needs=["mentors"])
    quiet.email_preferences = {"matches": False}
    session.commit()

    sent = reminders.run_matches(session, now=NOW)
    assert me.id not in sent and quiet.id not in sent
