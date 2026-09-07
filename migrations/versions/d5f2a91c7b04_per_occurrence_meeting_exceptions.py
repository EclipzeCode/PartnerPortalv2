"""per-occurrence exceptions for repeating meetings

Revision ID: d5f2a91c7b04
Revises: c1e83b47ad60
Create Date: 2026-09-06

A repeating meeting was one row and its edits applied to all of it, so
"we are skipping next week" and "move just this week to Thursday" had one
answer: end the series and start another, losing the history and leaving two
rows describing one meeting.

This table records the exceptions. A row either cancels one occurrence or
moves it, and the check constraint below is what keeps those the only two
shapes -- a cancellation carries no schedule, a move carries all of it, and
nothing half-filled can be written.

Purely additive. Every existing meeting has no exceptions and behaves exactly
as it did; the feature only exists for series somebody actually edits one week
of.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd5f2a91c7b04'
down_revision: Union[str, Sequence[str], None] = 'c1e83b47ad60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'event_exceptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        # The date the series lands on, which is the occurrence's identity and
        # does not change when it is moved.
        sa.Column('occurs_on', sa.Date(), nullable=False),
        sa.Column('cancelled', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('date', sa.Date(), nullable=True),
        sa.Column('time', sa.Time(), nullable=True),
        sa.Column('duration', sa.Float(), nullable=True),
        sa.Column('all_day', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # One exception per occurrence: two rows for the same week is a
        # meeting in two places, decided by whichever the expansion read first.
        sa.UniqueConstraint('event_id', 'occurs_on',
                            name='uq_event_exceptions_occurrence'),
        sa.CheckConstraint(
            "(cancelled AND date IS NULL AND time IS NULL"
            " AND duration IS NULL AND all_day IS NULL)"
            " OR (NOT cancelled AND date IS NOT NULL AND time IS NOT NULL"
            " AND all_day IS NOT NULL)",
            name='ck_event_exceptions_shape',
        ),
        # The same rules events applies to its own schedule, so an occurrence
        # cannot be given a shape its series could not have.
        sa.CheckConstraint('duration IS NULL OR duration > 0',
                           name='ck_event_exceptions_duration_positive'),
        sa.CheckConstraint('NOT (all_day AND duration IS NOT NULL)',
                           name='ck_event_exceptions_all_day_has_no_duration'),
    )
    op.create_index('ix_event_exceptions_event', 'event_exceptions',
                    ['event_id', 'occurs_on'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_event_exceptions_event', table_name='event_exceptions')
    op.drop_table('event_exceptions')
