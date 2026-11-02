"""origin on partnerships: proposed here, or recorded after the fact

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-11-02 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a8'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('partnerships', sa.Column(
        'origin', sa.String(16), nullable=False, server_default='proposed'))
    op.create_check_constraint(
        'ck_partnerships_origin', 'partnerships',
        "origin IN ('proposed', 'recorded')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_partnerships_origin', 'partnerships')
    op.drop_column('partnerships', 'origin')
