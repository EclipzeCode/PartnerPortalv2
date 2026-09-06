"""store link tokens as hashes rather than as themselves

The three single-use link tokens on an organization -- verify an address,
confirm a change of address, reset a password -- were stored exactly as they
were mailed. Anything that could read this table could use them: a backup, a
read replica, a dump handed to somebody for debugging, an injection nobody
noticed. Not hashes to be cracked. Working links.

The original reasoning was that a link token is single-use, revoked when
spent, and "not a credential in the way a password is". That is true of the
verification token, which only marks an address as reachable. It was extended
to the other two, where it is not true at all: the reset token sets a
password, and the pending-email token moves the address the account signs in
with. Either one is an account takeover in one request.

So all three are hashed now, including the one where the old argument held.
Deciding per column which tokens are really credentials is a call somebody
has to get right again every time one is added, and it was already got wrong
once here.

The existing values are converted rather than discarded. sha256() over the
current text produces exactly what the application will now look up, so every
link already sitting in somebody's inbox keeps working -- which matters most
for the verification links, whose window is seven days. Dropping the columns
and starting clean would have silently broken every one of them.

Revision ID: a4d17f9c0b32
Revises: e5c31a8d40f7
Create Date: 2026-09-06 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4d17f9c0b32'
down_revision: Union[str, Sequence[str], None] = 'e5c31a8d40f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMNS = (
    "email_verify_token",
    "pending_email_token",
    "password_reset_token",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.alter_column("organizations", name, new_column_name=f"{name}_hash")
        # sha256() is built in from Postgres 11 and takes bytea, so the text
        # is cast on the way in and the digest hexed on the way out -- which
        # is the same value hashlib.sha256(...).hexdigest() produces in
        # app.py. Only rows that actually hold a token are touched; the
        # column is NULL for everyone with nothing outstanding.
        op.execute(
            f"UPDATE organizations "
            f"SET {name}_hash = encode(sha256({name}_hash::bytea), 'hex') "
            f"WHERE {name}_hash IS NOT NULL"
        )


def downgrade() -> None:
    """Rename back, and clear what cannot be un-hashed.

    A digest does not go back to the token it came from, so anything
    outstanding at this point is dropped rather than restored to a value that
    would never match. The cost is that links mailed since the upgrade stop
    working and have to be requested again -- which every one of these flows
    already supports, because a resend is the ordinary remedy for a link that
    got lost.
    """
    for name in _COLUMNS:
        op.execute(f"UPDATE organizations SET {name}_hash = NULL")
        op.alter_column("organizations", f"{name}_hash", new_column_name=name)
