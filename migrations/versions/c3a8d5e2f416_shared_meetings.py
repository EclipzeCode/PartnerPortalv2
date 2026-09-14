"""meetings that belong to a partnership rather than to one calendar

Revision ID: c3a8d5e2f416
Revises: b7d3f0a9c1e2
Create Date: 2026-09-14

A meeting was one organization's calendar note: the partner was a name, and
nothing reached them. Arranging a time still happened somewhere else and
was typed into two calendars by hand.

A meeting may now belong to a partnership. It is proposed from inside the
message thread, waits on the other side the way a proposal does
(awaiting_id), and is accepted, moved or declined there; both parties see
it and both can download it. The thread records each step as a message
of kind 'meeting' pointing at the row, so the conversation shows what was
agreed and when.

Purely additive. Every existing meeting has no partnership and is exactly
what it was; every existing message is kind 'text'.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c3a8d5e2f416'
down_revision: Union[str, Sequence[str], None] = 'b7d3f0a9c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('events', sa.Column('partnership_id', sa.Integer(), nullable=True))
    op.add_column('events', sa.Column('share_status', sa.String(length=9), nullable=True))
    op.add_column('events', sa.Column('awaiting_id', sa.Integer(), nullable=True))
    op.add_column('events', sa.Column(
        'responded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('events', sa.Column('cancelled_by_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_events_partnership_id', 'events', 'partnerships',
                          ['partnership_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_events_awaiting_id', 'events', 'organizations',
                          ['awaiting_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_events_cancelled_by_id', 'events', 'organizations',
                          ['cancelled_by_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_events_partnership', 'events', ['partnership_id'])
    op.create_check_constraint(
        'ck_events_shared_has_status', 'events',
        '(partnership_id IS NULL) = (share_status IS NULL)')
    op.create_check_constraint(
        'ck_events_share_status', 'events',
        "share_status IS NULL OR share_status IN "
        "('proposed', 'accepted', 'declined', 'cancelled')")
    op.create_check_constraint(
        'ck_events_shared_is_one_off', 'events',
        'partnership_id IS NULL OR repeat IS NULL')

    op.add_column('messages', sa.Column(
        'kind', sa.String(length=16), nullable=False, server_default='text'))
    op.add_column('messages', sa.Column('meeting_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_messages_meeting_id', 'messages', 'events',
                          ['meeting_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_messages_meeting', 'messages', ['meeting_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_messages_meeting', table_name='messages')
    op.drop_constraint('fk_messages_meeting_id', 'messages', type_='foreignkey')
    op.drop_column('messages', 'meeting_id')
    op.drop_column('messages', 'kind')

    op.drop_constraint('ck_events_shared_is_one_off', 'events', type_='check')
    op.drop_constraint('ck_events_share_status', 'events', type_='check')
    op.drop_constraint('ck_events_shared_has_status', 'events', type_='check')
    op.drop_index('ix_events_partnership', table_name='events')
    op.drop_constraint('fk_events_cancelled_by_id', 'events', type_='foreignkey')
    op.drop_constraint('fk_events_awaiting_id', 'events', type_='foreignkey')
    op.drop_constraint('fk_events_partnership_id', 'events', type_='foreignkey')
    op.drop_column('events', 'cancelled_by_id')
    op.drop_column('events', 'responded_at')
    op.drop_column('events', 'awaiting_id')
    op.drop_column('events', 'share_status')
    op.drop_column('events', 'partnership_id')
