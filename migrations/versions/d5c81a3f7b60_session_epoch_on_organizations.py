"""session epoch on organizations

Lets a password change end every other session on the account. The session
cookie records the epoch it was issued under and login_required refuses
anything older, so bumping this column revokes every cookie already out
there without needing anywhere to store them.

Existing rows start at 0, which is also what a fresh session is stamped
with, so nobody is signed out by the deploy itself.

Revision ID: d5c81a3f7b60
Revises: b7d2e0913c48
Create Date: 2026-08-22 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5c81a3f7b60'
down_revision: Union[str, Sequence[str], None] = 'b7d2e0913c48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'organizations',
        sa.Column('session_epoch', sa.Integer(),
                  server_default='0', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('organizations', 'session_epoch')
