"""contact_messages table

The homepage form has always been delivered by email and never stored. That
reads as a defensible decision -- there is no inbox in this schema and no
admin view to read one from, so a table would only move the messages
somewhere nobody looks -- and it is wrong in the one case that matters.
Outbound mail does not leave this app until a sending domain is verified, so
every message anybody has sent through that form has gone nowhere at all,
silently, while the sender was shown a success.

Nothing here recovers the ones already lost. This only stops the next one.

handled_at rather than a boolean: null is the queue and a timestamp is the
record, and "when did somebody deal with this" is the question anybody
looking at an old message actually has. It ships now rather than with the
admin panel that will read it, because adding it later is a second migration
for a column the first one could have carried.

Revision ID: a7f31c05d284
Revises: f2c840b6ae19
Create Date: 2026-08-27 10:18:03.552914

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7f31c05d284'
down_revision: Union[str, Sequence[str], None] = 'f2c840b6ae19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'contact_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=64), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    # The only read that matters: unhandled, oldest first, because a support
    # queue is worked from the front.
    op.create_index('ix_contact_messages_queue', 'contact_messages',
                    ['handled_at', 'created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_contact_messages_queue', table_name='contact_messages')
    op.drop_table('contact_messages')
