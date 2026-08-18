import hashlib
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
    CATEGORY_GROUPS, FOCUS_AREAS, ORGANIZATION_TYPES, TIMELINE_OPTIONS,
    VALID_TIMELINES, clean_categories, clean_focus_areas,
)
from db import SessionLocal
from links import LinkError, parse_links
from matching import find_matches, score_pair
from moderation import name_problem
from models import (
    Event, Organization, Partnership, ProfileView, SavedLead,
)
from notifications import (
    notify_email_verification, notify_password_changed, notify_password_reset,
    notify_proposal_created, notify_proposal_responded,
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


def _esc_attr(value):
    """Escape for use inside an HTML attribute value (a meta content="...")."""
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _truncate(text, limit):
    text = " ".join(text.split())  # collapse newlines from a textarea
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _render_og_page(filename, title, description):
    """Stamp a static page's <title> and inject its og:/twitter: tags.

    Slack, iMessage and Twitter (and everything else that renders a link
    preview) fetch the URL and read the HTML directly -- they do not run
    organization.js or partnership.js, so a preview built by those scripts
    is invisible to them. This gives crawlers the same title/description a
    signed-in visitor would see, without a screenshot-style og:image: there
    is no image generation pipeline behind this site, and a text-only
    preview beats the bare URL these links show today.
    """
    with open(os.path.join(STATIC_DIR, filename), "r", encoding="utf-8") as f:
        html = f.read()

    title = _truncate(title, 70)
    description = _truncate(description, 200)
    tags = (
        '<meta property="og:type" content="website">\n'
        '    <meta property="og:site_name" content="PartnerPortal">\n'
        f'    <meta property="og:title" content="{_esc_attr(title)}">\n'
        f'    <meta property="og:description" content="{_esc_attr(description)}">\n'
        f'    <meta property="og:url" content="{_esc_attr(request.url)}">\n'
        '    <meta name="twitter:card" content="summary">\n'
        f'    <meta name="twitter:title" content="{_esc_attr(title)}">\n'
        f'    <meta name="twitter:description" content="{_esc_attr(description)}">'
    )
    html = html.replace("<!-- og:meta -->", tags, 1)
    html = re.sub(
        r"<title>.*?</title>", f"<title>{_esc_attr(title)}</title>", html, count=1,
    )
    return html


def _org_og_description(profile):
    bio = (profile.get("description") or "").strip()
    if bio:
        return bio
    type_loc = " in ".join(
        p for p in [profile.get("organization_type"), profile.get("location")] if p
    )
    if type_loc:
        return f"{type_loc} on PartnerPortal, looking for partners."
    return "An organization profile on PartnerPortal."


@app.route("/organization.html")
def organization_page():
    """Same file static/organization.html serves, with real og: tags on top.

    Only completed profiles get a specific title/description, matching what
    /api/organizations/<id>/public resolves -- a link to a half-filled or
    missing profile falls back to a generic preview rather than a 404, since
    organization.js is what actually tells the visitor that on the page.
    """
    org_id = request.args.get("id", "")
    title = "Organization | PartnerPortal"
    description = (
        "See what this organization offers and needs, and get in touch to "
        "propose a partnership on PartnerPortal."
    )
    if org_id.isdigit():
        db = get_db()
        try:
            org = db.get(Organization, int(org_id))
            if org is not None and org.onboarding_complete:
                profile = org.public_profile()
                title = f"{profile['name']} | PartnerPortal"
                description = _org_og_description(profile)
        finally:
            db.close()
    return _render_og_page("organization.html", title, description)


@app.route("/partnership.html")
def partnership_page():
    """Same file static/partnership.html serves, with real og: tags on top.

    Only an accepted partnership resolves to specific parties, matching
    /api/partnerships/<token> -- a spent or unknown token falls back to a
    generic preview, since partnership.js is what shows the actual error.
    """
    token = request.args.get("token", "")
    title = "Partnership Agreement | PartnerPortal"
    description = (
        "See the terms two organizations agreed to through PartnerPortal."
    )
    if token:
        db = get_db()
        try:
            proposal = db.query(Partnership).filter(
                Partnership.share_token == token
            ).one_or_none()
            if proposal is not None and proposal.status == Partnership.ACCEPTED:
                summary = proposal.public_summary()
                p1, p2 = summary["parties"][0]["name"], summary["parties"][1]["name"]
                title = f"{p1} & {p2} | Partnership Agreement"
                description = f"{p1} and {p2} confirmed a partnership through PartnerPortal."
                if summary.get("timeline_label"):
                    description += f" Timeline: {summary['timeline_label']}."
        finally:
            db.close()
    return _render_og_page("partnership.html", title, description)


@app.errorhandler(404)
def not_found(error):
    """Serve the real 404 page, but never to something expecting JSON.

    Only unrouted requests reach this. Handlers that return their own 404 --
    an unknown organization id, a spent verification token -- return jsonify
    directly and are unaffected.

    The split matters because Flask's default 404 is an HTML document, and
    every fetch on this site goes through common.js's api(), which calls
    res.json() on the response. On an HTML body that throws, the parsed data
    is left null, and the caller ends up showing "Request failed (404)"
    instead of anything a person could act on. A mistyped API path is a
    programming error rather than a visitor error, so it gets a plain JSON
    404 and the HTML page is reserved for someone who actually typed a URL.
    """
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found."}), 404
    return send_from_directory(STATIC_DIR, "404.html"), 404


@app.errorhandler(500)
def internal_error(error):
    """Serve the real 500 page, but never to something expecting JSON.

    Same split as not_found() above and for the same reason: common.js's
    api() calls res.json() on every response, so Flask's default HTML error
    document would surface there as an unreadable parse failure instead of a
    message a person could act on.

    Logged here rather than left silent -- a Neon cold start or a dropped
    connection is exactly the kind of thing this exists to catch, and
    without a log line it would otherwise vanish the moment the response
    goes out.
    """
    app.logger.error("Unhandled exception", exc_info=error)
    if request.path.startswith("/api/"):
        return jsonify({"error": "Something went wrong. Please try again."}), 500
    return send_from_directory(STATIC_DIR, "500.html"), 500


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
        # A separate list from `groups`, not a sixth group in it: these are
        # what an organization works on, never something it needs or offers,
        # and merging them would let one be picked as either.
        "focus_areas": [
            {"slug": slug, "label": label} for slug, label in FOCUS_AREAS
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
    problem = name_problem(name)
    if problem:
        return jsonify({"error": "Please provide " + problem + "."}), 400
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


# A reset link is enough on its own to take over the account, unlike a
# verification link -- so it lives for an hour, not a week. Whoever requested
# it can always ask for another.
PASSWORD_RESET_TOKEN_LIFETIME = timedelta(hours=1)


@app.route("/forgot-password", methods=["POST"])
def forgot_password():
    """Start a password reset. Always answers the same way.

    Returning a different message for "no such account" than for "email
    sent" would let this endpoint be used to check who has registered --
    exactly the enumeration /login's identical "Invalid email or password"
    already avoids. So the response here never depends on what was found:
    the org may not exist, may have no password to reset (a profile someone
    pre-created that nobody has claimed), or may exist and get an email. All
    three look the same from the caller's side.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    if not email or not is_valid_email(email):
        return jsonify({"error": "Please enter a valid email address."}), 400

    # Two buckets. The IP limit is the usual protection against a script
    # working down a list of addresses; the email limit exists because the
    # target here is not the server, it is a stranger's inbox -- without it,
    # anyone who knows an address could bury it in reset emails from a
    # rotating set of IPs. Same 3/hour ceiling as verify-email's resend, for
    # the same reason: this protects mail delivery, not compute.
    if rate_limited("forgot_password_ip", client_ip(),
                    max_attempts=8, window_seconds=3600):
        return jsonify({
            "error": "Too many requests from this connection. Please try "
                     "again in a while.",
        }), 429
    if rate_limited("forgot_password_email", email,
                    max_attempts=3, window_seconds=3600):
        return jsonify({
            "error": "Too many reset emails have gone out for that address "
                     "recently. Check your inbox and spam folder, then try "
                     "again in a little while.",
        }), 429

    generic = jsonify({
        "message": "If an account exists for that email, we've sent a "
                    "password reset link.",
    }), 200

    db = get_db()
    try:
        org = db.query(Organization).filter(
            Organization.email == email
        ).one_or_none()
        # No password_hash means there is nothing to reset -- a pre-created
        # profile nobody has claimed, the same case /register's password
        # check protects against from the other direction. Silently doing
        # nothing keeps this indistinguishable from "no such account".
        if org is not None and org.password_hash is not None:
            org.password_reset_token = secrets.token_urlsafe(32)
            org.password_reset_sent_at = datetime.now(timezone.utc)
            db.commit()
            notify_password_reset(org, org.password_reset_token)
        return generic
    finally:
        db.close()


@app.route("/api/reset-password", methods=["POST"])
def reset_password():
    """The other end of the link in notify_password_reset.

    Unauthenticated like /api/verify-email -- the token is the credential,
    and requiring a session would break the link for anyone reading their
    email on a different device than the one they are locked out of.
    """
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    password = data.get("password") or ""

    if not token:
        return jsonify({"error": "This link is missing its token."}), 400

    db = get_db()
    try:
        org = db.query(Organization).filter(
            Organization.password_reset_token == token
        ).one_or_none()

        if org is None:
            # Covers "never existed" and "already used" alike -- the token is
            # cleared on success, so a second click lands here too.
            return jsonify({
                "error": "This reset link is invalid or has already been "
                         "used.",
            }), 404

        if org.password_reset_sent_at and (
            datetime.now(timezone.utc) - org.password_reset_sent_at
            > PASSWORD_RESET_TOKEN_LIFETIME
        ):
            return jsonify({
                "error": "This reset link has expired. Please request a "
                         "new one.",
            }), 410

        # Same rules /register enforces, including the length/common-password
        # checks the client-side checklist does not mirror -- a stolen or
        # guessed-at token should not make the account easier to secure badly
        # than signing up does.
        problem = password_problem(password, email=org.email, name=org.name)
        if problem:
            return jsonify({"error": problem, "field": "password"}), 400

        org.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        org.password_reset_token = None
        org.password_reset_sent_at = None
        db.commit()

        # Proving control of the inbox and choosing a new password is the
        # same proof /login asks for; signing in here saves a redundant trip
        # back through it, the same reasoning /register signs someone in on
        # completion.
        session.clear()
        session["org_id"] = org.id
        session.permanent = True
        return jsonify({
            "message": "Password reset",
            "organization": org.private_dict(),
        }), 200
    finally:
        db.close()


# How long a verification link stays valid. Generous: letting a link sit
# unread over a weekend and still work matters more than a tight expiry, and
# an expired one is no longer a dead end now that /api/verify-email/resend
# can issue a fresh one.
EMAIL_VERIFY_TOKEN_LIFETIME = timedelta(days=7)

# Whether an unverified org is actually stopped from proposing a partnership.
#
# Off by default, and deliberately so. The gate is only fair if the
# verification email reliably arrives, and right now it does not: Resend is
# on its sandbox sender (onboarding@resend.dev), which refuses any recipient
# except the address owning the Resend account --
#
#   403 "You can only send testing emails to your own email address"
#
# so every signup but one would be told to check an inbox that never receives
# anything, with no way past it. Enforcing under those conditions does not
# stop spam, it stops signups.
#
# Read from the environment rather than edited here, so turning it on once a
# domain is verified at resend.com/domains (and EMAIL_FROM points at that
# domain) is a config change on the host, not a deploy. Everything else about
# verification stays live meanwhile -- the link, the resend flow, the badge
# and the prompts -- so the day this flips nothing else has to change.
REQUIRE_EMAIL_VERIFICATION = (
    os.environ.get("REQUIRE_EMAIL_VERIFICATION", "").strip().lower()
    in {"1", "true", "yes", "on"}
)


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


@app.route("/api/verify-email/resend", methods=["POST"])
@login_required
def resend_verification(org, db):
    """Issue a fresh verification link for the signed-in org.

    Registration sends one of these, but a message can bounce, land in spam,
    or expire while it sits unread -- and until now that was the end of it:
    the only route to a working link was registering all over again.
    """
    if org.email_verified:
        # No information leak to worry about: this is the caller's own
        # account, and the settings page already shows the same status.
        return jsonify({
            "error": "This email address is already verified.",
        }), 400

    # Tighter than the other limits in this file on purpose. Every other rate
    # limit here protects CPU or the database; this one protects somebody's
    # inbox, and the address is attacker-chosen at signup. Three an hour
    # covers "it did not arrive, send it again" without making the endpoint
    # a way to bury an address in mail.
    if rate_limited("verify_resend", str(org.id),
                    max_attempts=3, window_seconds=3600):
        return jsonify({
            "error": "Several verification emails have gone out recently. "
                     "Check your inbox and spam folder, then try again in a "
                     "little while.",
        }), 429

    # Replacing the token invalidates whatever was in the previous email --
    # the column holds exactly one, so an older link stops working the moment
    # this runs. That is the intended behaviour: the newest link is the only
    # live one, and a link someone forwarded or left in an old message cannot
    # be used later.
    org.email_verify_token = secrets.token_urlsafe(32)
    org.email_verify_sent_at = datetime.now(timezone.utc)
    db.commit()

    notify_email_verification(org, org.email_verify_token)
    return jsonify({
        "message": "Verification email sent",
        "email": org.email,
    }), 200


@app.route("/api/me", methods=["GET"])
@login_required
def get_me(org, db):
    # verification_required travels with the payload so the pages that prompt
    # for verification can say what not verifying actually costs, and stay
    # truthful when the gate is switched on or off. Server config, not a
    # property of the org, so it sits beside the organization rather than in
    # private_dict.
    #
    # pending_proposals is what the nav badge (common.js) reads. Every page
    # already calls /api/me to resolve the signed-in state, so folding the
    # count in here costs one indexed COUNT query, rather than a second
    # request to /api/proposals' much heavier full-list payload on every
    # page load just to find out whether anything is waiting.
    pending_proposals = db.query(Partnership).filter(
        Partnership.recipient_id == org.id,
        Partnership.status == Partnership.PENDING,
    ).count()
    return jsonify({
        "organization": org.private_dict(),
        "verification_required": REQUIRE_EMAIL_VERIFICATION,
        "pending_proposals": pending_proposals,
    })


# --- Account settings -------------------------------------------------------
@app.route("/api/settings", methods=["PATCH"])
@login_required
def update_settings(org, db):
    """Account-level preferences, kept apart from the profile.

    Only fields actually present in the body are touched, so a client that
    knows about one setting cannot reset another it has never heard of by
    omitting it. That is the opposite of the rule /api/onboarding uses for
    links_public -- there the whole profile form is submitted at once, so a
    missing key really does mean "unticked"; here each control saves on its
    own and a missing key means "not this one".
    """
    data = request.get_json(silent=True) or {}

    if "email_notifications" in data:
        value = data["email_notifications"]
        # Strictly a boolean rather than truthiness: "false" and 0 are both
        # things a client might send, and both read as the wrong answer under
        # bool(). Rejecting is safer than guessing which one was meant.
        if not isinstance(value, bool):
            return jsonify({
                "error": "Email notifications must be true or false.",
                "field": "email_notifications",
            }), 400
        org.email_notifications = value

    db.commit()
    return jsonify({
        "message": "Settings saved",
        "organization": org.private_dict(),
    }), 200


@app.route("/api/account/password", methods=["POST"])
@login_required
def change_password(org, db):
    """Change the signed-in org's password, given the current one.

    The current password is required even though the caller already holds a
    valid session, for the same reason /api/account does: a session cookie on
    a shared or unattended browser should not be enough to hand out a new
    password on its own. Unlike /api/reset-password, this never touches
    email -- there is nothing to prove here that a valid session has not
    already proven, so no token or link is involved.
    """
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    if not current_password:
        return jsonify({
            "error": "Enter your current password.",
            "field": "current_password",
        }), 400
    if not new_password:
        return jsonify({
            "error": "Enter a new password.",
            "field": "new_password",
        }), 400

    # Keyed by account, like /api/account's own limit: the thing worth
    # slowing down is guessing against this one account's current password,
    # not volume from one address.
    if rate_limited("change_password", str(org.id), max_attempts=5,
                    window_seconds=900):
        return jsonify({
            "error": "Too many incorrect attempts. Please wait a few minutes "
                     "and try again.",
        }), 429

    if not org.password_hash:
        # Cannot happen through the normal session path -- both /register and
        # /login require a password to reach this point -- but guarded the
        # same way /api/account guards it, rather than assumed away.
        return jsonify({
            "error": "This account has no password set. Please contact "
                     "support.",
        }), 400

    if len(current_password.encode("utf-8")) > MAX_PASSWORD_BYTES or not bcrypt.checkpw(
        current_password.encode("utf-8"), org.password_hash.encode("utf-8")
    ):
        return jsonify({
            "error": "Your current password is incorrect.",
            "field": "current_password",
        }), 403

    if bcrypt.checkpw(new_password.encode("utf-8"), org.password_hash.encode("utf-8")):
        return jsonify({
            "error": "That is your current password. Choose a different one.",
            "field": "new_password",
        }), 400

    problem = password_problem(new_password, email=org.email, name=org.name)
    if problem:
        return jsonify({"error": problem, "field": "new_password"}), 400

    org.password_hash = bcrypt.hashpw(
        new_password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    db.commit()
    notify_password_changed(org)
    return jsonify({"message": "Password changed"}), 200


@app.route("/api/account", methods=["DELETE"])
@login_required
def delete_account(org, db):
    """Delete the signed-in organization, after re-checking its password.

    The password is required even though the caller already holds a valid
    session: this is the one action with no undo, and a session cookie on a
    borrowed or unattended browser should not be enough to destroy an account.

    Partnerships pointing at this org go with it -- both foreign keys are
    ON DELETE CASCADE -- so no proposal is left referencing a row that is no
    longer there.
    """
    data = request.get_json(silent=True) or {}
    password = data.get("password") or ""

    if not password:
        return jsonify({
            "error": "Enter your password to confirm.",
            "field": "password",
        }), 400

    # Keyed by account, not IP: this endpoint needs a valid session, so the
    # thing worth slowing down is repeated guessing against one account rather
    # than volume from one address.
    if rate_limited("delete_account", str(org.id), max_attempts=5,
                    window_seconds=900):
        return jsonify({
            "error": "Too many incorrect attempts. Please wait a few minutes "
                     "and try again.",
        }), 429

    if not org.password_hash:
        # A profile pre-created for an org that never claimed it. There is no
        # password to check, so there is no safe way to honour this here.
        return jsonify({
            "error": "This account has no password set, so it cannot be "
                     "deleted from here. Please contact support.",
        }), 400

    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES or not bcrypt.checkpw(
        password.encode("utf-8"), org.password_hash.encode("utf-8")
    ):
        return jsonify({
            "error": "That password is incorrect.",
            "field": "password",
        }), 403

    db.delete(org)
    db.commit()
    session.clear()
    return jsonify({"message": "Account deleted"}), 200


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
    # Optional, unlike needs and offers: an organization that would rather not
    # categorise what it works on still gets matched on the exchange, which is
    # what the score is actually built from.
    focus_areas = clean_focus_areas(data.get("focus_areas"))

    # Mirrors the minimums the onboarding form enforces. A single character
    # passes a presence check while telling a prospective partner nothing, and
    # the client is not the only way into this endpoint.
    problems = []
    if len(name) < 2:
        problems.append("a full organization name")
    else:
        problem = name_problem(name)
        if problem:
            problems.append(problem)
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
    org.focus_areas = focus_areas
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
    # Opt-in, so a missing key means "not public" rather than leaving a
    # previous true in place: an older client that does not send the field
    # should not be able to keep links published by omission.
    org.links_public = bool(data.get("links_public"))
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

    # So the star on each card starts in the right state. Sent as one list of
    # ids rather than a flag per match: the client already holds the matches
    # and only needs to know which of them are on the shortlist, and this way
    # the answer stays correct for the examples too without touching either
    # list.
    saved_ids = _saved_ids(db, org)

    return jsonify({
        "matches": matches,
        "count": len(matches),
        "mutual_count": sum(1 for m in matches if m["match_detail"]["mutual"]),
        "examples": examples,
        "example_count": len(examples),
        "saved_ids": sorted(saved_ids),
    })


# --- Profile views ----------------------------------------------------------
# Counted, never itemised. An organization is told how often its public
# profile was opened; it is not told by whom. Naming visitors would publish
# the browsing of people who never agreed to be seen doing it -- most of them
# signed-out, with no account here and no way to opt out.
VIEW_DEDUP_WINDOW = timedelta(hours=24)


def _viewer_key(viewer_org):
    """A stable, opaque handle for whoever is looking.

    Salted with the app secret and never stored in the clear, because the
    only question it answers is "is this the same visitor as a moment ago".
    A signed-in viewer is keyed by account, so the same organization opening
    a profile from a laptop and a phone is one viewer rather than two;
    everyone else is keyed by address and user agent, which is the closest
    thing available without setting a tracking cookie on a public page.
    """
    if viewer_org is not None:
        basis = f"org:{viewer_org.id}"
    else:
        basis = f"anon:{client_ip()}:{request.headers.get('User-Agent', '')}"
    return hashlib.sha256(
        f"{app.secret_key}:{basis}".encode("utf-8")
    ).hexdigest()


def _record_profile_view(db, target):
    """Record that `target`'s profile was opened, at most once per viewer per day.

    Never lets a counting problem break the page it is counting: the profile
    is what the visitor asked for, and a failed insert here is not worth a
    500. Rolled back and dropped instead.
    """
    try:
        viewer = current_org(db)
        # An organization checking its own public profile -- which the
        # dashboard and settings both link to -- is not an audience.
        if viewer is not None and viewer.id == target.id:
            return

        key = _viewer_key(viewer)
        since = datetime.now(timezone.utc) - VIEW_DEDUP_WINDOW
        already = db.query(ProfileView.id).filter(
            ProfileView.organization_id == target.id,
            ProfileView.viewer_key == key,
            ProfileView.viewed_at >= since,
        ).first()
        # Reloading a profile, or coming back to it twice in an afternoon, is
        # one organization taking an interest rather than several.
        if already is not None:
            return

        db.add(ProfileView(organization_id=target.id, viewer_key=key))
        db.commit()
    except Exception:
        db.rollback()
        app.logger.exception("Could not record a profile view")


def _profile_view_counts(db, org):
    total = db.query(ProfileView.id).filter(
        ProfileView.organization_id == org.id
    ).count()
    since = datetime.now(timezone.utc) - timedelta(days=30)
    recent = db.query(ProfileView.id).filter(
        ProfileView.organization_id == org.id,
        ProfileView.viewed_at >= since,
    ).count()
    return total, recent


# --- Saved leads ------------------------------------------------------------
# A private shortlist. Matching answers "who could work with me", and that
# answer moves as either side edits its profile and as the directory grows --
# so it is a poor place to keep a decision. Saving records that someone picked
# an organization out, and keeps it reachable afterwards whatever the ranking
# does. Never visible to the organization saved: this is a bookmark, not an
# approach.
def _saved_ids(db, org):
    """The set of organization ids `org` has shortlisted."""
    rows = db.query(SavedLead.saved_organization_id).filter(
        SavedLead.organization_id == org.id
    ).all()
    return {row[0] for row in rows}


@app.route("/api/saved", methods=["GET"])
@login_required
def list_saved(org, db):
    """The shortlist, most recently saved first.

    Scored fresh on every read rather than stored: a saved organization is a
    decision, but the reason it looked promising is a live comparison of two
    profiles, and either may have changed since. Serving a remembered score
    would quietly show a number that is no longer true.

    Deliberately not filtered by whether they still match. Dropping an
    organization from someone's own shortlist because the ranking moved is
    exactly the loss this table exists to prevent -- if it no longer overlaps
    it simply scores low, and stays where it was put.
    """
    rows = db.query(SavedLead).filter(
        SavedLead.organization_id == org.id
    ).order_by(SavedLead.created_at.desc()).all()

    saved = []
    for row in rows:
        other = row.saved_organization
        # An org that has since un-finished its profile would otherwise be
        # rendered as a card with nothing in it.
        if other is None or not other.onboarding_complete:
            continue
        data = other.public_dict()
        score, reasons, detail = score_pair(org, other)
        data.update({
            "match_score": score,
            "reasons": reasons,
            "match_detail": detail,
            "saved_at": row.created_at.isoformat() if row.created_at else None,
        })
        saved.append(data)

    return jsonify({"saved": saved, "count": len(saved)})


@app.route("/api/saved", methods=["POST"])
@login_required
def create_saved(org, db):
    data = request.get_json(silent=True) or {}
    try:
        target_id = int(data.get("organization_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Which organization is this for?"}), 400

    if target_id == org.id:
        return jsonify({"error": "You cannot save your own organization."}), 400

    other = db.get(Organization, target_id)
    if other is None or not other.onboarding_complete:
        return jsonify({"error": "Organization not found."}), 404
    if other.is_demo:
        # Same line create_proposal draws: example organizations have no owner
        # and nothing to follow up on, so a shortlist of them leads nowhere.
        return jsonify({
            "error": "Example organizations cannot be saved. They are here to "
                     "show how matching works.",
        }), 400

    existing = db.query(SavedLead).filter(
        SavedLead.organization_id == org.id,
        SavedLead.saved_organization_id == target_id,
    ).one_or_none()
    # Idempotent rather than a 409: this backs a toggle, and a double-clicked
    # star means "saved", not "error". uq_saved_leads_pair is what makes the
    # race between two in-flight saves land on one row either way.
    if existing is None:
        db.add(SavedLead(organization_id=org.id, saved_organization_id=target_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()

    return jsonify({"message": "Saved", "organization_id": target_id}), 201


@app.route("/api/saved/<int:org_id>", methods=["DELETE"])
@login_required
def delete_saved(org, db, org_id):
    row = db.query(SavedLead).filter(
        SavedLead.organization_id == org.id,
        SavedLead.saved_organization_id == org_id,
    ).one_or_none()
    # Also idempotent: unsaving something already gone is the state asked for.
    if row is not None:
        db.delete(row)
        db.commit()
    return jsonify({"message": "Removed", "organization_id": org_id})


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
        # Counted here rather than on the /organization.html route: this is
        # what organization.js fetches on every profile load, signed in or
        # not, and exactly once. Link-preview crawlers (Slack, iMessage,
        # Twitter) request the HTML and never run its script, so an unfurled
        # link cannot inflate the number.
        _record_profile_view(db, other)
        return jsonify({"organization": other.public_profile()})
    finally:
        db.close()


# --- Dashboard --------------------------------------------------------------
@app.route("/api/dashboard", methods=["GET"])
@login_required
def get_dashboard(org, db):
    """Real numbers for the dashboard, replacing the hardcoded placeholders."""
    # Rides along with the payload the page already fetches, rather than a
    # second request on load -- same reasoning as pending_proposals on
    # /api/me. Included in the not-yet-onboarded branch too: that page still
    # renders the meetings card, and an empty list there should mean "none"
    # rather than "never asked".
    events = [e.to_dict() for e in _events_for(db, org)]
    # The shortlist's size only -- the dialog behind the card fetches the
    # organizations themselves when it is opened, the same way the matches
    # views do.
    saved_count = len(_saved_ids(db, org))
    views_total, views_recent = _profile_view_counts(db, org)

    if not org.onboarding_complete:
        return jsonify({
            "organization": org.private_dict(),
            "needs_onboarding": True,
            "stats": {
                "total_matches": 0, "mutual_matches": 0,
                "needs_count": 0, "offers_count": 0,
                "saved": saved_count,
                # Zero until the profile is finished -- it has no public URL
                # to be looked at yet -- but reported rather than assumed.
                "profile_views": views_total,
                "profile_views_recent": views_recent,
            },
            "top_matches": [],
            "events": events,
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
        "verification_required": REQUIRE_EMAIL_VERIFICATION,
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
            "saved": saved_count,
            "profile_views": views_total,
            "profile_views_recent": views_recent,
        },
        "top_matches": matches[:5],
        "recent_proposals": proposals[:5],
        "events": events,
    })


# --- Meetings ---------------------------------------------------------------
# These were kept in localStorage, which meant they were not saved at all:
# they belonged to one browser, died with site data, and never followed the
# account. Everything else on the dashboard is server-backed, so this was the
# one place the page lost work someone had done.
def _events_for(db, org):
    """This org's meetings, soonest first. Covered by ix_events_organization_date."""
    return db.query(Event).filter(
        Event.organization_id == org.id
    ).order_by(Event.date, Event.time).all()


@app.route("/api/events", methods=["GET"])
@login_required
def list_events(org, db):
    return jsonify({"events": [e.to_dict() for e in _events_for(db, org)]})


@app.route("/api/events", methods=["POST"])
@login_required
def create_event(org, db):
    """Save a meeting.

    Mirrors the checks ppdashboard.js's validateEventForm already makes --
    the form is not the only way in here, and the columns are Date/Time/Float
    rather than the strings the browser sends, so anything malformed has to
    be turned away before it reaches them.
    """
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    partner = (data.get("partner") or "").strip()
    description = (data.get("description") or "").strip()
    location = (data.get("location") or "").strip()

    problems = []
    if not title:
        problems.append("a title")
    if not partner:
        problems.append("who the meeting is with")

    # strptime rather than date.fromisoformat: fromisoformat also accepts
    # forms the date input never produces, and the column stores neither.
    event_date = event_time = None
    try:
        event_date = datetime.strptime(data.get("date") or "", "%Y-%m-%d").date()
    except ValueError:
        problems.append("a valid date")
    try:
        event_time = datetime.strptime(data.get("time") or "", "%H:%M").time()
    except ValueError:
        problems.append("a valid start time")

    try:
        duration = float(data.get("duration"))
    except (TypeError, ValueError):
        duration = None
    # Capped as well as floored: a meeting cannot run longer than the day it
    # is filed under, and the check constraint only rules out zero and below.
    if duration is None or duration <= 0 or duration > 24:
        problems.append("a length between 0 and 24 hours")

    if problems:
        return jsonify({"error": "Please provide " + ", ".join(problems) + "."}), 400

    # Length caps match the columns, so an over-long field is a 400 here
    # rather than a DataError from the driver further down.
    if len(title) > 200 or len(partner) > 255 or len(location) > 255:
        return jsonify({"error": "That is longer than this field allows."}), 400

    event = Event(
        organization_id=org.id,
        title=title,
        date=event_date,
        time=event_time,
        duration=duration,
        partner_name=partner,
        description=description or None,
        location=location or None,
    )
    db.add(event)
    db.commit()
    return jsonify({"message": "Meeting saved", "event": event.to_dict()}), 201


@app.route("/api/events/<int:event_id>", methods=["DELETE"])
@login_required
def delete_event(org, db, event_id):
    event = db.query(Event).filter(
        Event.id == event_id,
        # Scoped to the caller, so another org's meeting id cannot be deleted
        # -- or probed for existence -- through this route.
        Event.organization_id == org.id,
    ).one_or_none()
    if event is None:
        return jsonify({"error": "Meeting not found."}), 404

    db.delete(event)
    db.commit()
    return jsonify({"message": "Meeting removed"})


# --- Partnership proposals --------------------------------------------------
@app.route("/api/proposals", methods=["POST"])
@login_required
def create_proposal(org, db):
    """Propose a partnership with structured terms on both sides."""
    if not org.onboarding_complete:
        return jsonify({"error": "Complete your profile first."}), 409

    # The one thing an unverified account cannot do, when the gate is on (see
    # REQUIRE_EMAIL_VERIFICATION -- currently off until outbound email is
    # reliable). Sending a proposal is what puts this org's name, and an
    # email, in front of a stranger who did not ask for it, so it is the
    # action worth holding back until the address behind the account is known
    # to be real. Everything else stays open either way: an unverified org can
    # sign in, finish its profile, appear in search, and receive and answer
    # proposals, because none of those reach anyone who has not already
    # chosen to engage.
    if REQUIRE_EMAIL_VERIFICATION and not org.email_verified:
        return jsonify({
            "error": "Verify your email address before proposing a "
                     "partnership. Open Settings to send a new "
                     "verification link.",
            "needs_verification": True,
        }), 403

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
