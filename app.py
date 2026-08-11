import logging
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt

# Flask leaves the root logger at WARNING, which hides notifications.py's INFO
# lines. Every send would happen silently, including the dry-run fallback that
# is the whole point of running without an API key.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
from flask import (
    Flask, jsonify, request, session, send_from_directory
)

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix

from categories import (
    CATEGORY_GROUPS, ORGANIZATION_TYPES, TIMELINE_OPTIONS, VALID_TIMELINES,
    clean_categories,
)
from db import SessionLocal
from links import LinkError, parse_links
from matching import find_matches, score_pair
from models import Organization, Partnership
from notifications import (
    notify_email_verification, notify_proposal_created, notify_proposal_responded,
)

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")

# The frontend is served by Flask itself. That makes the API same-origin, which
# removes the CORS setup and the hardcoded localhost API base, and is what lets
# the session cookie work without SameSite gymnastics.
#
# static_folder MUST stay pointed at static/ and never at the project root.
# Flask serves everything under static_folder verbatim, so rooting it here
# would publish .env, app.py and the rest of the source at the top level --
# GET /.env would hand out DATABASE_URL and SECRET_KEY to anyone asking.
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

# Render terminates TLS and proxies to this app, so request.remote_addr is
# Render's edge, not the visitor, unless this rewrites it from X-Forwarded-For.
# The per-IP rate limits below (and any future ones) are meaningless without
# it -- every request would appear to come from the same address. x_for=1
# trusts exactly one proxy hop, matching Render's setup; a value too high
# would let a client forge its own IP by sending its own X-Forwarded-For.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

# Sessions are signed with this key. A generated fallback keeps local
# development working, but it changes on every restart -- so every session is
# invalidated whenever the server reloads. Set SECRET_KEY in .env (and in the
# host's environment when deployed) to avoid that.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
if not os.environ.get("SECRET_KEY"):
    app.logger.warning(
        "SECRET_KEY is not set; using a random key. Sessions will not survive "
        "a restart. Set SECRET_KEY in .env."
    )

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,   # JavaScript cannot read the cookie
    SESSION_COOKIE_SAMESITE="Lax",  # not sent on cross-site POSTs
    # Only send the cookie over HTTPS in production. Left off locally because
    # the dev server is plain HTTP and the cookie would never be set.
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
)

# bcrypt refuses passwords longer than this; hashing silently truncated them in
# older versions, so the limit is enforced explicitly rather than surfacing as
# a 500 for whoever picks a very long passphrase.
MAX_PASSWORD_BYTES = 72

# --- Signup validation --------------------------------------------------
# Deliberately not a full RFC 5322 pattern -- those accept addresses no mail
# server actually does and reject ones people really use. This catches what
# matters for a signup form: something, an @, something, a dot, something.
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

MIN_PASSWORD_LENGTH = 10
_SPECIAL_CHARS = set("!@#$%^&*()_+-=[]{}|;:,.<>?/~`\"'\\")

# Checked case-insensitively, exactly as leaked. Not comprehensive -- the
# point is to catch the handful of passwords bots and lazy signups reach for
# first, not to replace a real breach-corpus check like haveibeenpwned, which
# would mean a network call in the request path for a nonprofit tool that does
# not need that overhead.
COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "12345678", "123456789",
    "1234567890", "qwerty123", "qwertyuiop", "letmein123", "welcome123",
    "abc123456", "iloveyou1", "admin1234", "trustno1a", "sunshine1",
    "princess1", "football1", "baseball1", "dragon123", "monkey123",
    "superman1", "michael123", "shadow123", "master123", "starwars1",
    "whatever1", "freedom123", "passw0rd1", "changeme1", "partnerportal",
})

# An exact match against COMMON_PASSWORDS alone is trivial to dodge: appending
# "!" or "1" to "password" satisfies every structural rule above (length,
# case, digit, special character) while remaining exactly as guessable. This
# strips trailing digits/punctuation -- the overwhelming pattern in how people
# adapt a weak base word to a length or complexity rule -- and checks what is
# left against a short list of common bases, independent of the exact-string
# list above.
_TRAILING_NOISE_RE = re.compile(r"[^a-zA-Z]+$")
COMMON_PASSWORD_STEMS = frozenset({
    "password", "passw0rd", "qwerty", "qwertyuiop", "letmein", "welcome",
    "admin", "iloveyou", "trustno", "sunshine", "princess", "football",
    "baseball", "dragon", "monkey", "superman", "michael", "shadow",
    "master", "starwars", "whatever", "freedom", "changeme", "partnerportal",
    "abc",
})


def _password_stem(password):
    return _TRAILING_NOISE_RE.sub("", password).lower()


# A handful of well-known disposable/temporary-inbox providers. Not
# exhaustive -- new ones appear constantly, and a determined spammer can
# always run their own domain. This stops the common case: a bot or a bulk
# signup script working down a list of throwaway-mail generators.
DISPOSABLE_EMAIL_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "guerrillamail.info",
    "10minutemail.com", "10minutemail.net", "tempmail.com", "temp-mail.org",
    "throwawaymail.com", "yopmail.com", "trashmail.com", "getnada.com",
    "fakeinbox.com", "dispostable.com", "sharklasers.com", "maildrop.cc",
    "mintemail.com", "mohmal.com", "tempinbox.com", "moakt.com",
    "mailnesia.com", "spamgourmet.com", "mytemp.email", "emailondeck.com",
    "burnermail.io", "discard.email", "tempr.email",
})


def is_valid_email(email):
    return bool(EMAIL_RE.match(email))


def password_problem(password, *, email="", name=""):
    """None if the password is acceptable, otherwise why it was rejected.

    Mirrors the checklist pplogin.js shows while typing -- same five rules,
    same order -- so the message someone sees here is never a surprise given
    what the page already told them.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return "Password is too long (72 bytes maximum)."
    if not any(c.islower() for c in password):
        return "Password must include a lowercase letter."
    if not any(c.isupper() for c in password):
        return "Password must include an uppercase letter."
    if not any(c.isdigit() for c in password):
        return "Password must include a number."
    if not any(c in _SPECIAL_CHARS for c in password):
        return "Password must include a special character (e.g. ! @ # $ %)."

    lowered = password.lower()
    stem = _password_stem(password)
    if lowered in COMMON_PASSWORDS or stem in COMMON_PASSWORD_STEMS:
        return "That password is too common. Please choose another."
    # Cheap check against reusing the account's own email or org name as the
    # password -- not a breach-list lookup, just closing the most obvious gap.
    local_part = email.split("@", 1)[0].lower()
    if local_part and local_part in lowered:
        return "Password should not contain your email address."
    if name and len(name) >= 3 and name.lower() in lowered:
        return "Password should not contain your organization name."
    return None


# --- Rate limiting --------------------------------------------------------
# In-process and per-worker: gunicorn runs this app with 2 workers (see
# render.yaml), so the real ceiling on any of these limits is up to 2x what
# is configured here, and a restart clears it entirely. That is a real gap
# for a determined attacker, but it is a large improvement over no limit at
# all for the actual threat here -- a script hammering /register -- and
# adding Redis or another store for a nonprofit tool at this scale is not
# worth the operational cost it would add.
_rate_buckets = defaultdict(list)


def rate_limited(bucket, key, max_attempts, window_seconds):
    """True (and records nothing further) if `key` has hit the limit in
    `bucket` within the last `window_seconds`; otherwise records this attempt
    and returns False.
    """
    now = time.time()
    attempts = _rate_buckets[(bucket, key)]
    cutoff = now - window_seconds
    while attempts and attempts[0] < cutoff:
        attempts.pop(0)
    if len(attempts) >= max_attempts:
        return True
    attempts.append(now)
    return False


def client_ip():
    # request.remote_addr, corrected for Render's proxy by ProxyFix above.
    return request.remote_addr or "unknown"


# --- Plumbing ---------------------------------------------------------------
def get_db():
    """A session per request, closed when the request ends."""
    return SessionLocal()


def current_org(db):
    """The signed-in organization, or None."""
    org_id = session.get("org_id")
    if not org_id:
        return None
    return db.get(Organization, org_id)


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        db = get_db()
        try:
            org = current_org(db)
            if org is None:
                # Clear a cookie pointing at a deleted row so the client is
                # not stuck in a logged-in-but-broken state.
                session.clear()
                return jsonify({"error": "Please log in."}), 401
            return view(org, db, *args, **kwargs)
        finally:
            db.close()
    return wrapper


# --- Static frontend --------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# --- Reference data ---------------------------------------------------------
@app.route("/api/categories", methods=["GET"])
def get_categories():
    """Drives the onboarding form so the vocabulary lives in one place."""
    return jsonify({
        "groups": [
            {"name": name, "categories": [
                {"slug": slug, "label": label} for slug, label in entries
            ]}
            for name, entries in CATEGORY_GROUPS
        ],
        "organization_types": ORGANIZATION_TYPES,
        "timelines": [
            {"slug": slug, "label": label} for slug, label in TIMELINE_OPTIONS
        ],
    })


# --- Auth -------------------------------------------------------------------
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    # Honeypot: a field named to look worth filling in to a bot's form-filler,
    # hidden from real visitors with CSS rather than `type="hidden"` -- some
    # bots skip inputs that are hidden the obvious way. Genuine submissions
    # never touch it, so any value here means a script filled every field it
    # could find. Rather than reject outright and teach the bot what tripped
    # it, this returns the same shape a real success does, without writing
    # anything -- from the caller's side, the attempt "worked".
    if (data.get("website") or "").strip():
        return jsonify({
            "message": "Account created",
            "organization": {"onboarding_complete": False},
        }), 201

    if rate_limited("register", client_ip(), max_attempts=5, window_seconds=3600):
        return jsonify({
            "error": "Too many accounts created from this connection recently. "
                     "Please try again in a while.",
        }), 429

    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are all required."}), 400
    if not is_valid_email(email):
        return jsonify({"error": "Please enter a valid email address."}), 400
    domain = email.rsplit("@", 1)[-1]
    if domain in DISPOSABLE_EMAIL_DOMAINS:
        return jsonify({
            "error": "Please use a permanent email address -- that one looks "
                     "like a temporary inbox provider.",
        }), 400

    problem = password_problem(password, email=email, name=name)
    if problem:
        return jsonify({"error": problem}), 400

    db = get_db()
    try:
        existing = db.query(Organization).filter(
            Organization.email == email
        ).one_or_none()
        if existing is not None:
            return jsonify({"error": "That email is already registered."}), 409

        org = Organization(
            email=email,
            name=name,
            password_hash=bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8"),
            email_verify_token=secrets.token_urlsafe(32),
            email_verify_sent_at=datetime.now(timezone.utc),
        )
        db.add(org)
        db.commit()

        notify_email_verification(org, org.email_verify_token)

        # Registering signs you in -- otherwise the next step is a pointless
        # trip back through the login form. Verification is informational
        # only right now: nothing here or downstream checks email_verified.
        session.clear()
        session["org_id"] = org.id
        session.permanent = True
        return jsonify({
            "message": "Account created",
            "organization": org.private_dict(),
        }), 201
    finally:
        db.close()


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400
    if not is_valid_email(email):
        # A format check, not an existence check -- it runs before touching
        # the database, so it gives no information a syntax check does not
        # already give away.
        return jsonify({"error": "Please enter a valid email address."}), 400

    # Generous on purpose: office and library connections share one IP across
    # many people, and a mistyped password is normal, not an attack. This
    # blunts a script trying passwords in a loop without punishing a shared
    # connection for one person fumbling their own login a few times.
    if rate_limited("login", client_ip(), max_attempts=20, window_seconds=900):
        return jsonify({
            "error": "Too many attempts from this connection. Please wait a "
                     "few minutes and try again.",
        }), 429

    db = get_db()
    try:
        org = db.query(Organization).filter(
            Organization.email == email
        ).one_or_none()

        # Same response whether the email is unknown or the password is wrong,
        # so this endpoint cannot be used to enumerate registered orgs.
        invalid = jsonify({"error": "Invalid email or password."}), 401
        if org is None or not org.password_hash:
            return invalid
        if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
            return invalid
        if not bcrypt.checkpw(
            password.encode("utf-8"), org.password_hash.encode("utf-8")
        ):
            return invalid

        session.clear()
        session["org_id"] = org.id
        session.permanent = True
        return jsonify({
            "message": "Signed in",
            "organization": org.private_dict(),
        }), 200
    finally:
        db.close()


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Signed out"}), 200


# How long a verification link stays valid. Generous, since there is no
# resend flow yet -- letting a link sit unread over a weekend still work
# matters more than a tight expiry would, given the only recovery from an
# expired one right now is registering again.
EMAIL_VERIFY_TOKEN_LIFETIME = timedelta(days=7)


@app.route("/api/verify-email", methods=["GET"])
def verify_email():
    """The link in notify_email_verification. Deliberately unauthenticated,
    like /api/partnerships/<token> -- the token itself is the credential, and
    requiring a session too would break the link for whoever reads their
    email on a different device than the one they signed up on.
    """
    token = (request.args.get("token") or "").strip()
    if not token:
        return jsonify({"error": "This link is missing its token."}), 400

    db = get_db()
    try:
        org = db.query(Organization).filter(
            Organization.email_verify_token == token
        ).one_or_none()

        if org is None:
            # Covers both "never existed" and "already used" -- the token is
            # cleared on success, so a second click lands here too. Handled
            # as its own case below when the row is still findable by some
            # other match; here it genuinely is not.
            return jsonify({
                "error": "This verification link is invalid or has already "
                         "been used.",
            }), 404

        if org.email_verify_sent_at and (
            datetime.now(timezone.utc) - org.email_verify_sent_at
            > EMAIL_VERIFY_TOKEN_LIFETIME
        ):
            return jsonify({
                "error": "This verification link has expired. Verifying is "
                         "optional and does not limit your account, so you "
                         "can keep using PartnerPortal as normal.",
            }), 410

        org.email_verified = True
        org.email_verify_token = None
        db.commit()
        return jsonify({
            "message": "Email verified",
            "organization": {"name": org.name},
        }), 200
    finally:
        db.close()


@app.route("/api/me", methods=["GET"])
@login_required
def get_me(org, db):
    return jsonify({"organization": org.private_dict()})


# --- Onboarding -------------------------------------------------------------
@app.route("/api/onboarding", methods=["POST"])
@login_required
def save_onboarding(org, db):
    """Fill in the matchable half of the signed-in org's profile.

    This updates the caller's own row rather than inserting a new one, which is
    what makes an onboarded org actually appear in other orgs' matches.
    """
    data = request.get_json(silent=True) or {}

    name = (data.get("organization_name") or "").strip()
    organization_type = (data.get("organization_type") or "").strip()
    location = (data.get("location") or "").strip()
    needs = clean_categories(data.get("needs"))
    offers = clean_categories(data.get("offers"))

    # Mirrors the minimums the onboarding form enforces. A single character
    # passes a presence check while telling a prospective partner nothing, and
    # the client is not the only way into this endpoint.
    problems = []
    if len(name) < 2:
        problems.append("a full organization name")
    if not organization_type:
        problems.append("an organization type")
    if len(location) < 2:
        problems.append("a location")
    if not needs:
        problems.append("at least one thing you need")
    if not offers:
        problems.append("at least one thing you can offer")

    description = (data.get("description") or "").strip()
    if description and len(description) < 20:
        problems.append("a longer description, or none at all")

    if problems:
        return jsonify({"error": "Please provide " + ", ".join(problems) + "."}), 400

    # All four are optional; parse_links returns None for anything left blank.
    # Errors name the field so the form can point at the right input rather
    # than dropping a generic message at the top of the page.
    try:
        links = parse_links(data)
    except LinkError as e:
        return jsonify({"error": str(e), "field": e.field}), 400

    org.name = name
    org.organization_type = organization_type
    org.location = location
    org.remote_friendly = bool(data.get("remote_friendly"))
    org.needs = needs
    org.offers = offers
    org.needs_note = (data.get("needs_note") or "").strip() or None
    org.offers_note = (data.get("offers_note") or "").strip() or None
    org.partnership_goals = (data.get("partnership_goals") or "").strip() or None
    org.description = description or None
    org.contact_email = (data.get("contact_email") or "").strip() or org.email
    org.contact_phone = (data.get("contact_phone") or "").strip() or None
    org.website_url = links["website_url"]
    org.instagram_url = links["instagram_url"]
    org.x_url = links["x_url"]
    org.linkedin_url = links["linkedin_url"]
    org.onboarding_complete = True

    db.commit()
    return jsonify({
        "message": "Profile saved",
        "organization": org.private_dict(),
    }), 200


# --- Matching ---------------------------------------------------------------
@app.route("/api/matches", methods=["GET"])
@login_required
def get_matches(org, db):
    if not org.onboarding_complete:
        return jsonify({
            "error": "Complete your profile first.",
            "needs_onboarding": True,
        }), 409

    mutual_only = request.args.get("mutual") == "1"
    matches = find_matches(db, org, mutual_only=mutual_only)

    # While the real directory is small a new org can have no real matches at
    # all. Rather than show an empty page, surface the seeded examples --
    # clearly flagged as examples by the client -- so there is something to
    # look at. They are never mixed into `matches`.
    examples = []
    if not matches:
        examples = find_matches(db, org, mutual_only=mutual_only, demo_only=True)

    return jsonify({
        "matches": matches,
        "count": len(matches),
        "mutual_count": sum(1 for m in matches if m["match_detail"]["mutual"]),
        "examples": examples,
        "example_count": len(examples),
    })


@app.route("/api/organizations/<int:org_id>", methods=["GET"])
@login_required
def get_organization(org, db, org_id):
    other = db.get(Organization, org_id)
    if other is None or not other.onboarding_complete:
        return jsonify({"error": "Organization not found."}), 404

    data = other.public_dict()
    if other.id != org.id:
        score, reasons, detail = score_pair(org, other)
        data.update({
            "match_score": score, "reasons": reasons, "match_detail": detail,
        })
    return jsonify({"organization": data})


@app.route("/api/organizations/<int:org_id>/public", methods=["GET"])
def public_organization(org_id):
    """An organization's public profile. Deliberately unauthenticated.

    So an org can be linked to from an email, a grant application or its own
    website without the reader needing an account. public_profile() is used
    rather than public_dict() because this is served to anyone: see the note
    there about contact details.

    Only completed profiles resolve, matching the signed-in route -- a
    half-filled row says nothing useful and should not have a public URL.
    """
    db = get_db()
    try:
        other = db.get(Organization, org_id)
        if other is None or not other.onboarding_complete:
            return jsonify({"error": "Organization not found."}), 404
        return jsonify({"organization": other.public_profile()})
    finally:
        db.close()


# --- Dashboard --------------------------------------------------------------
@app.route("/api/dashboard", methods=["GET"])
@login_required
def get_dashboard(org, db):
    """Real numbers for the dashboard, replacing the hardcoded placeholders."""
    if not org.onboarding_complete:
        return jsonify({
            "organization": org.private_dict(),
            "needs_onboarding": True,
            "stats": {
                "total_matches": 0, "mutual_matches": 0,
                "needs_count": 0, "offers_count": 0,
            },
            "top_matches": [],
        })

    matches = find_matches(db, org)
    mutual = [m for m in matches if m["match_detail"]["mutual"]]

    rows = db.query(Partnership).filter(
        or_(Partnership.proposer_id == org.id,
            Partnership.recipient_id == org.id)
    ).order_by(Partnership.created_at.desc()).all()
    proposals = [p.to_dict(viewer_id=org.id) for p in rows]

    return jsonify({
        "organization": org.private_dict(),
        "needs_onboarding": False,
        "stats": {
            "total_matches": len(matches),
            "mutual_matches": len(mutual),
            "needs_count": len(org.needs or []),
            "offers_count": len(org.offers or []),
            "awaiting_you": sum(
                1 for p in proposals
                if p["direction"] == "incoming" and p["status"] == "pending"
            ),
            "sent_pending": sum(
                1 for p in proposals
                if p["direction"] == "outgoing" and p["status"] == "pending"
            ),
            "agreed": sum(1 for p in proposals if p["status"] == "accepted"),
        },
        "top_matches": matches[:5],
        "recent_proposals": proposals[:5],
    })


# --- Partnership proposals --------------------------------------------------
@app.route("/api/proposals", methods=["POST"])
@login_required
def create_proposal(org, db):
    """Propose a partnership with structured terms on both sides."""
    if not org.onboarding_complete:
        return jsonify({"error": "Complete your profile first."}), 409

    data = request.get_json(silent=True) or {}

    try:
        recipient_id = int(data.get("recipient_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Which organization is this for?"}), 400

    if recipient_id == org.id:
        return jsonify({"error": "You cannot propose a partnership with yourself."}), 400

    recipient = db.get(Organization, recipient_id)
    if recipient is None or not recipient.onboarding_complete:
        return jsonify({"error": "Organization not found."}), 404
    if recipient.is_demo:
        # Example organizations have no owner and cannot accept or decline, so
        # a proposal to one would sit pending forever.
        return jsonify({
            "error": "This is an example organization, shown to illustrate how "
                     "matching works. You can only propose to real organizations."
        }), 400

    proposer_gives = clean_categories(data.get("proposer_gives"))
    recipient_gives = clean_categories(data.get("recipient_gives"))

    # Both sides must bring something. A proposal where one side gives nothing
    # is a request for a favour, and the whole premise here is the two-way
    # exchange -- so it is rejected rather than quietly stored as a partnership.
    if not proposer_gives or not recipient_gives:
        return jsonify({
            "error": "A partnership needs something from both sides. "
                     "Pick at least one thing you will provide and one thing "
                     "you are asking for."
        }), 400

    timeline = (data.get("timeline") or "").strip()
    if timeline and timeline not in VALID_TIMELINES:
        return jsonify({"error": "That is not a valid timeline."}), 400

    proposal = Partnership(
        proposer_id=org.id,
        recipient_id=recipient.id,
        status=Partnership.PENDING,
        proposer_gives=proposer_gives,
        recipient_gives=recipient_gives,
        timeline=timeline or None,
        message=(data.get("message") or "").strip() or None,
    )
    db.add(proposal)
    try:
        db.commit()
    except IntegrityError:
        # The partial unique index caught a second live proposal in the same
        # direction -- a double submit, or a genuine duplicate.
        db.rollback()
        return jsonify({
            "error": "You already have a pending proposal with this organization."
        }), 409

    # Fire-and-forget: sending happens on a background thread so a slow
    # provider does not slow down the response.
    notify_proposal_created(proposal)

    return jsonify({
        "message": "Proposal sent",
        "proposal": proposal.to_dict(viewer_id=org.id),
    }), 201


@app.route("/api/proposals", methods=["GET"])
@login_required
def list_proposals(org, db):
    """Everything this org is party to, in either direction."""
    rows = db.query(Partnership).filter(
        or_(Partnership.proposer_id == org.id,
            Partnership.recipient_id == org.id)
    ).order_by(Partnership.created_at.desc()).all()

    proposals = [p.to_dict(viewer_id=org.id) for p in rows]
    return jsonify({
        "proposals": proposals,
        "counts": {
            "incoming_pending": sum(
                1 for p in proposals
                if p["direction"] == "incoming" and p["status"] == "pending"
            ),
            "outgoing_pending": sum(
                1 for p in proposals
                if p["direction"] == "outgoing" and p["status"] == "pending"
            ),
            "accepted": sum(1 for p in proposals if p["status"] == "accepted"),
        },
    })


def _load_party_proposal(db, org, proposal_id):
    """Fetch a proposal, but only if this org is actually party to it."""
    proposal = db.get(Partnership, proposal_id)
    if proposal is None:
        return None
    if org.id not in (proposal.proposer_id, proposal.recipient_id):
        # Same response as "not found", so proposal ids belonging to other
        # organizations cannot be probed for existence.
        return None
    return proposal


@app.route("/api/proposals/<int:proposal_id>", methods=["GET"])
@login_required
def get_proposal(org, db, proposal_id):
    proposal = _load_party_proposal(db, org, proposal_id)
    if proposal is None:
        return jsonify({"error": "Proposal not found."}), 404
    return jsonify({"proposal": proposal.to_dict(viewer_id=org.id)})


@app.route("/api/proposals/<int:proposal_id>/accept", methods=["POST"])
@login_required
def accept_proposal(org, db, proposal_id):
    """Mutual confirmation. This is the step that creates the agreement."""
    proposal = _load_party_proposal(db, org, proposal_id)
    if proposal is None:
        return jsonify({"error": "Proposal not found."}), 404
    if proposal.recipient_id != org.id:
        return jsonify({"error": "Only the organization that received this "
                                 "proposal can accept it."}), 403
    if proposal.status != Partnership.PENDING:
        return jsonify({
            "error": f"This proposal was already {proposal.status}."
        }), 409

    data = request.get_json(silent=True) or {}
    proposal.status = Partnership.ACCEPTED
    proposal.responded_at = datetime.now(timezone.utc)
    proposal.response_message = (data.get("message") or "").strip() or None
    # Minted only now: agreement by both sides is what makes a summary worth
    # sharing, and a token on a pending proposal would leak an unagreed one.
    proposal.share_token = secrets.token_urlsafe(24)
    db.commit()

    notify_proposal_responded(proposal)

    return jsonify({
        "message": "Partnership agreed",
        "proposal": proposal.to_dict(viewer_id=org.id),
        "share_url": f"/partnership.html?token={proposal.share_token}",
    })


@app.route("/api/proposals/<int:proposal_id>/decline", methods=["POST"])
@login_required
def decline_proposal(org, db, proposal_id):
    proposal = _load_party_proposal(db, org, proposal_id)
    if proposal is None:
        return jsonify({"error": "Proposal not found."}), 404
    if proposal.recipient_id != org.id:
        return jsonify({"error": "Only the organization that received this "
                                 "proposal can decline it."}), 403
    if proposal.status != Partnership.PENDING:
        return jsonify({
            "error": f"This proposal was already {proposal.status}."
        }), 409

    data = request.get_json(silent=True) or {}
    proposal.status = Partnership.DECLINED
    proposal.responded_at = datetime.now(timezone.utc)
    proposal.response_message = (data.get("message") or "").strip() or None
    db.commit()

    notify_proposal_responded(proposal)

    return jsonify({
        "message": "Proposal declined",
        "proposal": proposal.to_dict(viewer_id=org.id),
    })


@app.route("/api/proposals/<int:proposal_id>/withdraw", methods=["POST"])
@login_required
def withdraw_proposal(org, db, proposal_id):
    proposal = _load_party_proposal(db, org, proposal_id)
    if proposal is None:
        return jsonify({"error": "Proposal not found."}), 404
    if proposal.proposer_id != org.id:
        return jsonify({"error": "Only the organization that sent this "
                                 "proposal can withdraw it."}), 403
    if proposal.status != Partnership.PENDING:
        return jsonify({
            "error": f"This proposal was already {proposal.status}."
        }), 409

    proposal.status = Partnership.WITHDRAWN
    proposal.responded_at = datetime.now(timezone.utc)
    db.commit()
    return jsonify({
        "message": "Proposal withdrawn",
        "proposal": proposal.to_dict(viewer_id=org.id),
    })


@app.route("/api/partnerships/<token>", methods=["GET"])
def public_partnership(token):
    """The shareable summary. Deliberately unauthenticated.

    The point is that an agreed partnership can be shown to a board or a
    funder without them needing an account. Only accepted partnerships resolve,
    and the payload carries no contact details -- just who agreed to what.
    """
    db = get_db()
    try:
        proposal = db.query(Partnership).filter(
            Partnership.share_token == token
        ).one_or_none()
        if proposal is None or proposal.status != Partnership.ACCEPTED:
            return jsonify({"error": "Partnership not found."}), 404
        return jsonify({"partnership": proposal.public_summary()})
    finally:
        db.close()


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, port=int(os.environ.get("PORT", 5000)))
