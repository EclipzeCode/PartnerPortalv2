"""remove the seeded example organizations and the is_demo flag

The directory no longer pads itself with fictional organizations. Every
foreign key into organizations is ON DELETE CASCADE or SET NULL, so the rows
go cleanly; they had no owner, so nobody is losing an account.

Revision ID: e8b1d4a6c372
Revises: d9f1b3c7a2e4
Create Date: 2026-10-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8b1d4a6c372'
down_revision: Union[str, Sequence[str], None] = 'd9f1b3c7a2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DELETE FROM organizations WHERE is_demo IS TRUE")
    op.drop_column('organizations', 'is_demo')


def downgrade() -> None:
    """Downgrade schema. The deleted rows are not restored."""
    op.add_column('organizations',
                  sa.Column('is_demo', sa.Boolean(), nullable=False,
                            server_default='false'))
