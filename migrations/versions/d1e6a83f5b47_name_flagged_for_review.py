"""name_flagged for review on organizations

The name filter used to have one list and one answer: matched, refused. That
turned away organizations named after Coon Rapids, Cripple Creek and anything
using a vulgarity on purpose -- with no allowlist, no appeal and no inbox
behind the message, since outbound mail does not leave this app yet.

Terms with no plausible innocent reading are still refused outright and need
no column. This is for the other half: a name that matched something
ambiguous is written, published and matchable exactly as any other, and
carries a mark so a person can look at it later. False on every existing row,
which is the truthful backfill -- nothing that is already here has been
screened under the new rule, and marking rows for review that nobody chose to
mark would fill the queue with the entire directory.

Revision ID: d1e6a83f5b47
Revises: c9e1a4b7f302
Create Date: 2026-08-24 14:12:08.334971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e6a83f5b47'
down_revision: Union[str, Sequence[str], None] = 'c9e1a4b7f302'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'organizations',
        sa.Column('name_flagged', sa.Boolean(),
                  server_default='false', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('organizations', 'name_flagged')
