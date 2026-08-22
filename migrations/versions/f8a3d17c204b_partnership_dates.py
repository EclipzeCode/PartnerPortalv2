"""start and end dates on a partnership

`timeline` is a slug out of a fixed list -- "1-3 months" -- which says
roughly how long a commitment is and cannot say when it runs. Both of these
are optional and independently so: a start with no end is an open-ended
arrangement rather than a half-filled form.

Revision ID: f8a3d17c204b
Revises: e7f4b2c91a58
Create Date: 2026-08-22 21:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a3d17c204b'
down_revision: Union[str, Sequence[str], None] = 'e7f4b2c91a58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('partnerships',
                  sa.Column('starts_on', sa.Date(), nullable=True))
    op.add_column('partnerships',
                  sa.Column('ends_on', sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('partnerships', 'ends_on')
    op.drop_column('partnerships', 'starts_on')
