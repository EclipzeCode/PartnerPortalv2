"""all-day meetings, and an optional duration

Revision ID: b7d2e0913c48
Revises: 54d93a4e0a1a
Create Date: 2026-08-22

Two things the events table could not record.

A length was mandatory, so scheduling "three o'clock on Tuesday" meant
picking an hour count nobody had agreed to, and the card then displayed that
invented range as though it were fact. duration becomes nullable; NULL means
nobody said, and the dashboard draws a start time with no range after it.
The existing `duration > 0` check needs no change -- a CHECK fails only on
FALSE, and NULL > 0 is NULL.

An all-day meeting had nowhere to go at all. all_day is the flag; the time
column stays NOT NULL and holds midnight for those rows, because every read
of this table is "soonest first" and a real 00:00 sorts an all-day meeting to
the top of its own day without any ORDER BY having to special-case it.

The two are mutually exclusive -- an all-day meeting has no length to state
-- and that is a constraint rather than a convention, so a code path that
forgets to clear one cannot leave a row that renders as both.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b7d2e0913c48'
down_revision: Union[str, Sequence[str], None] = '54d93a4e0a1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default so the column can be added NOT NULL against a table that
    # already has rows; every existing meeting is a timed one.
    op.add_column(
        'events',
        sa.Column(
            'all_day', sa.Boolean(), nullable=False, server_default=sa.text('false')
        ),
    )

    # The default is dropped with it: an insert that says nothing about the
    # length now means "nobody said", not "one hour".
    op.alter_column(
        'events', 'duration', existing_type=sa.Float(), nullable=True,
        server_default=None,
    )

    op.create_check_constraint(
        'ck_events_all_day_has_no_duration',
        'events',
        'NOT (all_day AND duration IS NOT NULL)',
    )


def downgrade() -> None:
    op.drop_constraint('ck_events_all_day_has_no_duration', 'events', type_='check')

    # An hour is what this schema assumed before the column could say
    # otherwise, and NOT NULL cannot go back on while any row is missing one.
    # All-day meetings become one-hour meetings at midnight, which is the
    # closest the old shape can get to them.
    op.execute('UPDATE events SET duration = 1 WHERE duration IS NULL')
    op.alter_column(
        'events', 'duration', existing_type=sa.Float(), nullable=False,
        server_default=sa.text('1'),
    )

    op.drop_column('events', 'all_day')
