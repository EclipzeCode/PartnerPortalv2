"""the zone a meeting's date and time are written in

A meeting was stored as a date and a wall-clock time and nothing else, which
is a complete thought only while everyone involved is in one place. Two
organizations agreeing to meet at three had no way to say whose three, and
the dashboard read every meeting in whatever zone the browser happened to be
in -- so the same meeting moved when its owner traveled.

The zone is recorded rather than the time being converted to UTC. Converting
looks equivalent and is not, for anything in the future: the offset a zone
will have on a date months away is a prediction. Store the instant and a
meeting on the far side of a DST boundary -- or one whose government moves
that boundary, which happens most years somewhere -- silently shifts an hour.
Store the wall clock and the zone, and "three o'clock in Austin" stays three
o'clock in Austin however the rules change; the instant is derived when
something actually needs one.

Nullable, and left null on every existing row. There is no honest backfill:
nothing recorded where those meetings were entered, and defaulting them to
the server's zone, or to any one organization's, would be inventing an answer
for someone else's diary. Null means "no zone recorded" and reads as the
viewer's own -- which is the assumption those rows were already written
under, so nothing about them changes.

Revision ID: c9e1a4b7f302
Revises: b3f5a7c81d24
Create Date: 2026-08-23 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e1a4b7f302'
down_revision: Union[str, Sequence[str], None] = 'b3f5a7c81d24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 64 characters: the longest IANA name in current tzdata is well under
    # half that, and the column holds a name from that list or nothing.
    op.add_column(
        "events",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("events", "timezone")
