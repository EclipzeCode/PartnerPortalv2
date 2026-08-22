"""invitations: an unclaimed profile somebody was invited to claim

Gives the "a profile can exist before anyone owns it" case in models.py the
half it never had -- a way to create one, and a way for the organization it
was made for to take it over.

Revision ID: e7f4b2c91a58
Revises: d5c81a3f7b60
Create Date: 2026-08-22 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f4b2c91a58'
down_revision: Union[str, Sequence[str], None] = 'd5c81a3f7b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('organizations',
                  sa.Column('claim_token', sa.String(length=64), nullable=True))
    op.add_column('organizations',
                  sa.Column('invited_at', sa.DateTime(timezone=True),
                            nullable=True))
    op.add_column('organizations',
                  sa.Column('invited_by_id', sa.Integer(), nullable=True))
    op.create_unique_constraint(
        'uq_organizations_claim_token', 'organizations', ['claim_token'])
    op.create_foreign_key(
        'fk_organizations_invited_by_id', 'organizations', 'organizations',
        ['invited_by_id'], ['id'], ondelete='SET NULL')
    # Every read of this column asks the same question -- which invitations
    # did this organization send -- and it is the only way the outstanding
    # list is built.
    op.create_index('ix_organizations_invited_by', 'organizations',
                    ['invited_by_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_organizations_invited_by', table_name='organizations')
    op.drop_constraint('fk_organizations_invited_by_id', 'organizations',
                       type_='foreignkey')
    op.drop_constraint('uq_organizations_claim_token', 'organizations',
                       type_='unique')
    op.drop_column('organizations', 'invited_by_id')
    op.drop_column('organizations', 'invited_at')
    op.drop_column('organizations', 'claim_token')
