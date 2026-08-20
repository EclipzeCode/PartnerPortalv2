"""pending email change

Revision ID: a7c05e31b9d2
Revises: f3a91c62d8e4
Create Date: 2026-08-20 16:55:03.712664

There was no way to change the address an account signs in with, so a typo at
signup was unrecoverable without someone editing the database by hand.

The new address is held here rather than written straight to `email`. An
address is the one field that cannot be checked by looking at it, and applying
a typo immediately locks somebody out of the account the change was meant to
move: the login becomes an address they do not own, and the reset link goes to
an inbox that does not exist. The old address stays live and stays the login
until a link sent to the new one is opened.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c05e31b9d2'
down_revision: Union[str, Sequence[str], None] = 'f3a91c62d8e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('organizations', sa.Column(
        'pending_email', sa.String(length=255), nullable=True))
    op.add_column('organizations', sa.Column(
        'pending_email_token', sa.String(length=64), nullable=True))
    op.add_column('organizations', sa.Column(
        'pending_email_sent_at', sa.DateTime(timezone=True), nullable=True))
    # Unique like the other one-shot tokens, so a lookup by token cannot
    # match two rows however unlikely the collision.
    op.create_unique_constraint(
        'uq_organizations_pending_email_token', 'organizations',
        ['pending_email_token'])


def downgrade() -> None:
    """Downgrade schema.

    Unconfirmed changes are dropped, which is the state they were already in:
    nothing had moved, and the account still signs in with the address it
    signed in with before.
    """
    op.drop_constraint('uq_organizations_pending_email_token', 'organizations',
                       type_='unique')
    op.drop_column('organizations', 'pending_email_sent_at')
    op.drop_column('organizations', 'pending_email_token')
    op.drop_column('organizations', 'pending_email')
