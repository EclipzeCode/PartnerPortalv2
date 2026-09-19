"""a per-organization count of the profile views pruned from the raw table

profile_views grew by one row per unique visitor per organization per day,
forever, and nothing ever read a row older than the longest series the
dashboard can draw. Rows past that window are now deleted on a timer, and
what they counted is added here so the all-time figure does not move.

Revision ID: c7d3e9a2b5f1
Revises: b8e4c2a1d9f7
Create Date: 2026-09-19 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d3e9a2b5f1'
down_revision: Union[str, Sequence[str], None] = 'b8e4c2a1d9f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'profile_view_archive',
        sa.Column('organization_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('counted', sa.Integer(), nullable=False,
                  server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('profile_view_archive')
