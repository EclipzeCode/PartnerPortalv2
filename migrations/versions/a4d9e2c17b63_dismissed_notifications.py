"""a list of dismissed notification entries per organization

Revision ID: a4d9e2c17b63
Revises: f7a2c4e9b150
Create Date: 2026-09-19

The notification list is derived from partnership rows and messages rather
than stored, so until now the only way to clear it was "mark everything
seen". This holds the identities ("kind:proposal_id:timestamp") of the
entries an organization has dismissed one at a time; see
Organization.dismissed_notifications.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision: str = 'a4d9e2c17b63'
down_revision: Union[str, Sequence[str], None] = 'f7a2c4e9b150'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('organizations', sa.Column(
        'dismissed_notifications', postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('organizations', 'dismissed_notifications')
