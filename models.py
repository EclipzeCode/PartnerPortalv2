"""The organizations model.

This single table replaces the old `users`, `partners` and `onboarding_profiles`
trio. Those were disconnected: registering wrote a `users` row, onboarding wrote
an unrelated `onboarding_profiles` row with no link back, and search read from a
third table of seed data. The practical result was that a real organization
which signed up and completed onboarding was invisible to everyone else.

Here an account *is* an organization. Registering creates the row; onboarding
fills in the matchable parts and flips `onboarding_complete`.
"""

from datetime import date as date_type, datetime, time as time_type

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, String,
    Text, Time, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from categories import TIMELINE_LABELS, focus_labels_for, labels_for


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
    # What this organization works on. Not part of the needs/offers exchange
    # -- a cause is not something anyone trades -- so it has its own
    # vocabulary (categories.FOCUS_AREAS) and its own column. Matching reads
    # it to show two organizations where their work overlaps; it never widens
    # who is considered a match, because shared concerns are not by
    # themselves a partnership.
    focus_areas: Mapped[list[str]] = mapped_column(
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

    # Same shape as the pair above -- unhashed, single-use, cleared once spent
    # -- but shorter-lived (checked against a 1-hour window in app.py, not 7
    # days): this token alone is enough to set a new password, so it grants
    # more than the verify link does and is worth expiring faster. Set only by
    # /forgot-password, which never reveals whether the address it was asked
    # about actually has an account.
    password_reset_token: Mapped[str | None] = mapped_column(
        String(64), unique=True
    )
    password_reset_sent_at: Mapped[datetime | None] = mapped_column(
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
            "focus_areas": list(self.focus_areas or []),
            "focus_area_labels": focus_labels_for(self.focus_areas),
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
            "focus_areas": list(self.focus_areas or []),
            "focus_area_labels": focus_labels_for(self.focus_areas),
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

    # SET NULL rather than CASCADE, and nullable to allow it.
    #
    # Under CASCADE, one organization deleting its account destroyed every
    # partnership it was party to -- including agreements the *other* side had
    # confirmed and may have sent to a board or a funder. The counterpart was
    # not asked, was not told, and the public link they had shared started
    # answering 404. One side's decision to leave should not reach into the
    # other side's record of what was agreed.
    #
    # So an accepted partnership outlives either party, and the columns below
    # keep enough of each side to render the agreement once the row it pointed
    # at is gone. Proposals that never became agreements are a different case
    # and are removed outright -- see delete_account in app.py.
    proposer_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    recipient_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )

    # Who each side was, recorded on the agreement itself.
    #
    # Same reasoning as Event.partner_name: this is a record of something that
    # happened between two organizations, and it has to still read correctly
    # when one of them is no longer there. Written when the proposal is
    # created and refreshed when it is accepted, so the name on an agreement
    # is the name that side was using at the moment it agreed.
    #
    # These are a fallback, not the source: every accessor below prefers the
    # live organization while it exists, so an organization that renames
    # itself is shown under its current name rather than a stale copy. The
    # snapshot is what is left once there is nothing live to prefer.
    proposer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    proposer_type: Mapped[str | None] = mapped_column(String(120))
    proposer_location: Mapped[str | None] = mapped_column(String(255))
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_type: Mapped[str | None] = mapped_column(String(120))
    recipient_location: Mapped[str | None] = mapped_column(String(255))

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
        """The other organization, from `org_id`'s point of view.

        None when that organization has deleted its account. Callers that
        render a party want counterpart_party() instead, which falls back to
        the snapshot rather than disappearing.
        """
        return self.recipient if self.proposer_id == org_id else self.proposer

    def snapshot_parties(self):
        """Record who each side is, from the live rows.

        Called when the proposal is created and again when it is accepted, so
        an agreement carries the names both sides were using at the moment
        they agreed to it.
        """
        if self.proposer is not None:
            self.proposer_name = self.proposer.name
            self.proposer_type = self.proposer.organization_type
            self.proposer_location = self.proposer.location
        if self.recipient is not None:
            self.recipient_name = self.recipient.name
            self.recipient_type = self.recipient.organization_type
            self.recipient_location = self.recipient.location

    @staticmethod
    def _party(org, name, org_type, location):
        """One side of the agreement, live if it still exists.

        The live row is preferred so an organization that renames itself is
        shown under the name it uses now. The snapshot is what is left once
        there is no live row to prefer, and `deleted` says which of the two
        this is -- the frontend needs to know not to offer a profile link or
        a meeting with an organization that is no longer there.
        """
        if org is not None:
            return {
                "id": org.id,
                "name": org.name,
                "organization_type": org.organization_type,
                "location": org.location,
                "deleted": False,
            }
        return {
            "id": None,
            "name": name,
            "organization_type": org_type,
            "location": location,
            "deleted": True,
        }

    def proposer_party(self):
        return self._party(self.proposer, self.proposer_name,
                           self.proposer_type, self.proposer_location)

    def recipient_party(self):
        return self._party(self.recipient, self.recipient_name,
                           self.recipient_type, self.recipient_location)

    def counterpart_party(self, org_id):
        """The other side, from `org_id`'s point of view, deleted or not."""
        return (self.recipient_party() if self.proposer_id == org_id
                else self.proposer_party())

    def counterpart_dict(self, org_id):
        """What the proposal lists render the other side from.

        public_dict() while that organization exists, so nothing about a
        normal proposal changes. Once it is gone there is no profile to serve
        -- the row is deleted, not hidden -- so this is the party snapshot
        padded out with the empty lists the templates iterate over, rather
        than a missing key that would take the page down with it.
        """
        other = self.counterpart(org_id)
        if other is not None:
            return other.public_dict()

        party = self.counterpart_party(org_id)
        return {
            **party,
            "remote_friendly": False,
            "description": None,
            "needs": [], "offers": [],
            "needs_labels": [], "offers_labels": [],
            "focus_areas": [], "focus_area_labels": [],
            "needs_note": None, "offers_note": None,
            "partnership_goals": None,
            "contact_email": None, "contact_phone": None,
            "website_url": None, "instagram_url": None,
            "x_url": None, "linkedin_url": None,
            "links_public": False,
            "is_demo": False,
        }

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
            # Same keys as before, plus `deleted`. Read through the accessors
            # rather than off self.proposer/self.recipient directly, which are
            # None once that organization has closed its account.
            "proposer": self.proposer_party(),
            "recipient": self.recipient_party(),
            "proposer_gives": list(self.proposer_gives or []),
            "proposer_gives_labels": labels_for(self.proposer_gives),
            "recipient_gives": list(self.recipient_gives or []),
            "recipient_gives_labels": labels_for(self.recipient_gives),
        }

        if viewer_id is not None:
            data.update({
                "direction": (
                    "outgoing" if self.proposer_id == viewer_id else "incoming"
                ),
                "counterpart": self.counterpart_dict(viewer_id),
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
            # The reason the row outlives its parties. A funder holding this
            # link can still read what was agreed after either organization
            # has closed its account -- which is what deleting one used to
            # take away from the other, without asking or telling them.
            "parties": [
                {
                    **self.proposer_party(),
                    "gives": labels_for(self.proposer_gives),
                    "receives": labels_for(self.recipient_gives),
                },
                {
                    **self.recipient_party(),
                    "gives": labels_for(self.recipient_gives),
                    "receives": labels_for(self.proposer_gives),
                },
            ],
        }


class Event(Base):
    """A meeting an organization has scheduled with a partner.

    These lived in localStorage until now, which meant they were not really
    saved at all: they belonged to one browser on one device, vanished with
    site data, and never followed the account that created them. Everything
    else on the dashboard reads from the database, so a meeting quietly
    disappearing was the one place the page lost work someone had done.

    The partner is stored as the name shown at the time rather than a foreign
    key. This is a calendar note the owner wrote for themselves -- it should
    still read correctly after the other organization renames itself or
    deletes its account, neither of which should reach into someone else's
    diary. Nothing here is shown to the partner; only `organization_id` ever
    sees these rows.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Real Date/Time columns rather than the strings the browser sends, so the
    # database rejects "2026-13-45", and "next meeting first" is an ORDER BY
    # rather than a string comparison that only works while the format holds.
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    time: Mapped[time_type] = mapped_column(Time, nullable=False)
    # Hours. Fractional on purpose -- a 30-minute call is 0.5.
    duration: Mapped[float] = mapped_column(Float, nullable=False, server_default="1")

    partner_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("duration > 0", name="ck_events_duration_positive"),
        # Every read is "this org's meetings, soonest first".
        Index("ix_events_organization_date", "organization_id", "date", "time"),
    )

    def __repr__(self):
        return f"<Event {self.id} org={self.organization_id} {self.date} {self.title!r}>"

    def to_dict(self):
        """The shape ppdashboard.js already renders.

        date and time are formatted as the browser's own `YYYY-MM-DD` and
        `HH:MM`, which is what the date/time inputs produce and what the
        rendering code splits on -- isoformat() would append seconds to the
        time and quietly break `time.split(':')`.
        """
        return {
            "id": self.id,
            "title": self.title,
            "date": self.date.strftime("%Y-%m-%d"),
            "time": self.time.strftime("%H:%M"),
            "duration": self.duration,
            "partner": self.partner_name,
            "description": self.description or "",
            "location": self.location or "",
        }


class SavedLead(Base):
    """An organization one org has shortlisted to come back to.

    Matching answers "who could work with me", which changes as either side
    edits its profile and as the directory grows. That makes it a poor place
    to keep a decision: an org someone meant to follow up on could drift down
    the ranking, or out of it entirely, with nothing recording that anyone
    had picked it out.

    Deliberately one-directional and private. Being saved is not visible to
    the organization saved, is not a proposal, and says nothing to anyone
    else -- it is a bookmark, and treating it as a signal to the other side
    would turn a private shortlist into an unsolicited approach.
    """

    __tablename__ = "saved_leads"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The org doing the saving.
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # The org being saved. CASCADE as well, so a shortlist never outlives the
    # profile it points at and cannot resurrect a deleted organization.
    saved_organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Why this one was worth keeping. Private to the org that wrote it and
    # never shown to the organization it is about -- the same rule the row
    # itself follows. A shortlist that cannot say what it is for is a list of
    # names someone has to remember the reasons for.
    note: Mapped[str | None] = mapped_column(Text)

    saved_organization = relationship(
        "Organization", foreign_keys=[saved_organization_id], lazy="joined"
    )

    __table_args__ = (
        # Saving twice is the same shortlist, not two entries. The route
        # relies on this to stay idempotent under a double-clicked star.
        UniqueConstraint(
            "organization_id", "saved_organization_id", name="uq_saved_leads_pair"
        ),
        CheckConstraint(
            "organization_id <> saved_organization_id",
            name="ck_saved_leads_not_self",
        ),
        # Every read is "my shortlist, most recently saved first".
        Index("ix_saved_leads_organization", "organization_id", "created_at"),
    )

    def __repr__(self):
        return f"<SavedLead {self.organization_id}->{self.saved_organization_id}>"


class ProfileView(Base):
    """One recorded look at an organization's public profile.

    Rows exist to be counted, never to be listed. Deliberately no display of
    who visited: "someone looked at you" is a count, and turning it into
    identities would publish the browsing of people who never agreed to be
    seen doing it -- including signed-out visitors who have no account here
    at all.

    viewer_key is a salted digest, not an address. It exists so that
    refreshing a page five times is one view rather than five, and it is
    never shown, joined against, or reversed -- the salt is the app secret,
    so the rows say nothing about who a visitor was even to whoever holds the
    database.
    """

    __tablename__ = "profile_views"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Whose profile was looked at.
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    viewer_key: Mapped[str] = mapped_column(String(64), nullable=False)

    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Both reads are "this org's views", either all of them or since a
        # date; the dedup check adds viewer_key on top of the same prefix.
        Index("ix_profile_views_org_seen", "organization_id", "viewed_at"),
        Index("ix_profile_views_dedup", "organization_id", "viewer_key", "viewed_at"),
    )

    def __repr__(self):
        return f"<ProfileView org={self.organization_id} at={self.viewed_at}>"
