"""indexes on the two foreign keys that had none

Revision ID: a4c9e17f52b3
Revises: d5f2a91c7b04
Create Date: 2026-09-13

Postgres does not index a foreign key on its own, and two of the ones here
were reached from the referenced side without one.

saved_leads.saved_organization_id is read every time an organization is
deleted: ON DELETE CASCADE has to find every row that saved it, which was a
sequential scan of the shortlist table per deletion. The lookups that
matter day to day go the other way, through ix_saved_leads_organization.

messages.sender_id is read the same way when a sender's account closes --
ON DELETE SET NULL has to find every message they wrote -- and by nothing
else, since every read of a thread goes through partnership_id.

Neither is large yet, and neither is slow yet. Both are the kind of scan
that stays invisible until the tables are big enough for a deletion to time
out, which is the worst moment to discover it. Purely additive.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a4c9e17f52b3'
down_revision: Union[str, Sequence[str], None] = 'd5f2a91c7b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_saved_leads_saved_organization', 'saved_leads',
                    ['saved_organization_id'])
    op.create_index('ix_messages_sender', 'messages', ['sender_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_messages_sender', table_name='messages')
    op.drop_index('ix_saved_leads_saved_organization', table_name='saved_leads')
