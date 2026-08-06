"""The organizations model.

This single table replaces the old `users`, `partners` and `onboarding_profiles`
trio. Those were disconnected: registering wrote a `users` row, onboarding wrote
an unrelated `onboarding_profiles` row with no link back, and search read from a
third table of seed data. The practical result was that a real organization
which signed up and completed onboarding was invisible to everyone else.

Here an account *is* an organization. Registering creates the row; onboarding
fills in the matchable parts and flips `onboarding_complete`.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from categories import labels_for


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- Account -----------------------------------------------------------
    # Stored lower-cased so login is not case-sensitive.
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Nullable on purpose: a profile can exist before anyone owns it. That
    # covers seeded demo orgs and lets you pre-create a profile for an org you
    # are recruiting, which they can claim later.
    password_hash: Mapped[str | None] = mapped_column(String(255))

    # --- Identity ----------------------------------------------------------
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_type: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(255))
    remote_friendly: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    description: Mapped[str | None] = mapped_column(Text)

    # --- Matching ----------------------------------------------------------
    # Category slugs from categories.py. What one org offers is drawn from the
    # same vocabulary as what another needs, which is what makes the two-way
    # match a simple array overlap.
    needs: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    offers: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    # Free text kept alongside the structured lists -- useful context for a
    # human reading a profile, never used for matching.
    needs_note: Mapped[str | None] = mapped_column(Text)
    offers_note: Mapped[str | None] = mapped_column(Text)
    partnership_goals: Mapped[str | None] = mapped_column(Text)

    # --- Public contact ----------------------------------------------------
    # Separate from the login email: the address an org wants partners to use
    # is often not the one someone signed up with.
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(32))

    # --- State -------------------------------------------------------------
    # Only completed profiles are matchable; a half-filled row would pollute
    # everyone else's results.
    onboarding_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # GIN indexes make the `&&` overlap operator indexable, so finding
        # candidates stays a database operation as the directory grows.
        Index("ix_organizations_needs", "needs", postgresql_using="gin"),
        Index("ix_organizations_offers", "offers", postgresql_using="gin"),
    )

    def __repr__(self):
        return f"<Organization {self.id} {self.name!r}>"

    # --- Serialisation -----------------------------------------------------
    def public_dict(self):
        """Fields safe to show to any signed-in organization.

        Deliberately excludes password_hash and the login email. Contact
        details are included -- the point of a match is being able to reach
        the other side.
        """
        return {
            "id": self.id,
            "name": self.name,
            "organization_type": self.organization_type,
            "location": self.location,
            "remote_friendly": self.remote_friendly,
            "description": self.description,
            "needs": list(self.needs or []),
            "offers": list(self.offers or []),
            "needs_labels": labels_for(self.needs),
            "offers_labels": labels_for(self.offers),
            "needs_note": self.needs_note,
            "offers_note": self.offers_note,
            "partnership_goals": self.partnership_goals,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
        }

    def private_dict(self):
        """The signed-in org's own record, including account-level fields."""
        data = self.public_dict()
        data.update({
            "email": self.email,
            "onboarding_complete": self.onboarding_complete,
            "has_password": self.password_hash is not None,
        })
        return data
