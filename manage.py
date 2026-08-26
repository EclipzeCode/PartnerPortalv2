"""Operator commands. Run on a machine that already has the database.

    python manage.py create-admin  <email> [--name "Ada Lovelace"]
    python manage.py list-admins
    python manage.py reset-admin-password <email>
    python manage.py remove-admin <email>

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
from datetime import datetime, timezone

import bcrypt

from db import SessionLocal
from models import Admin

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
        print(f"Created. Sign in at /admin.html")
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


def remove_admin(email):
    email = (email or "").strip().lower()
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.email == email).one_or_none()
        if admin is None:
            print(f"No admin with address {email}.", file=sys.stderr)
            return 1
        if db.query(Admin).count() == 1:
            print("That is the only admin. Create another before removing "
                  "this one, or there is no way back into the panel.",
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

    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.email, args.name)
    if args.command == "list-admins":
        return list_admins()
    if args.command == "reset-admin-password":
        return reset_admin_password(args.email)
    if args.command == "remove-admin":
        return remove_admin(args.email)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
