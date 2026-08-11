"""grandfather existing organizations as email verified

Revision ID: 55c59219492b
Revises: 6aadf53f4dae
Create Date: 2026-08-11 22:50:11.557171

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55c59219492b'
down_revision: Union[str, Sequence[str], None] = '6aadf53f4dae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Mark every organization that already exists as verified.

    Data only -- no schema change. Verifying an email address is about to
    start meaning something (an unverified org cannot send a partnership
    proposal), and every row predating this migration signed up when there
    was nothing to do about it: the flag was recorded but never enforced,
    and the earliest accounts were created before the verification email
    existed at all, so they hold no token and could not verify even if they
    wanted to.

    Gating them on a step that was never offered would lock working accounts
    out of the product to enforce a rule that arrived after they joined.
    Everyone who signs up from here on gets the real flow.

    Deliberately unconditional rather than filtered on created_at: at the
    moment this runs, "every row in the table" and "every row that predates
    the rule" are the same set, and a timestamp comparison would only add a
    clock-skew failure mode for no benefit.
    """
    op.execute(
        "UPDATE organizations SET email_verified = true "
        "WHERE email_verified = false"
    )


def downgrade() -> None:
    """Intentionally does nothing.

    The inverse would be "set email_verified = false", which cannot tell a
    row this migration touched from one that verified legitimately after it
    ran -- so it would silently un-verify real confirmations. Leaving the
    data as it is costs nothing: the column and its meaning both survive a
    downgrade, and re-running the upgrade is idempotent.
    """
