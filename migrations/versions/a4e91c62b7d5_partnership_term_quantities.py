"""how much of each term a partnership commits to

Beside proposer_gives / recipient_gives rather than replacing them: the
arrays answer which categories, these answer how much, and a term with no
entry is a term without a quantity -- which is what every proposal sent
before this existed already is. So there is nothing to backfill.

Revision ID: a4e91c62b7d5
Revises: f8a3d17c204b
Create Date: 2026-08-22 23:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a4e91c62b7d5'
down_revision: Union[str, Sequence[str], None] = 'f8a3d17c204b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for column in ("proposer_quantities", "recipient_quantities"):
        op.add_column(
            "partnerships",
            sa.Column(column, postgresql.JSONB(astext_type=sa.Text()),
                      server_default="{}", nullable=False),
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("partnerships", "recipient_quantities")
    op.drop_column("partnerships", "proposer_quantities")
