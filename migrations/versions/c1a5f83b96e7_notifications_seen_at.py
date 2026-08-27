"""notifications_seen_at on organizations

The notification list is derived rather than stored, which is the right shape
-- every entry is already a fact on a partnership row or a message, and a
table would be a second copy kept in step by hand. But derived data has
nowhere to record that somebody has read it, so old news sat in the list for
the full sixty-day window with no way to clear it.

One nullable timestamp answers it, and null is the honest backfill: nobody
has marked anything read yet.

It deliberately does not affect what is actionable. A proposal waiting on an
answer does not stop waiting because somebody looked at the list.

Revision ID: c1a5f83b96e7
Revises: b6d92e7a4c13
Create Date: 2026-08-27 14:26:19.447021

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1a5f83b96e7'
down_revision: Union[str, Sequence[str], None] = 'b6d92e7a4c13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('organizations',
                  sa.Column('notifications_seen_at',
                            sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('organizations', 'notifications_seen_at')
