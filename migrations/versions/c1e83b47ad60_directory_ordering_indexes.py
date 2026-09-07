"""indexes for the directory's two orderings

Revision ID: c1e83b47ad60
Revises: a4d17f9c0b32
Create Date: 2026-09-06

The trigram indexes added in 54d93a4e0a1a made the directory's *filters*
indexable. Its ORDER BY still was not.

_directory_query sorts every page one of two ways -- lower(name) for "A-Z"
and created_at DESC for "Newest" -- and neither had an index. lower(name) in
particular could not use one even in principle: a plain B-tree on `name`
indexes the values as written, and the query asks for them case-folded, which
is a different ordering (see the comment there: without the fold, "acme"
sorts after "Zebra"). So every directory page was a sort of the whole
filtered set to return twelve rows.

An expression index on lower(name) is the one the planner can actually use
for that, and it is what makes the common case -- an unfiltered first page,
which is what the public directory serves to anyone who clicks "Browse
partners" -- an index scan of twelve rows rather than a sort of everything.

Both are partial, restricted to the rows the directory can ever show. Every
query in _directory_query carries `onboarding_complete AND hidden_at IS NULL`
unconditionally, so a partial index is both smaller and still usable for
every one of them. is_demo is deliberately *not* in the predicate: the
signed-in listing excludes seeded examples and the public one includes them,
so an index that assumed either would only serve half the callers.

Cheap at the current size and pointless to add under load, which is the same
reason 54d93a4e0a1a gave for arriving early.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c1e83b47ad60'
down_revision: Union[str, Sequence[str], None] = 'a4d17f9c0b32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WHERE = "onboarding_complete AND hidden_at IS NULL"

# (name, the ORDER BY it serves). The trailing id in each mirrors the
# tie-breaker in _directory_query -- an index that stops at the sort column
# leaves the planner sorting the ties, and ties on lower(name) are exactly
# what two organizations with the same name produce.
_INDEXES = (
    ("ix_organizations_directory_name", "(lower(name)), id"),
    ("ix_organizations_directory_new", "created_at DESC, id DESC"),
)


def upgrade() -> None:
    """Upgrade schema."""
    for name, columns in _INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} "
            f"ON organizations ({columns}) WHERE {_WHERE}"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for name, _columns in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
