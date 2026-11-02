"""The daily reminder job: nothing on the site stalls silently.

Run once a day by the Render cron job (`python manage.py send-reminders`).
It gathers everything waiting on each organization, writes one email per
organization to the outbox, and leaves sending to the web service's email
workers as with every other message.

Each reminder goes out once. The reminders_sent row and the outbox row are
written in one transaction per organization, and the unique constraint on
reminders_sent turns a second run -- or a run restarted after a crash --
into a no-op for anything already sent. See ReminderSent.

Not run inside the web service: there are two gunicorn processes, and each
would send its own copy.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.dialects.postgresql import insert

from models import (
    Block, EmailOutbox, Organization, PartnerRequest, Partnership,
    ReminderSent,
)
from notifications import reminder_email

PROPOSAL_WAITING = timedelta(days=5)
RECORDED_WAITING = timedelta(days=7)
REQUEST_ENDING = timedelta(days=3)
PAST_END = (timedelta(days=3), timedelta(days=14))
PROFILE_UNFINISHED = timedelta(days=2)
EMAIL_UNVERIFIED = timedelta(days=3)
# Account reminders only reach accounts made this recently, so the first run
# does not write to every half-finished signup the site has ever had.
ACCOUNT_LOOKBACK = timedelta(days=30)


def _claimed(org):
    """A real account: it exists, and it is not an unclaimed invitation."""
    return org is not None and org.claim_token_hash is None and org.password_hash


def _blocked(db, a_id, b_id):
    return db.query(Block.id).filter(or_(
        and_(Block.blocker_id == a_id, Block.blocked_id == b_id),
        and_(Block.blocker_id == b_id, Block.blocked_id == a_id),
    )).first() is not None


def _waiting_threshold(p):
    return (RECORDED_WAITING if p.origin == Partnership.RECORDED
            else PROPOSAL_WAITING)


def due(db, now):
    """Everything due as of `now`: {org_id: (org, [(kind, item, entry)])}."""
    today = now.date()
    found = {}

    def add(org, kind, item, text, actions):
        found.setdefault(org.id, (org, []))[1].append(
            (kind, item, {"text": text, "actions": actions}))

    # Proposals waiting on one side. The clock starts at the turn: a counter
    # hands it over and restarts it, and is part of the item so the new turn
    # can be reminded about too.
    for p in db.query(Partnership).filter(
            Partnership.status == Partnership.PENDING):
        started = p.countered_at or p.created_at
        if now - started < _waiting_threshold(p):
            continue
        waiting_on = (p.recipient if p.awaiting_side == p.RECIPIENT_SIDE
                      else p.proposer)
        other = p.counterpart(waiting_on.id) if waiting_on else None
        if not _claimed(waiting_on) or other is None:
            continue
        if _blocked(db, waiting_on.id, other.id):
            continue
        if p.origin == Partnership.RECORDED:
            text = (f"{other.name} recorded a partnership with you "
                    f"{(now - started).days} days ago. Confirm it, or say "
                    f"you did not partner.")
        else:
            text = (f"{other.name}'s proposal has been waiting on your "
                    f"answer for {(now - started).days} days.")
        add(waiting_on, "proposal", f"{p.id}:{started:%Y%m%d%H%M%S}", text,
            [("Review partnership" if p.origin == Partnership.RECORDED
              else "Review proposal", f"/ppdashboard.html#messages-{p.id}")])

    # Requests about to come off the board. The expiry date is part of the
    # item, so extending one makes the next expiry remindable.
    for r in db.query(PartnerRequest).filter(
            PartnerRequest.status == PartnerRequest.OPEN,
            PartnerRequest.expires_on >= today,
            PartnerRequest.expires_on <= today + REQUEST_ENDING):
        if not _claimed(r.organization):
            continue
        add(r.organization, "request_ending", f"{r.id}:{r.expires_on}",
            f'Your request "{r.title}" comes off the board on '
            f"{r.expires_on:%B} {r.expires_on.day}.",
            [("Extend 30 days", f"/requests.html?id={r.id}"),
             ("Close it", f"/requests.html?id={r.id}")])

    # Agreed partnerships past their end date, to each side that has not
    # marked them complete: once at three days, again at fourteen. A run
    # that missed the first sends only the second.
    for p in db.query(Partnership).filter(
            Partnership.status == Partnership.ACCEPTED,
            Partnership.ends_on <= today - PAST_END[0]):
        stage = 14 if p.ends_on <= today - PAST_END[1] else 3
        for org in (p.proposer, p.recipient):
            if not _claimed(org) or p.completed_at_for(org.id) is not None:
                continue
            other = p.counterpart_party(org.id)
            add(org, "past_end", f"{p.id}:{stage}",
                f"Your partnership with {other['name']} ended on "
                f"{p.ends_on:%B} {p.ends_on.day}. Mark it complete once "
                f"you are done.",
                [("Mark complete", f"/ppdashboard.html#messages-{p.id}")])

    recent = Organization.created_at >= now - ACCOUNT_LOOKBACK
    claimed = and_(Organization.password_hash.isnot(None),
                   Organization.claim_token_hash.is_(None))
    for org in db.query(Organization).filter(
            claimed, recent,
            Organization.onboarding_complete.is_(False),
            Organization.created_at <= now - PROFILE_UNFINISHED):
        add(org, "profile", "1",
            "Your profile is not finished, so nobody can find you or "
            "propose a partnership yet.",
            [("Finish your profile", "/onboarding.html")])
    for org in db.query(Organization).filter(
            claimed, recent,
            Organization.email_verified.is_(False),
            Organization.created_at <= now - EMAIL_UNVERIFIED):
        add(org, "verify", "1",
            "Your email address is not verified yet, so you cannot send "
            "proposals.",
            [("Send a new link", "/settings.html")])

    return found


def run(db, now=None, dry_run=False, out=print):
    """Send what is due. Returns {org_id: [entry text, ...]} for what went."""
    now = now or datetime.now(timezone.utc)
    sent = {}
    for org, items in due(db, now).values():
        if not org.wants_email("reminders"):
            continue

        if dry_run:
            already = {(r.kind, r.item) for r in db.query(ReminderSent).filter(
                ReminderSent.organization_id == org.id)}
            fresh = [e for k, i, e in items if (k, i) not in already]
        else:
            # The insert is the claim: whatever comes back was not sent
            # before, and nothing else is included.
            claimed = db.execute(
                insert(ReminderSent)
                .values([{"organization_id": org.id, "kind": k, "item": i}
                         for k, i, _ in items])
                .on_conflict_do_nothing(constraint="uq_reminders_sent_once")
                .returning(ReminderSent.kind, ReminderSent.item)
            ).all()
            claimed = {(r.kind, r.item) for r in claimed}
            fresh = [e for k, i, e in items if (k, i) in claimed]

        if not fresh:
            db.rollback()
            continue

        to_addr, subject, html, text = reminder_email(org, fresh)
        if dry_run:
            out(f"{org.name} <{to_addr}>: {subject}")
            for e in fresh:
                out(f"    - {e['text']}")
        else:
            db.add(EmailOutbox(
                to_addr=to_addr, subject=subject, html=html, body_text=text,
                optional=True, status=EmailOutbox.QUEUED))
            db.commit()
        sent[org.id] = [e["text"] for e in fresh]
    return sent
