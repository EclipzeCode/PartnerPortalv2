"""messages on a proposal

Revision ID: f3a91c62d8e4
Revises: e2b8c4f70a51
Create Date: 2026-08-20 15:41:12.884209

A proposal carried exactly one message and one reply. Two organizations
working out what "event space" actually means had to leave the site and use
the contact email on the card -- which is also the point at which what they
agreed stops being written down anywhere.

The thread hangs off the partnership rather than off a pair of organizations,
which is the access rule in one line: you can write to an organization
because there is a live proposal between you, not because you found them in
the directory.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a91c62d8e4'
down_revision: Union[str, Sequence[str], None] = 'e2b8c4f70a51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('partnership_id', sa.Integer(), nullable=False),
        # SET NULL rather than CASCADE: an organization closing its account
        # must not delete its half of a conversation the other side is still
        # party to. sender_name keeps the thread readable afterwards.
        sa.Column('sender_id', sa.Integer(), nullable=True),
        sa.Column('sender_name', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['partnership_id'], ['partnerships.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['organizations.id'],
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_messages_partnership', 'messages',
                    ['partnership_id', 'created_at'])

    # When each side last opened the thread. One indexed comparison answers
    # "how many are waiting on me", rather than a read flag per message per
    # party. Null means never opened, which every existing row is.
    op.add_column('partnerships', sa.Column(
        'proposer_last_read_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('partnerships', sa.Column(
        'recipient_last_read_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema.

    Drops the threads. There is nowhere in the old schema to put them: the
    proposal's single `message` column is the proposer's opening note and
    already occupied, and folding a conversation into it would rewrite what
    one side said as the other.
    """
    op.drop_column('partnerships', 'recipient_last_read_at')
    op.drop_column('partnerships', 'proposer_last_read_at')
    op.drop_index('ix_messages_partnership', table_name='messages')
    op.drop_table('messages')
