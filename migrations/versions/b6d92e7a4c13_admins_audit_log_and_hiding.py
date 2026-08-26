"""admins, the audit log, and hiding an organization

Three things at once because they are one feature and none of them is useful
alone: an admins table nothing can act as, an audit log with no actions to
record, or a hidden_at column nothing can set.

admins is deliberately its own table rather than a flag on organizations. An
account here *is* an organization -- the row a stranger creates by filling in
a signup form -- so a privilege bit living there would sit in the same rows
every registration writes to. Nothing in `organizations` can make somebody an
admin, because the answer is not stored there. There is no signup route for
this table; rows come from `manage.py create-admin`.

hidden_at is discovery-only. A hidden organization can still sign in, edit its
profile and answer proposals; it stops appearing in the directory, in matches
and at its own public URL. A timestamp rather than a boolean because the audit
log wants "when" anyway.

admin_actions keeps admin_email beside a SET NULL admin_id, so removing an
admin does not quietly erase what they did.

Revision ID: b6d92e7a4c13
Revises: a7f31c05d284
Create Date: 2026-08-27 11:02:41.883275

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b6d92e7a4c13'
down_revision: Union[str, Sequence[str], None] = 'a7f31c05d284'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'admins',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('session_epoch', sa.Integer(),
                  server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )

    op.create_table(
        'admin_actions',
        sa.Column('id', sa.Integer(), nullable=False),
        # SET NULL, with the email kept beside it: removing an admin must not
        # erase the record of what they did.
        sa.Column('admin_id', sa.Integer(), nullable=True),
        sa.Column('admin_email', sa.String(length=255), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('detail', postgresql.JSONB(),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id'],
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_admin_actions_recent', 'admin_actions', ['created_at'])

    op.add_column('organizations',
                  sa.Column('hidden_at', sa.DateTime(timezone=True),
                            nullable=True))
    op.add_column('organizations',
                  sa.Column('hidden_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('organizations', 'hidden_reason')
    op.drop_column('organizations', 'hidden_at')
    op.drop_index('ix_admin_actions_recent', table_name='admin_actions')
    op.drop_table('admin_actions')
    op.drop_table('admins')
