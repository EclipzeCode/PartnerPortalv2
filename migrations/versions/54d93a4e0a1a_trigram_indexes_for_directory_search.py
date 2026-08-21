"""trigram indexes for directory search

Revision ID: 54d93a4e0a1a
Revises: a7c05e31b9d2
Create Date: 2026-08-21

/api/organizations searches name, location and description with
ILIKE '%term%'. A leading wildcard means no B-tree index can serve it, so
every directory search was a sequential scan -- run twice per request, once
for the COUNT that sizes the pager and once for the page itself.

pg_trgm indexes the three-character sequences in a value, which is exactly
what a substring match needs, and gin_trgm_ops teaches GIN to answer LIKE
and ILIKE from that. The query does not change: the planner picks the index
up on its own, and falls back to the scan for a term shorter than three
characters, which is the case the index genuinely cannot help with.

Not urgent at the directory's current size -- a scan over a few hundred rows
is nothing. It is here because the cost grows with every organization that
joins, and because adding it later means adding it under load.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '54d93a4e0a1a'
down_revision: Union[str, Sequence[str], None] = 'a7c05e31b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors the columns _contains() is applied to in app.py's list_organizations.
# The notes are searched deliberately not -- see the comment there.
_COLUMNS = ("name", "location", "description")


def upgrade() -> None:
    """Upgrade schema."""
    # Neon has pg_trgm available but not enabled by default. IF NOT EXISTS so
    # this is a no-op on a database where it is already on, rather than an
    # error that stops the rest of the migration.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for column in _COLUMNS:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_organizations_{column}_trgm "
            f"ON organizations USING gin ({column} gin_trgm_ops)"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for column in _COLUMNS:
        op.execute(f"DROP INDEX IF EXISTS ix_organizations_{column}_trgm")
    # The extension is deliberately left installed. Dropping it would take
    # any other index or query that came to depend on it with it, and an
    # enabled extension costs nothing on its own.
