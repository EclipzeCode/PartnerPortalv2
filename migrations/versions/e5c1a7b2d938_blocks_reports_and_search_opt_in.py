"""blocks, thread reports, and an opt-in to search indexing

Revision ID: e5c1a7b2d938
Revises: d4b9e6f3a027
Create Date: 2026-09-15

Three things the README listed as not built.

blocks: one organization refusing to hear from another. See models.Block
for what it stops; nothing here is visible to the blocked side.

thread_reports: a conversation somebody asked an admin to look at. Lands
in the admin panel's queue beside the contact messages.

organizations.searchable: whether the public profile may be indexed. Off
for everyone -- nobody agreed to search results by filling in onboarding.
When on, the profile page drops noindex and is listed in the sitemap.

Additive; nothing existing changes meaning.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e5c1a7b2d938'
down_revision: Union[str, Sequence[str], None] = 'd4b9e6f3a027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('organizations', sa.Column(
        'searchable', sa.Boolean(), nullable=False, server_default='false'))

    op.create_table(
        'blocks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('blocker_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('blocked_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('blocker_id', 'blocked_id', name='uq_blocks_pair'),
        sa.CheckConstraint('blocker_id <> blocked_id', name='ck_blocks_not_self'),
    )
    op.create_index('ix_blocks_blocked', 'blocks', ['blocked_id'])

    op.create_table(
        'thread_reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('partnership_id', sa.Integer(),
                  sa.ForeignKey('partnerships.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('reporter_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('reported_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('reporter_name', sa.String(length=255), nullable=False),
        sa.Column('reported_name', sa.String(length=255), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_thread_reports_queue', 'thread_reports',
                    ['handled_at', 'created_at'])
    op.create_index('ix_thread_reports_partnership', 'thread_reports',
                    ['partnership_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_thread_reports_partnership', table_name='thread_reports')
    op.drop_index('ix_thread_reports_queue', table_name='thread_reports')
    op.drop_table('thread_reports')
    op.drop_index('ix_blocks_blocked', table_name='blocks')
    op.drop_table('blocks')
    op.drop_column('organizations', 'searchable')
