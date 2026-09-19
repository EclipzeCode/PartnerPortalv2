"""whether a queued email is one the recipient could have switched off

Those are the messages that should carry a List-Unsubscribe header -- the
thing a mail client turns into an "Unsubscribe" button, and the thing
receiving servers read to decide a sender is a bulk sender behaving well.
The outbox is durable, so the fact has to travel with the row.

Revision ID: d9f1b3c7a2e4
Revises: c7d3e9a2b5f1
Create Date: 2026-09-19 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9f1b3c7a2e4'
down_revision: Union[str, Sequence[str], None] = 'c7d3e9a2b5f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('email_outbox',
                  sa.Column('optional', sa.Boolean(), nullable=False,
                            server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('email_outbox', 'optional')
