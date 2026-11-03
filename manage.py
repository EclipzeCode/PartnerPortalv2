"""Operator commands. Run on a machine that already has the database.

    python manage.py create-admin  <email> [--name "Ada Lovelace"]
    python manage.py list-admins
    python manage.py reset-admin-password <email>
    python manage.py remove-admin <email> [--force]
    python manage.py send-reminders [--dry-run]
    python manage.py import-invites <file.csv> --from <your org's email> [--dry-run]

There is no admin signup route and there will not be one. That is not an
omission to be filled in later: an admin is somebody who can act on other
people's accounts, and the set of people who should be able to create one is
exactly the set who could edit the table by hand anyway -- which is the set
holding DATABASE_URL, which is the set who can run this file. A web form
would widen that to "whoever can reach the URL", and every widening after
that is a decision somebody has to remember to get right.

Passwords are never taken as an argument. They would be in the shell history,
in the process list while the command ran, and in the terminal scrollback of
whoever ran it; getpass asks for it on the tty and echoes nothing.
"""

import argparse
import getpass
import sys

import bcrypt

from db import SessionLocal
from models import Admin, Organization

# The same rules an organization's password is held to, imported rather than
# restated. An admin password must not be allowed to be weaker than the ones
# guarding the accounts it can act on, and two copies of that rule is one copy
# too many for it to stay true.
from app import MAX_PASSWORD_BYTES, is_valid_email, password_problem


def _read_password(email, name):
    """Ask twice, on the tty, echoing nothing."""
    while True:
        first = getpass.getpass("Password: ")
        if not first:
            print("  Nothing entered.", file=sys.stderr)
            continue
        problem = password_problem(first, email=email, name=name)
        if problem:
            print(f"  {problem}", file=sys.stderr)
            continue
        if len(first.encode("utf-8")) > MAX_PASSWORD_BYTES:
            print("  Too long (72 bytes maximum).", file=sys.stderr)
            continue
        if first != getpass.getpass("Again: "):
            print("  They did not match.", file=sys.stderr)
            continue
        return first


def create_admin(email, name):
    email = (email or "").strip().lower()
    if not is_valid_email(email):
        print(f"{email!r} is not an email address.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        if db.query(Admin).filter(Admin.email == email).one_or_none():
            print(f"{email} is already an admin. Use reset-admin-password "
                  f"to change it.", file=sys.stderr)
            return 1

        name = (name or "").strip() or email.split("@", 1)[0]
        print(f"Creating admin {name} <{email}>.")
        password = _read_password(email, name)

        db.add(Admin(
            email=email,
            name=name,
            password_hash=bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        ))
        db.commit()
        print("Created. Sign in at /admin.html")
        return 0
    finally:
        db.close()


def list_admins():
    db = SessionLocal()
    try:
        rows = db.query(Admin).order_by(Admin.email).all()
        if not rows:
            print("No admins. Create one with:\n"
                  "  python manage.py create-admin you@example.com")
            return 0
        width = max(len(a.email) for a in rows)
        for a in rows:
            seen = (a.last_seen_at.strftime("%Y-%m-%d %H:%M")
                    if a.last_seen_at else "never signed in")
            print(f"  {a.email:<{width}}  {a.name:<24}  {seen}")
        return 0
    finally:
        db.close()


def reset_admin_password(email):
    email = (email or "").strip().lower()
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.email == email).one_or_none()
        if admin is None:
            print(f"No admin with address {email}.", file=sys.stderr)
            return 1

        password = _read_password(admin.email, admin.name)
        admin.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        # Every session opened under the old password ends here. This is the
        # command somebody runs because they think a password is compromised,
        # so leaving the sessions it opened alive would answer the wrong half
        # of the problem.
        admin.session_epoch = (admin.session_epoch or 0) + 1
        db.commit()
        print(f"Password changed. Every admin session for {email} has ended.")
        return 0
    finally:
        db.close()


def remove_admin(email, force=False):
    email = (email or "").strip().lower()
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.email == email).one_or_none()
        if admin is None:
            print(f"No admin with address {email}.", file=sys.stderr)
            return 1
        if db.query(Admin).count() == 1 and not force:
            # Worth stopping on, and worth being accurate about: this is not
            # a lockout. Admins are made here rather than in the panel, so
            # create-admin can always mint another -- which is exactly why
            # --force exists rather than this being a wall.
            print("That is the only admin. Nobody will be able to sign in to "
                  "the panel until you run create-admin again.\n"
                  "  Re-run with --force if that is what you meant.",
                  file=sys.stderr)
            return 1

        db.delete(admin)
        db.commit()
        # admin_actions.admin_id is ON DELETE SET NULL and keeps admin_email
        # beside it, so the record of what they did outlives the account.
        print(f"Removed {email}. What they did stays in the audit log.")
        return 0
    finally:
        db.close()


def send_reminders(dry_run=False):
    """The daily reminder emails and the weekly new-matches emails.

    Run by the Render cron job daily; each organization's matches email
    decides for itself whether a week has passed. See reminders.py.
    """
    import reminders

    db = SessionLocal()
    try:
        sent = reminders.run(db, dry_run=dry_run)
        matches = reminders.run_matches(db, dry_run=dry_run)
        print(f"{'Would send' if dry_run else 'Queued'} "
              f"{len(sent)} reminder email(s) and {len(matches)} new-matches "
              f"email(s).")
        return 0
    finally:
        db.close()


# Columns import-invites reads. Only `name` is required. `offers` and `needs`
# take category names or slugs separated by semicolons.
IMPORT_COLUMNS = ("name", "email", "organization_type", "location",
                  "description", "offers", "needs", "website")


def _categories_from(cell, row_no, column, problems):
    from categories import CATEGORY_LABELS

    by_name = {label.casefold(): slug for slug, label in CATEGORY_LABELS.items()}
    by_name.update({slug: slug for slug in CATEGORY_LABELS})
    slugs = []
    for part in (cell or "").split(";"):
        part = part.strip()
        if not part:
            continue
        slug = by_name.get(part.casefold())
        if slug is None:
            problems.append(f"row {row_no}: {column}: unknown category {part!r}")
        elif slug not in slugs:
            slugs.append(slug)
    return slugs


def import_invites(path, inviter_email, dry_run=False):
    """Create invited profiles from a spreadsheet, details filled in.

    The operator's version of the dashboard's "Invite an organization", for
    bringing on many at once: each row becomes an unclaimed profile carrying
    whatever details the sheet has, and the business claims it with its own
    address and password -- nobody holds a password for anyone else, and the
    profile is theirs to correct in onboarding, which opens prefilled.

    A row with an email gets the claim link mailed, from the inviting
    organization. A row without one has its link printed here, the only time
    it can be read (only a digest is stored), to be sent another way.

    All or nothing: every row is checked before any is written, so a typo on
    row 40 does not leave 39 half an import. Rows whose name already exists
    are skipped, so running the same sheet twice is harmless.
    """
    import csv
    import os
    import secrets
    from datetime import datetime, timezone

    from sqlalchemy import func

    from app import (MAX_DESCRIPTION, issue_token, length_problem,
                     screened_name)
    from links import LinkError, parse_website
    from notifications import notify_invitation

    db = SessionLocal()
    try:
        inviter = db.query(Organization).filter(
            Organization.email == inviter_email.strip().lower()).one_or_none()
        if inviter is None or not inviter.onboarding_complete:
            print(f"No organization with a finished profile signs in as "
                  f"{inviter_email}. Invitations say who they are from.",
                  file=sys.stderr)
            return 1

        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            unknown = set(reader.fieldnames or []) - set(IMPORT_COLUMNS)
            if "name" not in (reader.fieldnames or []) or unknown:
                print(f"The first row must name the columns. Allowed: "
                      f"{', '.join(IMPORT_COLUMNS)}."
                      + (f" Not recognized: {', '.join(sorted(unknown))}."
                         if unknown else ""), file=sys.stderr)
                return 1
            rows = list(reader)

        problems, ready, skipped = [], [], []
        seen = set()
        for row_no, raw in enumerate(rows, start=2):
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            name = row.get("name", "")
            if not name:
                problems.append(f"row {row_no}: name is missing")
                continue
            if name.casefold() in seen or db.query(Organization.id).filter(
                    func.lower(Organization.name) == name.casefold()).first():
                skipped.append(name)
                continue
            seen.add(name.casefold())

            problem, flagged = screened_name(name)
            problem = problem or length_problem("name", name)
            for field in ("organization_type", "location"):
                problem = problem or length_problem(field, row.get(field))
            email = row.get("email", "").lower()
            if email and not is_valid_email(email):
                problem = problem or f"{email!r} is not an email address"
            if len(row.get("description", "")) > MAX_DESCRIPTION:
                problem = problem or (f"description is over {MAX_DESCRIPTION} "
                                      f"characters")
            try:
                website = parse_website(row.get("website"))
            except LinkError as e:
                problem = problem or f"website: {e}"
            if problem:
                problems.append(f"row {row_no}: {problem}")
                continue

            ready.append({
                "name": name, "name_flagged": flagged, "email": email,
                "organization_type": row.get("organization_type") or None,
                "location": row.get("location") or None,
                "description": row.get("description") or None,
                "offers": _categories_from(row.get("offers"), row_no,
                                           "offers", problems),
                "needs": _categories_from(row.get("needs"), row_no,
                                          "needs", problems),
                "website_url": website,
            })

        for name in skipped:
            print(f"  skipped {name!r}: an organization with that name exists")
        if problems:
            print("Nothing was imported. Fix these and run it again:",
                  file=sys.stderr)
            for p in problems:
                print(f"  {p}", file=sys.stderr)
            return 1
        if dry_run:
            for r in ready:
                print(f"  would invite {r['name']!r}"
                      + (f", emailing {r['email']}" if r["email"]
                         else ", link printed"))
            print(f"Dry run: {len(ready)} to invite, {len(skipped)} skipped.")
            return 0

        base = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5001").rstrip("/")
        made = []
        for r in ready:
            token, digest = issue_token()
            invited = Organization(
                # The same reserved placeholder /api/invites uses; whoever
                # claims it chooses the real address.
                email=f"invite-{secrets.token_hex(8)}@invite.invalid",
                password_hash=None, onboarding_complete=False,
                claim_token_hash=digest,
                invited_at=datetime.now(timezone.utc),
                invited_by_id=inviter.id,
                **{k: v for k, v in r.items() if k != "email"},
            )
            db.add(invited)
            made.append((invited, token, r["email"]))
        db.commit()

        for invited, token, email in made:
            if email:
                notify_invitation(inviter, invited, email, token)
                print(f"  invited {invited.name!r}: emailed {email}")
            else:
                print(f"  invited {invited.name!r}: "
                      f"{base}/claim.html?token={token}")
        print(f"Invited {len(made)}, skipped {len(skipped)}.")
        return 0
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="manage.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    create = sub.add_parser("create-admin")
    create.add_argument("email")
    create.add_argument("--name", default="")

    sub.add_parser("list-admins")

    reset = sub.add_parser("reset-admin-password")
    reset.add_argument("email")

    remove = sub.add_parser("remove-admin")
    remove.add_argument("email")
    remove.add_argument("--force", action="store_true",
                        help="remove even if it is the only admin")

    reminders = sub.add_parser("send-reminders")
    reminders.add_argument("--dry-run", action="store_true",
                           help="print who would get what, and send nothing")

    imports = sub.add_parser("import-invites")
    imports.add_argument("path", help="a CSV file; see IMPORT_COLUMNS")
    imports.add_argument("--from", dest="inviter", required=True,
                         help="the sign-in email of the inviting organization")
    imports.add_argument("--dry-run", action="store_true",
                         help="check every row and write nothing")

    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.email, args.name)
    if args.command == "list-admins":
        return list_admins()
    if args.command == "reset-admin-password":
        return reset_admin_password(args.email)
    if args.command == "remove-admin":
        return remove_admin(args.email, args.force)
    if args.command == "send-reminders":
        return send_reminders(args.dry_run)
    if args.command == "import-invites":
        return import_invites(args.path, args.inviter, args.dry_run)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
