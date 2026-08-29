"""The organizations model.

This single table replaces the old `users`, `partners` and `onboarding_profiles`
trio. Those were disconnected: registering wrote a `users` row, onboarding wrote
an unrelated `onboarding_profiles` row with no link back, and search read from a
third table of seed data. The practical result was that a real organization
which signed up and completed onboarding was invisible to everyone else.

Here an account *is* an organization. Registering creates the row; onboarding
fills in the matchable parts and flips `onboarding_complete`.
"""

from datetime import date as date_type, datetime, time as time_type, timedelta

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, Time, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from categories import (
    TIMELINE_LABELS, focus_labels_for, label_for, labels_for,
)
from units import format_quantity


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

    # --- Invitations -------------------------------------------------------
    # An unclaimed profile someone created to bring another organization here.
    # The token is the credential -- whoever opens the link finishes the
    # account by choosing an address and a password -- so it is single-use and
    # cleared the moment it is spent, like every other token in this file.
    #
    # This is the half of "profiles can exist without a password" that was
    # described and never built. It exists because matching has a cold start
    # that nothing else here addresses: an organization whose needs and offers
    # overlap with nobody sees an empty product, and the one thing it can
    # actually do about that is bring the partner it already has in mind.
    #
    # No address is asked for when the invite is made. Requiring one would
    # mean answering "that organization is already registered" to anybody who
    # guessed an address, which is the enumeration oracle /register works to
    # avoid -- and the person doing the inviting often knows the organization
    # without knowing which address it would sign up under. The claimer
    # supplies their own on the way in.
    claim_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Who did the inviting, so the claim page can say whose invitation this is
    # -- an invitation from nobody is a signup form with extra steps. SET NULL
    # rather than CASCADE: the invitation still stands if the organization
    # that sent it closes its account, and the page falls back to naming
    # nobody rather than the link going dead.
    invited_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    invited_by: Mapped["Organization | None"] = relationship(
        "Organization", remote_side="Organization.id", foreign_keys=[invited_by_id],
    )

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
    # All optional. Stored as full canonical URLs -- links.py normalizes
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

    # A requested new login address, held here until it is confirmed.
    #
    # Not written straight to `email`, because the address someone typed is
    # the one thing that cannot be checked by looking at it. A typo applied
    # immediately locks them out of the account it was meant to move -- the
    # login is the new address, the reset link goes to an inbox that does not
    # exist, and there is no way back. So the change lands only when a link
    # sent to the new address is opened, which is the same proof registration
    # asks for and the only proof that matters here.
    #
    # The old address stays live and stays the login until that happens.
    pending_email: Mapped[str | None] = mapped_column(String(255))
    pending_email_token: Mapped[str | None] = mapped_column(
        String(64), unique=True
    )
    pending_email_sent_at: Mapped[datetime | None] = mapped_column(
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

    # Which generation of sessions is still valid for this account.
    #
    # A session cookie carried nothing but org_id, so it stayed valid until it
    # expired however the account changed underneath it. Changing a password
    # did not end any of the sessions already open on it -- which is exactly
    # backward, because the person most likely to change a password is the
    # one who thinks somebody else has it. They would be told the password was
    # changed, and the other session would keep working for weeks.
    #
    # So the session records the epoch it was issued under, login_required
    # compares the two, and anything stamped with an older number is refused.
    # Bumping this is the revoke-everywhere switch; see _end_other_sessions.
    #
    # An integer rather than a timestamp: the question is only "is this the
    # current generation", and a counter cannot be confused by clock skew or
    # by two changes landing inside the same second.
    # default=0 as well as server_default: the server default fills existing
    # rows, but a freshly constructed Organization would carry None in Python
    # until it was reloaded -- and /register stamps the new session from this
    # attribute the moment it commits. None there would be written into the
    # cookie and then compared against the 0 in the database, signing every
    # new account out of the session it had just been given.
    session_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )

    # Covers the optional emails only: a partnership proposal arriving, and a
    # proposal being accepted or declined. Verification mail ignores this,
    # because it is how someone proves they own the address in the first
    # place -- an account that opted out before verifying could never verify.
    #
    # Defaults to true, unlike links_public: these emails are the only way to
    # learn a proposal is waiting without signing in to check, so silence has
    # to be chosen rather than arrived at by default.
    # Superseded by email_preferences below and still written, so that rolling
    # this code back does not silently mute every organization that has since
    # turned one category off. Nothing reads it. Removed, with its column,
    # once this has settled -- the same arrangement the read markers use.
    email_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    # Which kinds of email this organization wants, by category.
    #
    # One switch used to cover all of it, which made the only way to stop a
    # busy thread mailing you also the way to stop hearing that somebody
    # proposed a partnership. Those are not the same decision, and the second
    # is the one this product exists to deliver -- so the switch people
    # actually reached for turned off the thing they came for.
    #
    # Stored as an object rather than a column per category so that adding a
    # category is a code change instead of a migration, and so a future
    # setting that is not a boolean (a digest, say) has somewhere to live.
    # An absent key means yes: a category added later is on for everybody
    # without a backfill, and only an explicit false is silence. That
    # direction matters -- see wants_email.
    email_preferences: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    # This organization's name matched something ambiguous in
    # moderation.SOFT_FLAGGED -- a term that is a slur or a vulgarity in one
    # reading and a place name, a surname or a deliberate choice in another.
    #
    # Never a reason to hide or refuse anything. The row is live, matchable
    # and public exactly as any other; this only records that a person should
    # look at the name eventually. Refusing on a maybe is what this column
    # exists to stop: the filter used to do that, and it turned away
    # organizations named after Coon Rapids and Cripple Creek.
    #
    # Nothing reads it yet. The admin review page is what will, and until it
    # exists a flagged signup writes a warning to the log, which is the
    # cheapest place a person can actually come across one.
    name_flagged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # How far back the notification list has been read.
    #
    # The list is derived rather than stored -- every entry in it is already a
    # fact on a partnership row or a message -- and that is the right shape:
    # a notifications table would be a second copy of all of it, kept in step
    # by hand and wrong the first time somebody forgot to write to it. But
    # derived data has nowhere to record that a person has seen it, which is
    # why old news sat in the list for the full sixty days.
    #
    # One column answers it. Anything that happened before this has been
    # seen; anything after has not.
    #
    # It deliberately does not touch what is *actionable*. A proposal waiting
    # on an answer does not stop waiting because somebody looked at the list,
    # so marking everything read clears the news and leaves the work -- which
    # is also why the nav badge, which counts work, is unaffected by it.
    notifications_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # --- Moderation --------------------------------------------------------
    # When an admin took this organization out of the directory, if they did.
    #
    # A timestamp rather than a boolean, because "when" is the question
    # anybody looking at a hidden profile has, and the audit log wants it
    # anyway. Null is the normal state and is what every query below tests
    # for, so a row that has never been touched needs nothing said about it.
    #
    # Hiding is discovery-only, and deliberately narrow. The organization can
    # still sign in, edit its profile, read its messages and answer proposals;
    # it stops appearing in the directory, in anybody's matches and at its own
    # public URL. Existing partnerships are untouched -- counterpart_dict
    # reads the relationship directly rather than going through those queries
    # -- because taking a profile out of a listing is not the same act as
    # withdrawing somebody from an agreement they already made.
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # What the organization is told. Written into the email that goes out, so
    # this is a sentence for them to read rather than a note to self.
    hidden_reason: Mapped[str | None] = mapped_column(Text)

    # Seeded example organizations. Kept out of real orgs' match results so a
    # new signup is never paired with something fictional, but still shown --
    # clearly labeled -- as example matches while the directory is small.
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
        # focus_areas is filtered with the same `&&` operator as the two
        # above -- see the directory's ?focus= parameter -- and was the one
        # array column without an index behind it. Two of the three overlap
        # filters were indexed and the third was a sequential scan, which is
        # the kind of asymmetry that stays invisible until the directory is
        # big enough for it to matter and is then hard to attribute.
        Index("ix_organizations_focus_areas", "focus_areas",
              postgresql_using="gin"),
    )

    # What an organization can be mailed about, and what each category covers.
    #
    # Three, not eight. A preferences screen with one row per message type is
    # a screen nobody finishes reading, and the categories people actually
    # think in are: somebody wants to work with me, somebody is talking to me,
    # something changed about a partnership I already have.
    #
    # Account security -- verification, password reset, the notice that an
    # email change was requested -- is deliberately absent and always sent.
    # Those are not notifications about other people's activity; they are the
    # only channel back to somebody locked out of their own account, and a
    # preference that can silence them is a preference that can lock somebody
    # out permanently. See the senders in notifications.py, which say so at
    # each one.
    EMAIL_CATEGORIES = {
        "proposals": "Proposals sent to you, and answers to yours",
        "messages": "Messages in a partnership conversation",
        "partnerships": "Partnerships completing, ending, or their shared link changing",
    }

    def wants_email(self, category):
        """Whether this organization wants mail in `category`.

        Absent means yes, and only an explicit false is no. Two things follow.
        A category added in a later release is on for everybody without a
        backfill; and a preferences object that is empty, malformed, or from
        a version that had never heard of this category fails toward sending
        rather than toward silence.

        That direction is chosen. Sending an email somebody did not want is a
        message they delete. Not sending one is an organization never learning
        a partnership was proposed to them -- and, because there is no other
        channel, never learning it at all.
        """
        prefs = self.email_preferences or {}
        return prefs.get(category) is not False

    def __repr__(self):
        return f"<Organization {self.id} {self.name!r}>"

    # --- Serialization -----------------------------------------------------
    def public_dict(self, *, contact=False):
        """Fields safe to show to any signed-in organization.

        Deliberately excludes password_hash and the login email.

        Contact details are opt-in rather than always present, which is the
        one thing to be careful about when calling this. Reaching the other
        side is the point of a match, so it is tempting to include them
        everywhere -- but this payload is also what the bulk listings are
        built from, and those answer with up to a page of organizations at a
        time. An address and a phone number on every row means one free
        account can walk the directory and leave with the contact list for
        every organization on the site: the same harvesting public_profile()
        already refuses to serve anonymously, undone from behind a signup
        form that costs nothing and verifies nothing.

        So they travel only where somebody asked about one organization in
        particular -- the single-org route the detail views read, the
        caller's own record, and the other side of a proposal, who they are
        already in a conversation with. The listings carry everything needed
        to decide *whether* to approach an organization, and the profile is
        one request away when the answer is yes.
        """
        data = {
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
            **self._link_dict(),
            "links_public": self.links_public,
            "is_demo": self.is_demo,
        }
        # Omitted rather than sent as null, so the absence is a fact about
        # this payload rather than a claim that the organization has no
        # address -- the same shape public_profile() uses for the links it
        # withholds.
        if contact:
            data["contact_email"] = self.contact_email
            data["contact_phone"] = self.contact_phone
        return data

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
        """The signed-in org's own record, including account-level fields.

        contact=True because these are the caller's own details: the settings
        and onboarding forms render them back into the fields they were typed
        into, and withholding them here would blank both on every load.
        """
        data = self.public_dict(contact=True)
        data.update({
            "email": self.email,
            "onboarding_complete": self.onboarding_complete,
            "has_password": self.password_hash is not None,
            "email_verified": self.email_verified,
            # Resolved rather than sent raw. The column stores only what has
            # been chosen -- an absent key is a default, not a value -- and a
            # settings page that has to know that rule in order to draw three
            # switches is a second place for it to be got wrong.
            "email_preferences": {
                key: self.wants_email(key) for key in self.EMAIL_CATEGORIES
            },
            # So the settings page can say a change is waiting rather than
            # showing the old address with no sign anything is in flight.
            "pending_email": self.pending_email,
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
    # What happens after both sides said yes. "accepted" used to be the end of
    # the line, which left every agreement ever made looking equally live --
    # a partnership that ran its course last year sat in the same list, with
    # the same public page, as one starting next week. For an app whose claim
    # is that both sides actually get something, never recording whether they
    # did is the more awkward half of that.
    COMPLETED = "completed"
    ENDED = "ended"
    STATUSES = (PENDING, ACCEPTED, DECLINED, WITHDRAWN, COMPLETED, ENDED)

    # Statuses where the partnership is over, whichever way it went.
    SETTLED = (DECLINED, WITHDRAWN, COMPLETED, ENDED)
    # Statuses that resolve at the public share link. A spent agreement is
    # still a true record of what was agreed, and a funder holding the link
    # is better served by "this finished in March" than by a 404.
    PUBLIC = (ACCEPTED, COMPLETED, ENDED)

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

    # How much of each of the above, keyed by the category slug it qualifies:
    #
    #   {"volunteers": {"amount": 30, "unit": "people", "detail": null},
    #    "event_space": {"amount": 4000, "unit": "sqft", "detail": null}}
    #
    # Beside the arrays rather than replacing them, and that is the whole
    # design. The arrays answer *which* categories, which is what the
    # "neither side may commit to something it has not listed" rule checks
    # and what every existing reader of a proposal is built on. These answer
    # *how much*, for the subset that says. A category with no entry here is
    # a term without a quantity, which is exactly what every proposal sent
    # before this existed was -- so nothing needs backfilling and nothing
    # already agreed is retroactively missing something.
    #
    # JSONB rather than a partnership_terms table, matching the choice
    # `needs` and `offers` already make on Organization: this is data that
    # belongs to one row, is read whole every time it is read at all, and
    # never joins to anything. Postgres can still total it -- jsonb_each over
    # completed partnerships is what the profile rollup will be -- and if
    # that ever needs its own indexes it can become a table without any of
    # the callers noticing.
    #
    # Kept in step with the arrays by _clean_quantities in app.py, which
    # drops any key whose category is no longer part of the proposal.
    proposer_quantities: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    recipient_quantities: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    timeline: Mapped[str | None] = mapped_column(String(32))
    # When it actually runs, as opposed to roughly how long it lasts.
    #
    # `timeline` is a slug out of a fixed list -- "1-3 months" -- which is
    # enough to say whether two organizations are talking about the same
    # order of commitment, and not enough to put in an agreement. A funder
    # reading the summary wants to know when this happened, and both parties
    # want to know when it starts; neither is answerable from "3-6 months".
    #
    # Both optional, and independently so: a partnership with a start and no
    # end is open-ended, which is a real arrangement rather than a half-filled
    # form. Ordering is enforced in app.py rather than by a check constraint,
    # so the message can name the field the person should fix.
    starts_on: Mapped[date_type | None] = mapped_column(Date)
    ends_on: Mapped[date_type | None] = mapped_column(Date)
    message: Mapped[str | None] = mapped_column(Text)
    # The recipient's note when accepting or declining.
    response_message: Mapped[str | None] = mapped_column(Text)

    # Minted on acceptance. Anyone holding it can read the summary without an
    # account, which is what makes the agreement shareable with a board or a
    # funder. Null until accepted, so a pending proposal has no public URL.
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True)

    # --- Completion --------------------------------------------------------
    # Completing is mutual, the same way accepting is. One organization
    # deciding on its own that a partnership is finished is a claim about
    # what the other one received, and this whole model is built on neither
    # side being able to make that claim alone -- a proposal needs the
    # recipient to accept, so an agreement needs both to close it. The first
    # of these to be set marks that side as done and changes nothing else;
    # the second is what moves the status to completed.
    proposer_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    recipient_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Whether each side actually provided what it committed to.
    #
    # Named for the side being judged, not the side recording it:
    # proposer_delivered is the *recipient's* answer about the proposer, and
    # vice versa. Nobody grades their own homework, which is also why these
    # can only be written by the other party.
    #
    # Private to the two organizations. It never reaches public_summary, and
    # there is no aggregate anywhere: an unverified, undisputed "they did not
    # deliver" published against a named real organization is a reputation
    # system with no appeal, which is a different and much heavier product
    # than this one. Between the two parties it is a record; published it
    # would be an accusation.
    proposer_delivered: Mapped[bool | None] = mapped_column(Boolean)
    recipient_delivered: Mapped[bool | None] = mapped_column(Boolean)

    # --- Ending ------------------------------------------------------------
    # Unilateral, unlike completing. Requiring the other side to agree before
    # you may stop would mean an organization could be held to a partnership
    # it wants out of by the other one simply not answering.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    # Shown to the other party, never on the public page. Ending is one
    # organization's account of why, given without the other one having a say
    # in how it is worded.
    end_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Messages ----------------------------------------------------------
    # How far into the thread each side has read, so "how many are waiting on
    # me" is one indexed comparison rather than a read flag per message per
    # party. Null means never opened, which is what a brand new proposal is.
    #
    # A message id, not a time. The marker is only ever compared against a
    # message -- nothing displays it, and no API returns it -- so a timestamp
    # bought nothing and cost the one thing an id cannot get wrong: it was
    # written from the app server's clock and compared against created_at,
    # which Postgres stamps from its own. A persistent offset between those
    # two machines breaks the comparison in whichever direction it leans, and
    # does it silently. Both values now come from one sequence in one
    # database.
    proposer_last_read_message_id: Mapped[int | None] = mapped_column(Integer)
    recipient_last_read_message_id: Mapped[int | None] = mapped_column(Integer)

    # Superseded by the two above and still written, so that rolling the code
    # back does not present every thread as unread. Nothing reads them.
    # Removed, with their columns, once this has settled.
    proposer_last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    recipient_last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    proposer = relationship(
        "Organization", foreign_keys=[proposer_id], lazy="joined"
    )
    recipient = relationship(
        "Organization", foreign_keys=[recipient_id], lazy="joined"
    )
    messages = relationship(
        "Message",
        back_populates="partnership",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'withdrawn', "
            "'completed', 'ended')",
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
            # contact=True: a proposal is the two of them already talking, so
            # this is the one listing where reaching the other side is the
            # whole point and neither party is a stranger who did not ask.
            return other.public_dict(contact=True)

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

    def quantities_for(self, org_id):
        """The amounts attached to what `org_id` committed to providing."""
        return dict(
            (self.proposer_quantities if self.proposer_id == org_id
             else self.recipient_quantities) or {}
        )

    def counterpart_quantities(self, org_id):
        """The amounts attached to what `org_id` gets back."""
        return dict(
            (self.recipient_quantities if self.proposer_id == org_id
             else self.proposer_quantities) or {}
        )

    @staticmethod
    def term_lines(slugs, quantities):
        """Each term as one line of display text, quantity included.

        The label alone where nothing was stated -- "Event space" -- and the
        label with the amount where something was: "Event space - 4,000 sq ft".
        Returned in place of the bare labels these used to be, so every
        surface that already renders a list of terms (the proposal card, the
        public agreement, both emails) picks up quantities without knowing
        they exist.
        """
        lines = []
        for slug in (slugs or []):
            label = label_for(slug)
            entry = (quantities or {}).get(slug) or {}
            text = format_quantity(
                entry.get("amount"), entry.get("unit"), entry.get("detail"))
            lines.append(f"{label} - {text}" if text else label)
        return lines

    @staticmethod
    def terms(slugs, quantities):
        """The same terms, structured, for anything that has to edit them."""
        out = []
        for slug in (slugs or []):
            entry = (quantities or {}).get(slug) or {}
            out.append({
                "slug": slug,
                "label": label_for(slug),
                "amount": entry.get("amount"),
                "unit": entry.get("unit"),
                "detail": entry.get("detail"),
                "text": format_quantity(
                    entry.get("amount"), entry.get("unit"), entry.get("detail")),
            })
        return out

    def receives_for(self, org_id):
        """What `org_id` gets back."""
        return list(
            (self.recipient_gives if self.proposer_id == org_id
             else self.proposer_gives) or []
        )

    def last_read_message_id_for(self, org_id):
        """The newest message `org_id` has seen, or None if it never opened."""
        return (self.proposer_last_read_message_id if self.proposer_id == org_id
                else self.recipient_last_read_message_id)

    def mark_read_through(self, org_id, message_id, now):
        """Record that `org_id` has read the thread as far as `message_id`.

        Takes `now` rather than reading the clock, so the transitional
        timestamp column and the caller's own idea of the time cannot
        disagree. It is the only thing that timestamp is still for.
        """
        if self.proposer_id == org_id:
            self.proposer_last_read_message_id = message_id
            self.proposer_last_read_at = now
        else:
            self.recipient_last_read_message_id = message_id
            self.recipient_last_read_at = now

    def messages_open(self):
        """Whether this thread still accepts new messages.

        A live proposal or a running partnership: the two states where the
        two organizations still have something to arrange. Once it is
        settled the thread stays readable and stops accepting posts --
        declining is a no, and a channel that stays open after a no is the
        unsolicited approach this model is careful about everywhere else.
        """
        return self.status in (self.PENDING, self.ACCEPTED)

    def completed_at_for(self, org_id):
        """When `org_id` marked its side complete, if it has."""
        return (self.proposer_completed_at if self.proposer_id == org_id
                else self.recipient_completed_at)

    def counterpart_completed_at(self, org_id):
        return (self.recipient_completed_at if self.proposer_id == org_id
                else self.proposer_completed_at)

    def delivered_by(self, org_id):
        """Whether `org_id` delivered, as judged by the other side."""
        return (self.proposer_delivered if self.proposer_id == org_id
                else self.recipient_delivered)

    def delivered_by_counterpart(self, org_id):
        """Whether the other side delivered, as judged by `org_id`."""
        return (self.recipient_delivered if self.proposer_id == org_id
                else self.proposer_delivered)

    def to_dict(self, viewer_id=None):
        data = {
            "id": self.id,
            "status": self.status,
            "timeline": self.timeline,
            "starts_on": self.starts_on.isoformat() if self.starts_on else None,
            "ends_on": self.ends_on.isoformat() if self.ends_on else None,
            "timeline_label": TIMELINE_LABELS.get(self.timeline),
            "message": self.message,
            "response_message": self.response_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "responded_at": (
                self.responded_at.isoformat() if self.responded_at else None
            ),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "share_token": self.share_token,
            # Same keys as before, plus `deleted`. Read through the accessors
            # rather than off self.proposer/self.recipient directly, which are
            # None once that organization has closed its account.
            "proposer": self.proposer_party(),
            "recipient": self.recipient_party(),
            "proposer_gives": list(self.proposer_gives or []),
            "proposer_gives_labels": self.term_lines(
                self.proposer_gives, self.proposer_quantities),
            "proposer_gives_terms": self.terms(
                self.proposer_gives, self.proposer_quantities),
            "recipient_gives": list(self.recipient_gives or []),
            "recipient_gives_labels": self.term_lines(
                self.recipient_gives, self.recipient_quantities),
            "recipient_gives_terms": self.terms(
                self.recipient_gives, self.recipient_quantities),
        }

        if viewer_id is not None:
            data.update({
                "direction": (
                    "outgoing" if self.proposer_id == viewer_id else "incoming"
                ),
                "counterpart": self.counterpart_dict(viewer_id),
                "you_give": self.gives_for(viewer_id),
                "you_give_labels": self.term_lines(
                    self.gives_for(viewer_id), self.quantities_for(viewer_id)),
                "you_give_terms": self.terms(
                    self.gives_for(viewer_id), self.quantities_for(viewer_id)),
                "you_receive": self.receives_for(viewer_id),
                "you_receive_labels": self.term_lines(
                    self.receives_for(viewer_id),
                    self.counterpart_quantities(viewer_id)),
                "you_receive_terms": self.terms(
                    self.receives_for(viewer_id),
                    self.counterpart_quantities(viewer_id)),
                # Only the recipient of a pending proposal can accept or
                # decline it; only the proposer can withdraw it.
                "can_respond": (
                    self.status == self.PENDING and self.recipient_id == viewer_id
                ),
                "can_withdraw": (
                    self.status == self.PENDING and self.proposer_id == viewer_id
                ),
                # The same window as withdrawing, and the same side. Editing
                # stops at acceptance: from then on this is a record of what
                # two organizations agreed to, with a public summary either
                # may already have sent somewhere, and one of them changing
                # it afterward would make it a claim rather than an
                # agreement. See update_proposal in app.py.
                "can_edit": (
                    self.status == self.PENDING and self.proposer_id == viewer_id
                ),
                # Either party may close a live agreement. Completing needs
                # both, so the button goes once this side has marked it;
                # ending needs one, so it stays until the status changes.
                "can_complete": (
                    self.status == self.ACCEPTED
                    and self.completed_at_for(viewer_id) is None
                ),
                "can_end": self.status == self.ACCEPTED,
                "you_marked_complete": (
                    self.completed_at_for(viewer_id) is not None
                ),
                "they_marked_complete": (
                    self.counterpart_completed_at(viewer_id) is not None
                ),
                # Both verdicts, to both parties. Showing one side what the
                # other recorded about it is the point of recording it --
                # a private note the subject cannot see would be a rating,
                # not a record between two organizations.
                "counterpart_delivered": self.delivered_by_counterpart(viewer_id),
                "you_delivered": self.delivered_by(viewer_id),
                "end_reason": self.end_reason,
                "messages_open": self.messages_open(),
                "ended_by_you": (
                    self.ended_by_id is not None
                    and self.ended_by_id == viewer_id
                ),
            })
        return data

    def public_summary(self):
        """The shareable agreement. No contact details, no account required."""
        return {
            "status": self.status,
            "agreed_at": self.responded_at.isoformat() if self.responded_at else None,
            # How it finished, if it has. Deliberately just the fact and the
            # date: who ended it, why, and either side's verdict on whether
            # the other delivered all stay between the two organizations.
            # This page is read by people with no account and no stake, and
            # an unanswerable claim about a named organization is not
            # something to publish on their behalf.
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "timeline": self.timeline,
            "starts_on": self.starts_on.isoformat() if self.starts_on else None,
            "ends_on": self.ends_on.isoformat() if self.ends_on else None,
            "timeline_label": TIMELINE_LABELS.get(self.timeline),
            "message": self.message,
            # The reason the row outlives its parties. A funder holding this
            # link can still read what was agreed after either organization
            # has closed its account -- which is what deleting one used to
            # take away from the other, without asking or telling them.
            "parties": [
                {
                    **self.proposer_party(),
                    "gives": self.term_lines(
                        self.proposer_gives, self.proposer_quantities),
                    "receives": self.term_lines(
                        self.recipient_gives, self.recipient_quantities),
                },
                {
                    **self.recipient_party(),
                    "gives": self.term_lines(
                        self.recipient_gives, self.recipient_quantities),
                    "receives": self.term_lines(
                        self.proposer_gives, self.proposer_quantities),
                },
            ],
        }


class Message(Base):
    """One message in the thread attached to a proposal.

    Threads hang off a partnership rather than off a pair of organizations,
    which is the whole access rule in one line: you can write to an
    organization because there is a live proposal between you, not because
    you found them in the directory. Everything else here already draws that
    line -- proposing is the sanctioned way to approach a stranger, and a
    saved lead is deliberately invisible to the organization saved, because a
    bookmark is not an approach. An open inbox would undo both.

    Before this, a proposal carried exactly one message and one reply. Two
    organizations working out what "event space" actually means had to leave
    the site and use the contact email on the card, which is also the point
    at which the agreement stops being written down anywhere.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)

    partnership_id: Mapped[int] = mapped_column(
        ForeignKey("partnerships.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL, like the partnership's own party keys: an organization
    # closing its account must not delete its half of a conversation the
    # other side is still party to. The name is snapshotted for the same
    # reason the agreement snapshots its parties -- see Partnership.
    sender_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)

    body: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    partnership = relationship("Partnership", back_populates="messages")
    sender = relationship("Organization", foreign_keys=[sender_id], lazy="joined")

    __table_args__ = (
        # Every read is "this thread, oldest first", and the unread count is
        # the same prefix with an id comparison on top. Leading on id rather
        # than created_at because that is what the comparison now sits on --
        # and because within a thread the two orderings agree.
        Index("ix_messages_partnership", "partnership_id", "id"),
    )

    def __repr__(self):
        return f"<Message {self.id} partnership={self.partnership_id}>"

    def to_dict(self, viewer_id=None):
        return {
            "id": self.id,
            "body": self.body,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            # Live name while the organization exists, snapshot once it does
            # not -- the same rule the agreement's parties follow.
            "sender_name": (self.sender.name if self.sender is not None
                            else self.sender_name),
            "sender_id": self.sender_id,
            "mine": viewer_id is not None and self.sender_id == viewer_id,
            "sender_deleted": self.sender is None,
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
    # Midnight when all_day is set. The column stays NOT NULL rather than
    # going nullable for the all-day case: every read of this table is
    # "soonest first", and a real 00:00 sorts an all-day meeting to the top of
    # its own day, which is where it belongs. A NULL would have to be given
    # that meaning by hand in every ORDER BY instead.
    time: Mapped[time_type] = mapped_column(Time, nullable=False)
    # Hours. Fractional on purpose -- a 30-minute call is 0.5.
    #
    # Optional: "we are meeting at three" is a complete thought, and requiring
    # a length meant inventing one. NULL means nobody said, which the card
    # renders as a start time with no range after it. Always NULL when
    # all_day is set -- see the check constraint below.
    duration: Mapped[float | None] = mapped_column(Float)
    # A meeting filed under a date with no time of day.
    all_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # The IANA zone the date and time above are written in -- "3pm" is not a
    # moment until something says where.
    #
    # This pair is stored as wall-clock time plus a zone, never as a UTC
    # instant. Converting at write and back at read looks equivalent and is
    # not, for anything in the future: the offset a zone will have on a date
    # months away is a prediction, and when a government moves a DST boundary
    # -- or the meeting is simply on the far side of one -- the stored instant
    # keeps the old offset and the meeting silently moves an hour. "Three
    # o'clock in Austin" has to stay three o'clock in Austin, so the wall
    # clock is the thing recorded and the instant is derived when needed.
    #
    # Nullable, and null on every row written before this column existed.
    # There is no honest backfill: nothing recorded where those meetings were
    # entered, and picking a default would be inventing an answer for someone
    # else's diary. Null reads as "no zone recorded" and the frontend falls
    # back to the viewer's own, which is exactly what those rows have always
    # meant.
    timezone: Mapped[str | None] = mapped_column(String(64))

    # --- Repeating ---------------------------------------------------------
    # A standing meeting is one row, not fifty.
    #
    # The row stores the *first* occurrence -- date and time above are the
    # series start -- and the rest are worked out when the calendar is read.
    # Writing them out as rows would mean choosing how far into the future to
    # write, rewriting the tail every time the series is edited, and leaving
    # whatever was already written behind when it is not.
    #
    # Editing is series-only, deliberately. There is no per-occurrence
    # exception here: changing a repeating meeting changes all of it, and
    # deleting it deletes all of it. Exceptions need somewhere to record "this
    # one is different", which is a second table and a much larger idea about
    # what a meeting is; a standing partner check-in is the thing this is for,
    # and moving one week of it is rare enough to be worth doing by ending the
    # series and starting another.
    #
    # NULL means it happens once, which is what every row written before this
    # column existed means and what most rows will always mean.
    REPEAT_RULES = ("weekly", "biweekly", "monthly")

    repeat: Mapped[str | None] = mapped_column(String(16))
    # The last date the series may land on. Required whenever `repeat` is set
    # -- see the check constraint below -- because an unbounded series is one
    # every read has to invent a horizon for, and a horizon invented at read
    # time is a different answer to the same question depending on who asks.
    repeat_until: Mapped[date_type | None] = mapped_column(Date)

    partner_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # NULL passes: a CHECK only fails on FALSE, and "no length given" is
        # exactly what NULL is here.
        CheckConstraint("duration > 0", name="ck_events_duration_positive"),
        # An all-day meeting has no length to state, so the two cannot both be
        # set. Enforced here rather than left to the route: a length that only
        # some code paths clear is a length that eventually gets rendered.
        CheckConstraint(
            "NOT (all_day AND duration IS NOT NULL)",
            name="ck_events_all_day_has_no_duration",
        ),
        # A repeat rule this code knows how to expand, or none at all. A value
        # outside the list would read as a one-off in one place and raise in
        # another, which is the kind of disagreement a constraint exists to
        # make impossible.
        CheckConstraint(
            "repeat IS NULL OR repeat IN ('weekly', 'biweekly', 'monthly')",
            name="ck_events_repeat_rule",
        ),
        # The two halves of a series travel together: a rule with no end is
        # unbounded, and an end date with no rule describes nothing.
        CheckConstraint(
            "(repeat IS NULL) = (repeat_until IS NULL)",
            name="ck_events_repeat_needs_until",
        ),
        # A series that ends before it starts has no occurrences at all, which
        # is a form somebody filled in wrong rather than a meeting.
        CheckConstraint(
            "repeat_until IS NULL OR repeat_until >= date",
            name="ck_events_repeat_until_after_start",
        ),
        # Every read is "this org's meetings, soonest first".
        Index("ix_events_organization_date", "organization_id", "date", "time"),
    )

    def __repr__(self):
        return f"<Event {self.id} org={self.organization_id} {self.date} {self.title!r}>"

    def occurrences(self, until, since=None):
        """Every date this meeting lands on, earliest first.

        One date for a one-off. For a series, the start and then each repeat
        up to the earlier of repeat_until and `until` -- the caller's horizon,
        which is what stops a five-year weekly series from being expanded in
        full to draw a card showing the next three.

        `since` drops occurrences before a floor, and exists because a weekly
        meeting that has been running since January is not a hundred cards
        worth of history -- it is one standing meeting, and what a calendar
        is being asked is when it happens next. Deliberately not applied to a
        one-off: a meeting last Tuesday still appears on the dashboard,
        dimmed, exactly as it always has, and a floor that silently removed
        it would be this change quietly deleting something.

        Monthly skips a month that has no such day rather than clamping to
        the last one: the 31st of February is not the 28th, and a meeting
        that silently moves is worse than one that does not happen. That is
        also what FREQ=MONTHLY;BYMONTHDAY=31 does in the RRULE this exports
        as, so a calendar app subscribing to it agrees with the dashboard.
        """
        if not self.repeat:
            return [self.date]

        last = min(self.repeat_until, until) if until else self.repeat_until
        if last is None or last < self.date:
            return [self.date] if not until or self.date <= until else []

        def keep(at):
            return since is None or at >= since

        dates = []
        if self.repeat in ("weekly", "biweekly"):
            step = timedelta(days=7 if self.repeat == "weekly" else 14)
            at = self.date
            while at <= last:
                if keep(at):
                    dates.append(at)
                at += step
            return dates

        # Monthly, on the same day number.
        day = self.date.day
        year, month = self.date.year, self.date.month
        while True:
            try:
                at = date_type(year, month, day)
            except ValueError:
                at = None          # no such day this month -- skip it
            if at is not None:
                if at > last:
                    break
                if keep(at):
                    dates.append(at)
            # Advance regardless, or a skipped February ends the series.
            month += 1
            if month > 12:
                month, year = 1, year + 1
            # The skip case has no date to compare against `last`, so the
            # loop needs its own stop: once the first of the month is past
            # the horizon, nothing later in it can be inside it.
            if date_type(year, month, 1) > last:
                break
        return dates

    def to_dict(self, on=None):
        """The shape ppdashboard.js already renders.

        date and time are formatted as the browser's own `YYYY-MM-DD` and
        `HH:MM`, which is what the date/time inputs produce and what the
        rendering code splits on -- isoformat() would append seconds to the
        time and quietly break `time.split(':')`.

        `on` overrides the date, for one occurrence of a repeating meeting.
        Everything else about an occurrence is the series -- including `id`,
        which is the series' id and is what the edit and delete controls send.
        That is not an oversight: editing is series-only (see REPEAT_RULES
        above), so the only thing those controls could act on is the series.
        """
        when = on or self.date
        return {
            "id": self.id,
            "title": self.title,
            "date": when.strftime("%Y-%m-%d"),
            "time": self.time.strftime("%H:%M"),
            # What the series is, so the card can say "every week" and the
            # edit form can open holding the rule it already has.
            "repeat": self.repeat,
            "repeat_until": (self.repeat_until.strftime("%Y-%m-%d")
                             if self.repeat_until else None),
            # The first occurrence, which is the row's own date. The card
            # uses it to mark the one that is the start of the series rather
            # than one of its repeats.
            "starts_on": self.date.strftime("%Y-%m-%d"),
            # null rather than a stand-in: the dashboard draws a start time
            # with no range after it when nobody said how long, and it can
            # only tell the difference if the absence survives the trip.
            "duration": self.duration,
            "all_day": self.all_day,
            # null for a meeting saved before zones were recorded. The
            # dashboard reads that as "the viewer's own zone", which is the
            # assumption those rows were written under.
            "timezone": self.timezone,
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


class ContactMessage(Base):
    """A message from the homepage form.

    These were delivered by email and not kept. That reads as a reasonable
    decision -- there is no inbox in this schema and no admin view to read one
    from, so a table would only move them somewhere nobody looks -- and it is
    wrong in the one case that matters: outbound mail does not leave this app
    until a sending domain is verified, so every message anybody has sent
    through that form has gone nowhere at all, silently, and the sender was
    told it worked.

    So they are written down first and mailed second. Mail stays the way a
    person actually finds out; this is the copy that survives the provider
    being misconfigured, rate limited, or simply off.

    Deliberately no IP address. The rest of this schema does not record who
    somebody is unless it has to -- profile views are a salted digest for
    exactly that reason -- and the honeypot and the per-connection limit on
    /api/contact already do the abuse work an address would be kept for.
    """

    __tablename__ = "contact_messages"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Widths match what the endpoint already enforces, so a value that passed
    # validation cannot fail on the way into the column.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # When somebody dealt with it. Null is the queue; a timestamp is the
    # record. A boolean would answer "is it done" and lose "when", which is
    # the question anybody looking at an old message actually has.
    handled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    __table_args__ = (
        # The only read that matters: the unhandled ones, oldest first,
        # because a support queue is worked from the front.
        Index("ix_contact_messages_queue", "handled_at", "created_at"),
    )

    def __repr__(self):
        return f"<ContactMessage {self.id} from {self.email!r}>"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "message": self.message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "handled_at": self.handled_at.isoformat() if self.handled_at else None,
        }


class Admin(Base):
    """Somebody who operates this site, which is not the same as somebody who
    uses it.

    A separate table rather than a flag on Organization, and the difference is
    not tidiness. An account here *is* an organization -- the row a stranger
    creates by filling in a signup form -- so a privilege bit living in that
    table would sit in the same rows every registration writes to, and any bug
    in any path that updates an organization becomes a potential escalation.
    Nothing in `organizations` can make somebody an admin, because the answer
    is not stored there.

    There is no signup route for this table and there never will be. Rows come
    from `python manage.py create-admin`, which is a thing you run on a machine
    that already has the database credentials -- which is the point: the set of
    people who can create an admin is exactly the set who could edit the table
    by hand anyway.

    The session carries admin_id beside org_id rather than instead of it, so
    being an admin does not sign you out of your own organization and doing
    admin work does not mean losing your place.
    """

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Lower-cased on the way in, like Organization.email, so signing in is not
    # case-sensitive. Unique, but note it is a *different* namespace: the same
    # address may be an organization and an admin, and those are two accounts
    # with two passwords, not one account with two hats.
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # The same revocation mechanism organizations have, for the same reason:
    # changing the password has to end the sessions opened under the old one,
    # and a privileged session is the one where that matters most.
    session_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self):
        return f"<Admin {self.id} {self.email!r}>"

    def to_dict(self):
        """Never includes the hash, and there is nothing else worth hiding."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "last_seen_at": (self.last_seen_at.isoformat()
                             if self.last_seen_at else None),
        }


class AdminAction(Base):
    """What an admin did, and when.

    Both powers this records are reversible -- clearing a name flag, hiding
    and unhiding an organization -- so this is not an undo log. It is the
    answer to "who did that", which is a question with no answer at all
    otherwise, and which becomes a real one the moment there is more than one
    admin or more than a few weeks between the act and the asking.

    admin_id is SET NULL rather than CASCADE, and admin_email is a snapshot
    beside it: removing an admin must not quietly erase the record of what
    they did, and a null id with no name attached would be a record of
    nothing.
    """

    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(primary_key=True)

    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    admin_email: Mapped[str] = mapped_column(String(255), nullable=False)

    # A short verb: "hide_organization", "clear_name_flag". Free text rather
    # than an enum because a check constraint here would mean a migration
    # every time a power is added, and the value is written by this codebase
    # rather than by anything a caller controls.
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer)

    # Whatever the action needs to be understood later -- the reason given for
    # hiding, the name that was flagged. Not a foreign key to anything: the
    # point of a log entry is that it still reads after the row it describes
    # has changed underneath it.
    detail: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_admin_actions_recent", "created_at"),
    )

    def __repr__(self):
        return f"<AdminAction {self.action} by {self.admin_email!r}>"

    def to_dict(self):
        return {
            "id": self.id,
            "admin_email": self.admin_email,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "detail": dict(self.detail or {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RateLimitAttempt(Base):
    """One recorded attempt against one rate-limit bucket.

    The limits used to live in a dict in the web process. gunicorn runs two
    workers (see render.yaml), so every limit was really up to twice what it
    said, and which answer you got depended on which worker the proxy picked
    -- a login lockout that holds on one connection and not the next is not a
    lockout. A restart cleared them all, and the free plan spins down when
    idle, so waiting out a spin-down refunded an attacker's whole budget.

    None of that is fixable in process memory, because the thing being
    counted happens in more than one process. The counter has to live where
    both workers can see it, and the only such place this app already has is
    Postgres.

    Rows are disposable. Nothing reads them but the limiter, they carry no
    history worth keeping, and they are deleted as they age out -- both for
    the key being asked about, on every call, and across the table on a
    timer. See _sweep_rate_limits in app.py.

    `key` is whatever the bucket is keyed by: an IP address, an email
    address, or an organization id as a string. Deliberately untyped here --
    what a bucket counts is the caller's business, and a column that tried to
    know would need a migration every time a limit was added.
    """

    __tablename__ = "rate_limit_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)

    bucket: Mapped[str] = mapped_column(String(64), nullable=False)
    # Long enough for an email address, which is the longest thing any
    # current bucket keys by.
    key: Mapped[str] = mapped_column(String(255), nullable=False)

    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Every read is "this bucket, this key, since this moment", and the
        # deletes are the same prefix. One index covers all of them.
        Index("ix_rate_limit_lookup", "bucket", "key", "attempted_at"),
        # The global sweep asks only about age, across every bucket at once.
        Index("ix_rate_limit_sweep", "attempted_at"),
    )

    def __repr__(self):
        return f"<RateLimitAttempt {self.bucket}:{self.key}>"


class EmailOutbox(Base):
    """A message to be delivered, written down before anything tries to send it.

    Delivery used to be an in-memory queue drained by two threads, with an
    atexit hook to finish what was in flight. That covers a clean shutdown
    and nothing else: atexit does not run on SIGKILL, on an out-of-memory
    kill, or on a container torn down past its grace window, and a full queue
    dropped the message to a log line. Everything queued at that moment was
    simply gone, with no record that it had ever existed.

    For a partnership notification that is a missed email. For a verification
    link or a password reset it is an account somebody cannot get into -- and
    because sending is deliberately off the request path, they were shown a
    success either way, so nobody found out. That is the failure this table
    exists to make impossible.

    The row is now the queue. A worker claims one, sends it, and marks the
    outcome; a claim that goes stale because the process holding it died is
    released and taken by somebody else. Which means a message survives the
    process that accepted it, and either worker can deliver what the other
    one queued.

    Bodies are stored in full. They are already built by the time this is
    written, they are small, and a retry that had to reconstruct one would
    need the world as it was when the message was composed -- which is
    exactly what is no longer available after a restart.
    """

    __tablename__ = "email_outbox"

    #: Waiting for a worker, or waiting for `next_attempt_at` to arrive.
    QUEUED = "queued"
    #: Claimed by a worker. Released back to QUEUED if the claim goes stale.
    SENDING = "sending"
    DELIVERED = "delivered"
    #: Given up on -- either definitively refused, or out of attempts.
    FAILED = "failed"

    STATUSES = (QUEUED, SENDING, DELIVERED, FAILED)

    id: Mapped[int] = mapped_column(primary_key=True)

    to_addr: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{QUEUED}'")
    )

    # How many times a worker has picked this up. Bounded by
    # MAX_DELIVERY_ROUNDS in notifications.py, so a message that cannot be
    # delivered stops rather than being retried forever.
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    # When this becomes eligible again. Set into the future after a
    # retryable failure, which is what turns "try three times over ten
    # seconds" into a backoff that can span a provider outage.
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # When the current claim was taken, so a claim held by a process that has
    # since died can be recognized as stale and released.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # The last thing that went wrong, kept on the row rather than only in the
    # logs: "did that reset email actually go out" is a question somebody
    # asks about one address, and grepping a log for it is not an answer.
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'sending', 'delivered', 'failed')",
            name="ck_email_outbox_status",
        ),
        # What the claim query asks: the oldest queued row whose time has
        # come. Partial, because delivered rows are the ones that accumulate
        # and none of them are ever claimed again.
        Index(
            "ix_email_outbox_claimable", "next_attempt_at", "id",
            postgresql_where=text("status = 'queued'"),
        ),
        # Releasing stale claims asks the same question of the other status.
        Index(
            "ix_email_outbox_claimed", "claimed_at",
            postgresql_where=text("status = 'sending'"),
        ),
    )

    def __repr__(self):
        return f"<EmailOutbox {self.id} {self.status} to={self.to_addr!r}>"
