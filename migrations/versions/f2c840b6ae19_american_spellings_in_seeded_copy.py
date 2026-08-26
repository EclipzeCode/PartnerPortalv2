"""american spellings in the seeded example copy

Data only -- no schema change.

The spelling sweep that went through this codebase covered files. These are
rows, and they were written by a version of seed.py that has since been
corrected: the file already says "Lakeside Community Center" and "mobilize",
while the database still says "Centre" and "mobilise". Correcting seed.py was
never going to reach them, because seed() skips an organization that already
exists rather than updating it -- which is the drift this fixes and which
`python seed.py --refresh` now closes.

Nine occurrences across five rows, every one of them `is_demo` -- the seeded
examples the directory shows while it is small. No real organization's own
words are touched, and the WHERE says so rather than relying on the strings
happening not to appear anywhere else.

Scoped replacements rather than a blanket regex. "Centre" is a proper noun in
one row's name and a common noun in another's description, and something that
rewrote every "centre" everywhere would eventually reach an organization that
had chosen its own name.

Revision ID: f2c840b6ae19
Revises: e4b72c1d9f38
Create Date: 2026-08-26 15:07:44.219338

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2c840b6ae19'
down_revision: Union[str, Sequence[str], None] = 'e4b72c1d9f38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (column, British, American). Case matters: two of these open a sentence or
# a proper name, and replace() in Postgres is case-sensitive.
#
# Singular forms only, and deliberately: "programme" is a prefix of
# "programmes", so one replacement covers both and the plural needs no entry.
# Listing both is what makes these order-dependent, and order-dependent in a
# way that breaks going backwards -- undo "programs" to "programmes" and a
# following pass for "program" finds one inside it and leaves
# "programmemes". With only the singular there is nothing to sequence.
REPLACEMENTS = [
    ("name", "Centre", "Center"),
    ("description", "Neighbourhood", "Neighborhood"),
    ("description", "centre", "center"),
    ("description", "organising", "organizing"),
    ("description", "programme", "program"),
    ("offers_note", "mobilise", "mobilize"),
]

REVERSALS = [(col, new, old) for col, old, new in REPLACEMENTS]


def _apply(pairs):
    for column, old, new in pairs:
        op.execute(
            sa.text(
                f"UPDATE organizations "
                f"SET {column} = replace({column}, :old, :new) "
                f"WHERE is_demo IS TRUE "
                f"  AND {column} LIKE :like"
            ).bindparams(old=old, new=new, like=f"%{old}%")
        )


def upgrade() -> None:
    """Bring the seeded copy in line with what seed.py already says."""
    _apply(REPLACEMENTS)


def downgrade() -> None:
    """Put the British spellings back.

    Each pair is its own word rather than a prefix of another, so these can
    run in any order and twice without compounding -- which is the property
    the note above exists to protect.
    """
    _apply(REVERSALS)
