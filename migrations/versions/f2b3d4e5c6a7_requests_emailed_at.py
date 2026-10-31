"""requests_emailed_at on organizations, for the daily requests email

Revision ID: f2b3d4e5c6a7
Revises: f1a2c3d4e5b6
Create Date: 2026-10-31 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b3d4e5c6a7'
down_revision: Union[str, Sequence[str], None] = 'f1a2c3d4e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('organizations', sa.Column(
        'requests_emailed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('organizations', 'requests_emailed_at')
