"""repeating meetings

Revision ID: d3f8b21c7e05
Revises: c1a5f83b96e7
Create Date: 2026-08-28

A standing partner check-in was fifteen rows somebody typed in one at a time,
and moving it meant editing fifteen of them. This stores the series instead:
the row keeps its own date as the first occurrence, and `repeat` plus
`repeat_until` say how it recurs and when it stops. The rest are worked out
when the calendar is read (Event.occurrences) rather than written out as
rows -- writing them would mean choosing a horizon, rewriting the tail on
every edit, and orphaning whatever was written past the new end.

Both columns are nullable and NULL on every existing row, which is what a
meeting that happens once has always meant. No backfill: there is nothing to
infer, and inventing a rule for somebody's diary would be inventing meetings
they never scheduled.

The three constraints are the ones the model states, enforced where they
cannot be worked around:

  * `repeat` is one of the rules the expansion knows. Anything else would
    read as a one-off in one place and raise in another.
  * the rule and the end date travel together -- a rule with no end is
    unbounded, and an end with no rule describes nothing.
  * a series cannot end before it starts, which is a mistyped form rather
    than a meeting.

Written as a batch of ADD COLUMNs before the constraints, so the constraints
are validated against a table where every row already has NULLs in both --
which passes all three trivially, and means this does not lock anything for
longer than the ALTERs themselves.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd3f8b21c7e05'
down_revision: Union[str, Sequence[str], None] = 'c1a5f83b96e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("events", sa.Column("repeat", sa.String(length=16),
                                      nullable=True))
    op.add_column("events", sa.Column("repeat_until", sa.Date(),
                                      nullable=True))

    op.create_check_constraint(
        "ck_events_repeat_rule", "events",
        "repeat IS NULL OR repeat IN ('weekly', 'biweekly', 'monthly')",
    )
    op.create_check_constraint(
        "ck_events_repeat_needs_until", "events",
        "(repeat IS NULL) = (repeat_until IS NULL)",
    )
    op.create_check_constraint(
        "ck_events_repeat_until_after_start", "events",
        "repeat_until IS NULL OR repeat_until >= date",
    )


def downgrade() -> None:
    """Downgrade schema."""
    # The constraints go with the columns they constrain, so dropping the
    # columns would take them anyway -- named explicitly so this reads as the
    # exact inverse of the upgrade rather than relying on that.
    op.drop_constraint("ck_events_repeat_until_after_start", "events",
                       type_="check")
    op.drop_constraint("ck_events_repeat_needs_until", "events",
                       type_="check")
    op.drop_constraint("ck_events_repeat_rule", "events", type_="check")
    op.drop_column("events", "repeat_until")
    op.drop_column("events", "repeat")
