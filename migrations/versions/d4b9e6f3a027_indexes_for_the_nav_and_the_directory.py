"""indexes for the two questions every page asks

Revision ID: d4b9e6f3a027
Revises: c3a8d5e2f416
Create Date: 2026-09-15

Two filters ran on every signed-in page load with nothing to read but the
table.

events(awaiting_id, share_status) -- "is a shared meeting waiting on this
organization" -- is asked by /api/me for the nav badge and again when the
notification list is built. The only index on events was by owner and date,
and a proposed meeting's owner is the other organization, so this was a scan.

organizations(onboarding_complete, hidden_at) is the directory's base
filter and the matcher's: every candidate query starts from "listed and not
hidden". Partial, on exactly those rows, so it is small and stays small.

Additive; nothing is rewritten.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd4b9e6f3a027'
down_revision: Union[str, Sequence[str], None] = 'c3a8d5e2f416'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'ix_events_awaiting', 'events', ['awaiting_id', 'share_status'],
        postgresql_where=sa.text("awaiting_id IS NOT NULL"),
    )
    op.create_index(
        'ix_organizations_listed', 'organizations', ['id'],
        postgresql_where=sa.text(
            "onboarding_complete IS TRUE AND hidden_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_organizations_listed', table_name='organizations')
    op.drop_index('ix_events_awaiting', table_name='events')
