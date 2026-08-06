import os
import secrets
from functools import wraps

import bcrypt
from flask import (
    Flask, jsonify, request, session, send_from_directory
)

from categories import (
    CATEGORY_GROUPS, ORGANIZATION_TYPES, clean_categories,
)
from db import SessionLocal
from matching import find_matches, score_pair
from models import Organization

HERE = os.path.dirname(os.path.abspath(__file__))

# The frontend is served by Flask itself. That makes the API same-origin, which
# removes the CORS setup and the hardcoded localhost API base, and is what lets
# the session cookie work without SameSite gymnastics.
app = Flask(__name__, static_folder=HERE, static_url_path="")

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
    return send_from_directory(HERE, "index.html")


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
    })


# --- Auth -------------------------------------------------------------------
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are all required."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return jsonify({"error": "Password is too long (72 bytes maximum)."}), 400

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
        )
        db.add(org)
        db.commit()

        # Registering signs you in -- otherwise the next step is a pointless
        # trip back through the login form.
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

    missing = []
    if not name:
        missing.append("organization name")
    if not organization_type:
        missing.append("organization type")
    if not location:
        missing.append("location")
    if not needs:
        missing.append("at least one thing you need")
    if not offers:
        missing.append("at least one thing you can offer")
    if missing:
        return jsonify({"error": "Please provide " + ", ".join(missing) + "."}), 400

    org.name = name
    org.organization_type = organization_type
    org.location = location
    org.remote_friendly = bool(data.get("remote_friendly"))
    org.needs = needs
    org.offers = offers
    org.needs_note = (data.get("needs_note") or "").strip() or None
    org.offers_note = (data.get("offers_note") or "").strip() or None
    org.partnership_goals = (data.get("partnership_goals") or "").strip() or None
    org.description = (data.get("description") or "").strip() or None
    org.contact_email = (data.get("contact_email") or "").strip() or org.email
    org.contact_phone = (data.get("contact_phone") or "").strip() or None
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
    return jsonify({
        "matches": matches,
        "count": len(matches),
        "mutual_count": sum(1 for m in matches if m["match_detail"]["mutual"]),
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
    return jsonify({
        "organization": org.private_dict(),
        "needs_onboarding": False,
        "stats": {
            "total_matches": len(matches),
            "mutual_matches": len(mutual),
            "needs_count": len(org.needs or []),
            "offers_count": len(org.offers or []),
        },
        "top_matches": matches[:5],
    })


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, port=int(os.environ.get("PORT", 5000)))
