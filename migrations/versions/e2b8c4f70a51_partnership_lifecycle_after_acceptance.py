"""partnership lifecycle after acceptance

Revision ID: e2b8c4f70a51
Revises: c1d7e4a90b32
Create Date: 2026-08-20 14:02:51.336104

"accepted" was the end of the line, so every agreement ever made looked
equally live: one that ran its course last year sat in the same list, with the
same public page, as one starting next week. Nothing recorded whether either
side actually provided what it committed to, which is an odd omission for an
app whose claim is that both of them get something.

Completing is mutual, like accepting -- one organization deciding on its own
that a partnership is finished is a claim about what the other one received.
Ending is unilateral, because requiring agreement before you may stop would
let one side hold the other to a partnership by not answering.

The delivery columns are private to the two parties by design; see the note
in models.py. Nothing here is published.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b8c4f70a51'
down_revision: Union[str, Sequence[str], None] = 'c1d7e4a90b32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('partnerships', sa.Column(
        'proposer_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('partnerships', sa.Column(
        'recipient_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('partnerships', sa.Column(
        'completed_at', sa.DateTime(timezone=True), nullable=True))

    op.add_column('partnerships', sa.Column(
        'proposer_delivered', sa.Boolean(), nullable=True))
    op.add_column('partnerships', sa.Column(
        'recipient_delivered', sa.Boolean(), nullable=True))

    op.add_column('partnerships', sa.Column(
        'ended_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('partnerships', sa.Column(
        'ended_by_id', sa.Integer(), nullable=True))
    op.add_column('partnerships', sa.Column(
        'end_reason', sa.Text(), nullable=True))

    # SET NULL, matching the two party keys: an organization closing its
    # account must not take the record of how a partnership ended with it.
    op.create_foreign_key(
        'partnerships_ended_by_id_fkey', 'partnerships', 'organizations',
        ['ended_by_id'], ['id'], ondelete='SET NULL')

    # The status check has to admit the two new values before any row can
    # take one. Dropped and recreated -- a CHECK cannot be widened in place.
    op.drop_constraint('ck_partnerships_status', 'partnerships', type_='check')
    op.create_check_constraint(
        'ck_partnerships_status', 'partnerships',
        "status IN ('pending', 'accepted', 'declined', 'withdrawn', "
        "'completed', 'ended')")


def downgrade() -> None:
    """Downgrade schema.

    Rows that reached one of the new statuses have nowhere to go under the old
    check constraint. They are returned to 'accepted', which is what they were
    before being closed and the only prior status that is true of them -- the
    two sides did agree. The timestamps go with the columns.
    """
    op.execute("""
        UPDATE partnerships
           SET status = 'accepted'
         WHERE status IN ('completed', 'ended')
    """)

    op.drop_constraint('ck_partnerships_status', 'partnerships', type_='check')
    op.create_check_constraint(
        'ck_partnerships_status', 'partnerships',
        "status IN ('pending', 'accepted', 'declined', 'withdrawn')")

    op.drop_constraint(
        'partnerships_ended_by_id_fkey', 'partnerships', type_='foreignkey')

    op.drop_column('partnerships', 'end_reason')
    op.drop_column('partnerships', 'ended_by_id')
    op.drop_column('partnerships', 'ended_at')
    op.drop_column('partnerships', 'recipient_delivered')
    op.drop_column('partnerships', 'proposer_delivered')
    op.drop_column('partnerships', 'completed_at')
    op.drop_column('partnerships', 'recipient_completed_at')
    op.drop_column('partnerships', 'proposer_completed_at')
