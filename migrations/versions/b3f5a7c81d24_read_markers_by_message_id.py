"""read markers as a message id rather than a timestamp

The marker answers one question -- which messages in this thread has this
side not seen -- and it answered it by comparing two clocks. Message.created_at
comes from Postgres (now(), at the inserting transaction's start); the marker
was written from the app server's datetime.now(). Those are different machines,
and a persistent offset between them breaks the comparison in whichever
direction it leans: a marker that runs ahead swallows new messages silently,
one that runs behind never lets the badge clear.

A message id is the same ordering with no clock in it. Both values now come
from one sequence in one database, so there is nothing left to disagree.

The old columns stay for now. Dropping them in the same migration that adds
these would mean the instant between the schema moving and the new code
landing is served by code reading columns that are gone. A follow-up removes
them once this has run.

Backfill: the newest message each side had already seen, which is the largest
id in the thread stamped at or before the old marker. A thread nobody opened
has a null marker and stays null -- the same "never opened" this started with.
It inherits whatever skew the old timestamps carried, because that is the only
record of what was read; it does not carry it forward.

Revision ID: b3f5a7c81d24
Revises: a4e91c62b7d5
Create Date: 2026-08-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f5a7c81d24'
down_revision: Union[str, Sequence[str], None] = 'a4e91c62b7d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# proposer/recipient are symmetric everywhere in this schema, so the two
# sides are one statement written twice rather than two rules.
_SIDES = ("proposer", "recipient")


def upgrade() -> None:
    """Upgrade schema."""
    # A plain integer and deliberately not a foreign key. Messages are only
    # ever deleted by cascade from the partnership that owns them, which
    # takes these columns with it -- so there is no dangling id to guard
    # against. A key with ON DELETE SET NULL would actively hurt: it would
    # read as "never opened" and show the whole thread unread again.
    for side in _SIDES:
        op.add_column(
            "partnerships",
            sa.Column(f"{side}_last_read_message_id", sa.Integer(),
                      nullable=True),
        )

    for side in _SIDES:
        op.execute(f"""
            UPDATE partnerships p
               SET {side}_last_read_message_id = (
                   SELECT MAX(m.id)
                     FROM messages m
                    WHERE m.partnership_id = p.id
                      AND m.created_at <= p.{side}_last_read_at
               )
             WHERE p.{side}_last_read_at IS NOT NULL
        """)

    # The unread count is "this thread, ids above N", so the index that used
    # to lead partnership_id, created_at leads partnership_id, id instead.
    # Same prefix, and id is what the comparison now sits on.
    op.drop_index("ix_messages_partnership", table_name="messages")
    op.create_index("ix_messages_partnership", "messages",
                    ["partnership_id", "id"])


def downgrade() -> None:
    """Downgrade schema.

    The timestamps were never stopped being written, so there is nothing to
    restore into them -- dropping the id columns is enough to put the old
    comparison back exactly as it was.
    """
    op.drop_index("ix_messages_partnership", table_name="messages")
    op.create_index("ix_messages_partnership", "messages",
                    ["partnership_id", "created_at"])

    for side in _SIDES:
        op.drop_column("partnerships", f"{side}_last_read_message_id")
