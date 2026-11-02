"""reminders_sent table, for the daily reminder emails

Revision ID: a1b2c3d4e5f7
Revises: f2b3d4e5c6a7
Create Date: 2026-11-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, Sequence[str], None] = 'f2b3d4e5c6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'reminders_sent',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('item', sa.String(64), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('organization_id', 'kind', 'item',
                            name='uq_reminders_sent_once'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('reminders_sent')
