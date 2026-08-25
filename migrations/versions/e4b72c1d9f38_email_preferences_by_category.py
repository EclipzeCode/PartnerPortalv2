"""email preferences by category on organizations

One boolean covered every kind of mail this app sends, so the only way to
stop a busy message thread reaching your inbox was also the way to stop
hearing that somebody had proposed a partnership -- which is the thing the
product exists to tell you. The switch people would actually reach for turned
off the one they came for.

Three categories now: proposals, messages, partnerships. Stored as an object
rather than three columns so that adding a fourth is a code change instead of
another migration, and so an absent key can mean "yes" -- which is what lets
a category introduced later be on for everybody without a backfill.

The backfill only has to carry the one decision anybody has actually made.
An organization that turned the old switch off chose silence, so all three
land false; everybody else gets an empty object, which reads as every default
-- not as three explicit trues, because nobody chose those and writing them
would turn a default into a decision.

email_notifications is deliberately left in place and still written by the
app. Dropping it in the same release as the column that replaces it means a
rollback silently un-mutes everyone who had turned it off. It goes once this
has settled, which is the same arrangement the read markers on partnerships
are under.

Revision ID: e4b72c1d9f38
Revises: d1e6a83f5b47
Create Date: 2026-08-26 09:41:22.117043

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e4b72c1d9f38'
down_revision: Union[str, Sequence[str], None] = 'd1e6a83f5b47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'organizations',
        sa.Column('email_preferences', postgresql.JSONB(),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    # Only the organizations that chose silence. Everyone else keeps the
    # empty object the column defaults to.
    op.execute(
        "UPDATE organizations "
        "SET email_preferences = "
        "'{\"proposals\": false, \"messages\": false, "
        "\"partnerships\": false}'::jsonb "
        "WHERE email_notifications IS FALSE"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # email_notifications was never stopped being written, so there is
    # nothing to restore into it on the way back down.
    op.drop_column('organizations', 'email_preferences')
