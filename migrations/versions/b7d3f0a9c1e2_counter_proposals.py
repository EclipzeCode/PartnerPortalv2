"""whose turn a pending proposal is waiting on

Revision ID: b7d3f0a9c1e2
Revises: a4c9e17f52b3
Create Date: 2026-09-14

A recipient's answers were yes and no. "Yes, but half the hours" meant
declining and proposing afresh in the other direction, which lost the
message thread and the history of what had been on the table.

This column records whose answer a pending proposal is waiting for. It
starts with the recipient, as every proposal always has, and either side
changing the terms hands it to the other: the recipient's edit is a
counter-offer the proposer now has to accept, decline or counter again. The
row, the thread and the timestamps stay where they were.

Backfilled to 'recipient' for every existing row by the server default,
which is exactly what was true of them: nothing had ever moved the turn.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b7d3f0a9c1e2'
down_revision: Union[str, Sequence[str], None] = 'a4c9e17f52b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('partnerships', sa.Column(
        'awaiting_side', sa.String(length=9), nullable=False,
        server_default='recipient'))
    op.create_check_constraint(
        'ck_partnerships_awaiting_side', 'partnerships',
        "awaiting_side IN ('proposer', 'recipient')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_partnerships_awaiting_side', 'partnerships',
                       type_='check')
    op.drop_column('partnerships', 'awaiting_side')
