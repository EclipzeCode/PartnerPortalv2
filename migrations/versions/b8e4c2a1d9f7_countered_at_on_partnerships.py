"""when a proposal was last handed back with different terms

The "suggested different terms" notification was dated by updated_at, which
moves whenever the row is touched -- reading the thread stamps a read
marker on it, changing the share link stamps it too -- so a counter that had
been seen became "new" again every time either side did anything. This
column is written once per counter and nothing else moves it.

Backfilled from updated_at for the pending proposals currently waiting on
their proposer, which is the only state a counter leaves a row in; nothing
better is recorded for them, and it is what the notification was already
showing.

Revision ID: b8e4c2a1d9f7
Revises: a4d9e2c17b63
Create Date: 2026-09-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e4c2a1d9f7'
down_revision: Union[str, Sequence[str], None] = 'a4d9e2c17b63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('partnerships',
                  sa.Column('countered_at', sa.DateTime(timezone=True),
                            nullable=True))
    op.execute(
        "UPDATE partnerships SET countered_at = updated_at "
        "WHERE status = 'pending' AND awaiting_side = 'proposer'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('partnerships', 'countered_at')
