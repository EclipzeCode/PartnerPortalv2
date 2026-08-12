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

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from categories import TIMELINE_LABELS, labels_for


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

    # --- Links -------------------------------------------------------------
    # All optional. Stored as full canonical URLs -- links.py normalises
    # whatever shape they were typed in, and only ever produces http(s) on a
    # known host, so rendering these in an href is safe.
    website_url: Mapped[str | None] = mapped_column(String(255))
    instagram_url: Mapped[str | None] = mapped_column(String(255))
    x_url: Mapped[str | None] = mapped_column(String(255))
    linkedin_url: Mapped[str | None] = mapped_column(String(255))

    # Who can see the four links above.
    #
    # False (the default) keeps them in public_dict only, so they reach
    # signed-in organizations and no one else -- the same treatment
    # contact_email and contact_phone get. True adds them to public_profile
    # as well, which is served to anyone with the profile URL.
    #
    # Defaulting to false matters: it means turning this on is always a
    # deliberate act by the organization, and an org that never touches the
    # setting is never surprised by where its handles ended up.
    links_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # --- State -------------------------------------------------------------
    # Only completed profiles are matchable; a half-filled row would pollute
    # everyone else's results.
    onboarding_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Read in exactly one place: create_proposal, which refuses to send a
    # partnership proposal from an unverified org -- but only when
    # REQUIRE_EMAIL_VERIFICATION is on, and it is off by default while
    # outbound email cannot reach anyone but the Resend account owner. So
    # this is recorded and shown everywhere, and currently blocks nothing.
    # Signing in, finishing a profile, appearing in search, and answering
    # proposals stay open regardless -- the gate is on reaching a stranger,
    # not on using the product.
    #
    # Organizations that existed before that rule were grandfathered to true
    # by migration 55c59219492b; the earliest of them hold no token at all and
    # could never have verified.
    #
    # Unhashed, like Partnership.share_token: single-use, revoked on verify,
    # and not a credential in the way a password is. Only ever one live token
    # per org -- a resend overwrites the column, which is what retires the
    # link in any older email.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    email_verify_token: Mapped[str | None] = mapped_column(
        String(64), unique=True
    )
    email_verify_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Covers the optional emails only: a partnership proposal arriving, and a
    # proposal being accepted or declined. Verification mail ignores this,
    # because it is how someone proves they own the address in the first
    # place -- an account that opted out before verifying could never verify.
    #
    # Defaults to true, unlike links_public: these emails are the only way to
    # learn a proposal is waiting without signing in to check, so silence has
    # to be chosen rather than arrived at by default.
    email_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    # Seeded example organizations. Kept out of real orgs' match results so a
    # new signup is never paired with something fictional, but still shown --
    # clearly labelled -- as example matches while the directory is small.
    is_demo: Mapped[bool] = mapped_column(
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
            **self._link_dict(),
            "links_public": self.links_public,
            "is_demo": self.is_demo,
        }

    def _link_dict(self):
        """The four link fields. Shared so public_dict and public_profile
        cannot drift apart on which columns count as "the links"."""
        return {
            "website_url": self.website_url,
            "instagram_url": self.instagram_url,
            "x_url": self.x_url,
            "linkedin_url": self.linkedin_url,
        }

    def public_profile(self):
        """The org's profile page. No account required.

        Narrower than public_dict on purpose. public_dict is "public" only in
        the sense of visible to another signed-in organization, and it carries
        contact_email and contact_phone precisely so a match can be acted on.
        This payload is served unauthenticated, so those would hand every
        listed organization's inbox and phone number to anyone crawling the
        site. Same line Partnership.public_summary draws.

        Contact details are never in here. The four links are the one
        exception, and only when the organization has ticked links_public --
        an opt-in, defaulting to off, so nothing appears here that its owner
        did not choose to publish.

        A signed-in viewer gets the full contact block regardless -- see the
        authenticated /api/organizations/<id>, which the profile page
        enriches from.
        """
        data = {
            "id": self.id,
            "name": self.name,
            "organization_type": self.organization_type,
            "location": self.location,
            "remote_friendly": self.remote_friendly,
            "description": self.description,
            "needs_labels": labels_for(self.needs),
            "offers_labels": labels_for(self.offers),
            "needs_note": self.needs_note,
            "offers_note": self.offers_note,
            "partnership_goals": self.partnership_goals,
            "is_demo": self.is_demo,
        }
        if self.links_public:
            data.update(self._link_dict())
        return data

    def private_dict(self):
        """The signed-in org's own record, including account-level fields."""
        data = self.public_dict()
        data.update({
            "email": self.email,
            "onboarding_complete": self.onboarding_complete,
            "has_password": self.password_hash is not None,
            "email_verified": self.email_verified,
            "email_notifications": self.email_notifications,
        })
        return data


class Partnership(Base):
    """A proposed -- and possibly agreed -- partnership between two orgs.

    This is the step a match is supposed to lead to. A match says "you two
    could help each other"; a partnership records what each side actually
    committed to, and whether the other side said yes.

    Terms are stored as category slugs on both sides rather than free text, so
    the agreement says the same thing to both parties and can be rendered
    without anyone having to interpret prose.
    """

    __tablename__ = "partnerships"

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    STATUSES = (PENDING, ACCEPTED, DECLINED, WITHDRAWN)

    id: Mapped[int] = mapped_column(primary_key=True)

    proposer_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=PENDING
    )

    # What each side commits to providing. Named from the proposal's point of
    # view so there is never a question of whose column is whose.
    proposer_gives: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    recipient_gives: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )

    timeline: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)
    # The recipient's note when accepting or declining.
    response_message: Mapped[str | None] = mapped_column(Text)

    # Minted on acceptance. Anyone holding it can read the summary without an
    # account, which is what makes the agreement shareable with a board or a
    # funder. Null until accepted, so a pending proposal has no public URL.
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    proposer = relationship(
        "Organization", foreign_keys=[proposer_id], lazy="joined"
    )
    recipient = relationship(
        "Organization", foreign_keys=[recipient_id], lazy="joined"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'withdrawn')",
            name="ck_partnerships_status",
        ),
        # An org proposing to itself is always a mistake, and the matching
        # query already excludes self -- enforce it here so no other code path
        # can create one.
        CheckConstraint(
            "proposer_id <> recipient_id", name="ck_partnerships_not_self"
        ),
        # At most one live proposal in a given direction. Without this, a
        # double-clicked submit button creates two pending proposals and the
        # recipient sees the same request twice.
        Index(
            "uq_partnerships_one_pending",
            "proposer_id", "recipient_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_partnerships_recipient", "recipient_id"),
        Index("ix_partnerships_proposer", "proposer_id"),
    )

    def __repr__(self):
        return (f"<Partnership {self.id} {self.proposer_id}->{self.recipient_id} "
                f"{self.status}>")

    def counterpart(self, org_id):
        """The other organization, from `org_id`'s point of view."""
        return self.recipient if self.proposer_id == org_id else self.proposer

    def gives_for(self, org_id):
        """What `org_id` committed to providing."""
        return list(
            (self.proposer_gives if self.proposer_id == org_id
             else self.recipient_gives) or []
        )

    def receives_for(self, org_id):
        """What `org_id` gets back."""
        return list(
            (self.recipient_gives if self.proposer_id == org_id
             else self.proposer_gives) or []
        )

    def to_dict(self, viewer_id=None):
        data = {
            "id": self.id,
            "status": self.status,
            "timeline": self.timeline,
            "timeline_label": TIMELINE_LABELS.get(self.timeline),
            "message": self.message,
            "response_message": self.response_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "responded_at": (
                self.responded_at.isoformat() if self.responded_at else None
            ),
            "share_token": self.share_token,
            "proposer": {
                "id": self.proposer.id, "name": self.proposer.name,
                "organization_type": self.proposer.organization_type,
                "location": self.proposer.location,
            },
            "recipient": {
                "id": self.recipient.id, "name": self.recipient.name,
                "organization_type": self.recipient.organization_type,
                "location": self.recipient.location,
            },
            "proposer_gives": list(self.proposer_gives or []),
            "proposer_gives_labels": labels_for(self.proposer_gives),
            "recipient_gives": list(self.recipient_gives or []),
            "recipient_gives_labels": labels_for(self.recipient_gives),
        }

        if viewer_id is not None:
            other = self.counterpart(viewer_id)
            data.update({
                "direction": (
                    "outgoing" if self.proposer_id == viewer_id else "incoming"
                ),
                "counterpart": other.public_dict(),
                "you_give": self.gives_for(viewer_id),
                "you_give_labels": labels_for(self.gives_for(viewer_id)),
                "you_receive": self.receives_for(viewer_id),
                "you_receive_labels": labels_for(self.receives_for(viewer_id)),
                # Only the recipient of a pending proposal can accept or
                # decline it; only the proposer can withdraw it.
                "can_respond": (
                    self.status == self.PENDING and self.recipient_id == viewer_id
                ),
                "can_withdraw": (
                    self.status == self.PENDING and self.proposer_id == viewer_id
                ),
            })
        return data

    def public_summary(self):
        """The shareable agreement. No contact details, no account required."""
        return {
            "status": self.status,
            "agreed_at": self.responded_at.isoformat() if self.responded_at else None,
            "timeline": self.timeline,
            "timeline_label": TIMELINE_LABELS.get(self.timeline),
            "message": self.message,
            "parties": [
                {
                    "name": self.proposer.name,
                    "organization_type": self.proposer.organization_type,
                    "location": self.proposer.location,
                    "gives": labels_for(self.proposer_gives),
                    "receives": labels_for(self.recipient_gives),
                },
                {
                    "name": self.recipient.name,
                    "organization_type": self.recipient.organization_type,
                    "location": self.recipient.location,
                    "gives": labels_for(self.recipient_gives),
                    "receives": labels_for(self.proposer_gives),
                },
            ],
        }
