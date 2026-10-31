"""open requests: the partner_requests table and partnerships.request_id

Revision ID: f1a2c3d4e5b6
Revises: e8b1d4a6c372
Create Date: 2026-10-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1a2c3d4e5b6'
down_revision: Union[str, Sequence[str], None] = 'e8b1d4a6c372'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'partner_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('category', sa.String(64), nullable=False),
        sa.Column('quantity', postgresql.JSONB(), nullable=True),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('needed_by', sa.Date(), nullable=True),
        sa.Column('expires_on', sa.Date(), nullable=False),
        sa.Column('remote_ok', sa.Boolean(), nullable=False,
                  server_default='false'),
        sa.Column('status', sa.String(8), nullable=False,
                  server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('need', 'have')",
                           name='ck_partner_requests_kind'),
        sa.CheckConstraint("status IN ('open', 'filled', 'closed')",
                           name='ck_partner_requests_status'),
    )
    op.create_index('ix_partner_requests_board', 'partner_requests',
                    ['status', 'created_at'])
    op.create_index('ix_partner_requests_organization', 'partner_requests',
                    ['organization_id', 'status'])
    op.add_column('partnerships', sa.Column(
        'request_id', sa.Integer(),
        sa.ForeignKey('partner_requests.id', ondelete='SET NULL'),
        nullable=True))
    op.create_index('ix_partnerships_request_id', 'partnerships',
                    ['request_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_partnerships_request_id', table_name='partnerships')
    op.drop_column('partnerships', 'request_id')
    op.drop_index('ix_partner_requests_organization',
                  table_name='partner_requests')
    op.drop_index('ix_partner_requests_board', table_name='partner_requests')
    op.drop_table('partner_requests')
