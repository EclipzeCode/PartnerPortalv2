"""partnerships outlive a deleted party

Revision ID: c1d7e4a90b32
Revises: ce31fc6e6110
Create Date: 2026-08-20 11:22:04.118273

Both foreign keys were ON DELETE CASCADE, so one organization deleting its
account destroyed every partnership it was party to -- including agreements
the other side had confirmed and shared. The counterpart was not asked and
not told; the public link they had sent to a board or a funder simply began
answering 404.

This makes both keys SET NULL and records who each side was on the agreement
itself, so the row survives either party leaving. The snapshot is a fallback,
not the source: the model prefers the live organization while it exists, so a
rename is still reflected everywhere.

Backfill runs before the columns are made NOT NULL, so existing rows are
filled from the organizations they still point at. That ordering is what
makes this apply to a populated database as well as an empty one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d7e4a90b32'
down_revision: Union[str, Sequence[str], None] = 'ce31fc6e6110'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Added nullable, filled, then tightened -- an existing table has rows
    # that would fail a NOT NULL added in one step.
    op.add_column('partnerships',
                  sa.Column('proposer_name', sa.String(length=255), nullable=True))
    op.add_column('partnerships',
                  sa.Column('proposer_type', sa.String(length=120), nullable=True))
    op.add_column('partnerships',
                  sa.Column('proposer_location', sa.String(length=255), nullable=True))
    op.add_column('partnerships',
                  sa.Column('recipient_name', sa.String(length=255), nullable=True))
    op.add_column('partnerships',
                  sa.Column('recipient_type', sa.String(length=120), nullable=True))
    op.add_column('partnerships',
                  sa.Column('recipient_location', sa.String(length=255), nullable=True))

    # Every row still points at both organizations at this point: the old
    # CASCADE guaranteed there were no orphans to leave behind.
    op.execute("""
        UPDATE partnerships p
           SET proposer_name     = o.name,
               proposer_type     = o.organization_type,
               proposer_location = o.location
          FROM organizations o
         WHERE o.id = p.proposer_id
    """)
    op.execute("""
        UPDATE partnerships p
           SET recipient_name     = o.name,
               recipient_type     = o.organization_type,
               recipient_location = o.location
          FROM organizations o
         WHERE o.id = p.recipient_id
    """)

    op.alter_column('partnerships', 'proposer_name', nullable=False)
    op.alter_column('partnerships', 'recipient_name', nullable=False)

    # The keys themselves. Dropped and recreated because ON DELETE is part of
    # the constraint, not something ALTER can change in place.
    op.drop_constraint('partnerships_proposer_id_fkey',
                       'partnerships', type_='foreignkey')
    op.drop_constraint('partnerships_recipient_id_fkey',
                       'partnerships', type_='foreignkey')

    op.alter_column('partnerships', 'proposer_id',
                    existing_type=sa.Integer(), nullable=True)
    op.alter_column('partnerships', 'recipient_id',
                    existing_type=sa.Integer(), nullable=True)

    op.create_foreign_key('partnerships_proposer_id_fkey', 'partnerships',
                          'organizations', ['proposer_id'], ['id'],
                          ondelete='SET NULL')
    op.create_foreign_key('partnerships_recipient_id_fkey', 'partnerships',
                          'organizations', ['recipient_id'], ['id'],
                          ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema.

    Rows whose party has already been deleted cannot go back: NOT NULL and a
    CASCADE key have nowhere to put a null. They are removed, which is the
    state the old schema would have left them in anyway.
    """
    op.execute("""
        DELETE FROM partnerships
         WHERE proposer_id IS NULL OR recipient_id IS NULL
    """)

    op.drop_constraint('partnerships_proposer_id_fkey',
                       'partnerships', type_='foreignkey')
    op.drop_constraint('partnerships_recipient_id_fkey',
                       'partnerships', type_='foreignkey')

    op.alter_column('partnerships', 'proposer_id',
                    existing_type=sa.Integer(), nullable=False)
    op.alter_column('partnerships', 'recipient_id',
                    existing_type=sa.Integer(), nullable=False)

    op.create_foreign_key('partnerships_proposer_id_fkey', 'partnerships',
                          'organizations', ['proposer_id'], ['id'],
                          ondelete='CASCADE')
    op.create_foreign_key('partnerships_recipient_id_fkey', 'partnerships',
                          'organizations', ['recipient_id'], ['id'],
                          ondelete='CASCADE')

    op.drop_column('partnerships', 'recipient_location')
    op.drop_column('partnerships', 'recipient_type')
    op.drop_column('partnerships', 'recipient_name')
    op.drop_column('partnerships', 'proposer_location')
    op.drop_column('partnerships', 'proposer_type')
    op.drop_column('partnerships', 'proposer_name')
