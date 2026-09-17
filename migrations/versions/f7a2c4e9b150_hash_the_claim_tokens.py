"""store the digest of a claim token, not the token

Revision ID: f7a2c4e9b150
Revises: e5c1a7b2d938
Create Date: 2026-09-16

Every other single-use link token here -- password reset, email
verification, email change -- is stored as a SHA-256 digest, so a read of
the table hands out nothing that works in a URL. The claim token was the
one exception, kept raw so the invitations list could show the link again.
It is a digest now, the column says so, and a sender who needs the link
again asks for a new one (POST /api/invites/<id>/link), which retires the
old one.

The rows are hashed in place: an outstanding invitation keeps working with
the link that was already sent, because the digest of that link is what
the lookup now compares against.
"""
import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f7a2c4e9b150'
down_revision: Union[str, Sequence[str], None] = 'e5c1a7b2d938'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, claim_token FROM organizations WHERE claim_token IS NOT NULL"
    )).all()
    for row in rows:
        digest = hashlib.sha256(row.claim_token.encode("utf-8")).hexdigest()
        conn.execute(
            sa.text("UPDATE organizations SET claim_token = :d WHERE id = :i"),
            {"d": digest, "i": row.id},
        )
    op.alter_column('organizations', 'claim_token',
                    new_column_name='claim_token_hash')


def downgrade() -> None:
    """Downgrade schema.

    The name goes back; the digests cannot. An outstanding invitation
    after a downgrade has to be re-sent.
    """
    op.alter_column('organizations', 'claim_token_hash',
                    new_column_name='claim_token')
