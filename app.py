import os
import secrets
from datetime import datetime, timezone
from functools import wraps

import bcrypt
from flask import (
    Flask, jsonify, request, session, send_from_directory
)

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from categories import (
    CATEGORY_GROUPS, ORGANIZATION_TYPES, TIMELINE_OPTIONS, VALID_TIMELINES,
    clean_categories,
)
from db import SessionLocal
from matching import find_matches, score_pair
from models import Organization, Partnership

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
