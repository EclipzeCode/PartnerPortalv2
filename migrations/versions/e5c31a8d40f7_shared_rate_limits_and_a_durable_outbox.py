"""shared rate limits, a durable email outbox, and the focus_areas index

Revision ID: e5c31a8d40f7
Revises: d3f8b21c7e05
Create Date: 2026-08-28 15:10:44.218903

Three fixes that all needed schema.

`rate_limit_attempts` moves the limiter out of process memory. It lived in a
dict, and gunicorn runs two workers -- so every limit was up to twice what it
said, inconsistently, and a restart or a free-plan spin-down cleared the lot.

`email_outbox` makes a queued message survive the process that accepted it.
Delivery was an in-memory queue with an atexit drain, which covers a clean
shutdown and nothing else; anything queued during a SIGKILL was gone, with no
record it had existed. For a password reset that is a locked-out account.

And a GIN index on organizations.focus_areas, which the directory filters
with the same `&&` operator as needs and offers -- the only one of the three
that was a sequential scan.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e5c31a8d40f7'
down_revision: Union[str, Sequence[str], None] = 'd3f8b21c7e05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'rate_limit_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bucket', sa.String(length=64), nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('attempted_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_rate_limit_lookup', 'rate_limit_attempts',
                    ['bucket', 'key', 'attempted_at'], unique=False)
    op.create_index('ix_rate_limit_sweep', 'rate_limit_attempts',
                    ['attempted_at'], unique=False)

    op.create_table(
        'email_outbox',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('to_addr', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('html', sa.Text(), nullable=False),
        sa.Column('body_text', sa.Text(), nullable=False),
        sa.Column('reply_to', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False,
                  server_default=sa.text("'queued'")),
        sa.Column('attempts', sa.Integer(), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('queued', 'sending', 'delivered', 'failed')",
            name='ck_email_outbox_status'),
        sa.PrimaryKeyConstraint('id'),
    )
    # Partial, on the status each query actually asks about: delivered rows
    # are what accumulate here and neither index needs to carry them.
    op.create_index('ix_email_outbox_claimable', 'email_outbox',
                    ['next_attempt_at', 'id'], unique=False,
                    postgresql_where=sa.text("status = 'queued'"))
    op.create_index('ix_email_outbox_claimed', 'email_outbox',
                    ['claimed_at'], unique=False,
                    postgresql_where=sa.text("status = 'sending'"))

    # Concurrently is not available inside alembic's transaction, and this
    # table is small enough that the brief lock does not matter.
    op.create_index('ix_organizations_focus_areas', 'organizations',
                    ['focus_areas'], unique=False,
                    postgresql_using='gin')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_organizations_focus_areas', table_name='organizations')
    op.drop_index('ix_email_outbox_claimed', table_name='email_outbox')
    op.drop_index('ix_email_outbox_claimable', table_name='email_outbox')
    op.drop_table('email_outbox')
    op.drop_index('ix_rate_limit_sweep', table_name='rate_limit_attempts')
    op.drop_index('ix_rate_limit_lookup', table_name='rate_limit_attempts')
    op.drop_table('rate_limit_attempts')
