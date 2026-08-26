"""The admin panel.

The authorization boundary comes first here, and everything else second,
because this is the only surface in the app that reads and acts on other
people's rows. A bug anywhere else shows somebody the wrong number; a bug here
hands a stranger the directory.

Two properties are load-bearing and are asserted from several directions:

* An admin is not an organization. Nothing a signup writes, and no amount of
  being signed in as an organization, produces admin access -- because the
  answer is not stored in `organizations` at all.

* Every admin route answers 404 without an admin session, never 401 or 403.
  There is no link to these routes, they are not in the sitemap and robots
  disallows them; answering "unauthorized" would undo all three, because it
  confirms the surface exists to anybody with a wordlist.
"""

import bcrypt
import pytest

import app as app_module
from models import Admin, AdminAction, ContactMessage, Organization


ADMIN_PASSWORD = "Test1234!admin"

# Every route the panel exposes, with a method that reaches it.
ADMIN_ROUTES = [
    ("get", "/api/admin/me"),
    ("get", "/api/admin/overview"),
    ("post", "/api/admin/contact-messages/1/handled"),
    ("delete", "/api/admin/organizations/1/flag"),
    ("post", "/api/admin/organizations/1/hidden"),
]


@pytest.fixture
def make_admin(session):
    def _make(email=None, name="Test Admin"):
        import uuid
        admin = Admin(
            email=email or f"pytest-admin-{uuid.uuid4().hex[:8]}@example.com",
            name=name,
            password_hash=bcrypt.hashpw(
                ADMIN_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode(),
        )
        session.add(admin)
        session.commit()
        return admin
    return _make


@pytest.fixture
def admin_login(client):
    def _login(admin):
        response = client.post("/api/admin/login", json={
            "email": admin.email, "password": ADMIN_PASSWORD})
        assert response.status_code == 200, response.get_data(as_text=True)
        return client
    return _login


# --- The boundary ----------------------------------------------------------

@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_every_admin_route_is_a_404_to_a_stranger(client, method, path):
    assert getattr(client, method)(path).status_code == 404


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_being_signed_in_as_an_organization_is_not_admin_access(
        client, login, make_org, method, path):
    """The property a separate table exists to give.

    An account here *is* an organization, so a privilege flag would live in
    the rows every signup writes. Nothing in that table can grant this.
    """
    login(make_org())
    assert getattr(client, method)(path).status_code == 404


def test_a_wrong_password_is_refused(client, make_admin):
    admin = make_admin()
    response = client.post("/api/admin/login", json={
        "email": admin.email, "password": "not-the-password"})
    assert response.status_code == 401
    assert client.get("/api/admin/overview").status_code == 404


def test_an_unknown_address_and_a_wrong_password_read_the_same(
        client, make_admin):
    """The set of admin addresses is small, and confirming one is most of the
    work of attacking it."""
    admin = make_admin()
    wrong_password = client.post("/api/admin/login", json={
        "email": admin.email, "password": "not-the-password"})
    unknown = client.post("/api/admin/login", json={
        "email": "pytest-nobody@example.com", "password": "anything"})
    assert wrong_password.status_code == unknown.status_code == 401
    assert wrong_password.get_json() == unknown.get_json()


def test_signing_in_reaches_the_panel(client, make_admin, admin_login):
    admin = make_admin()
    admin_login(admin)
    payload = client.get("/api/admin/overview").get_json()
    assert payload["admin"]["email"] == admin.email
    assert "contact_messages" in payload and "flagged" in payload


def test_the_two_sessions_are_independent(client, make_admin, admin_login,
                                          make_org, login):
    """Being an admin does not sign you out of your own organization, and
    signing out of the panel does not sign you out of the product."""
    org = make_org()
    login(org)
    admin_login(make_admin())

    assert client.get("/api/me").status_code == 200
    assert client.get("/api/admin/overview").status_code == 200

    client.post("/api/admin/logout")
    assert client.get("/api/admin/overview").status_code == 404
    # Still signed in as the organization.
    assert client.get("/api/me").status_code == 200


def test_changing_the_password_ends_the_admin_session(
        client, session, make_admin, admin_login):
    """The same revocation organizations have, where it matters most."""
    admin = make_admin()
    admin_login(admin)
    assert client.get("/api/admin/overview").status_code == 200

    admin.session_epoch = (admin.session_epoch or 0) + 1
    session.commit()

    assert client.get("/api/admin/overview").status_code == 404


# --- Contact messages ------------------------------------------------------

def test_the_queue_holds_what_the_form_wrote(client, session, make_admin,
                                             admin_login):
    client.post("/api/contact", json={
        "name": "Ada", "email": "pytest-ada@example.com",
        "message": "A question about partnering."})
    admin_login(make_admin())

    payload = client.get("/api/admin/overview").get_json()
    assert any(m["email"] == "pytest-ada@example.com"
               for m in payload["contact_messages"])


def test_handling_a_message_takes_it_off_the_queue_and_keeps_it(
        client, session, make_admin, admin_login):
    client.post("/api/contact", json={
        "name": "Grace", "email": "pytest-grace@example.com",
        "message": "Hello."})
    row = session.query(ContactMessage).filter(
        ContactMessage.email == "pytest-grace@example.com").one()
    admin_login(make_admin())

    assert client.post(
        f"/api/admin/contact-messages/{row.id}/handled",
        json={"handled": True}).status_code == 200

    session.refresh(row)
    assert row.handled_at is not None
    # Not deleted -- a handled message is still the record that somebody
    # wrote in.
    assert session.get(ContactMessage, row.id) is not None
    payload = client.get("/api/admin/overview").get_json()
    assert not any(m["id"] == row.id for m in payload["contact_messages"])


# --- Flags -----------------------------------------------------------------

def test_a_flag_can_be_cleared(client, session, make_admin, admin_login,
                               make_org):
    org = make_org(name="pytest-flag Fuck Cancer", name_flagged=True)
    admin_login(make_admin())

    assert client.delete(
        f"/api/admin/organizations/{org.id}/flag").status_code == 200
    session.refresh(org)
    assert org.name_flagged is False


def test_clearing_an_unflagged_name_is_refused(client, make_admin,
                                               admin_login, make_org):
    org = make_org()
    admin_login(make_admin())
    assert client.delete(
        f"/api/admin/organizations/{org.id}/flag").status_code == 409


# --- Hiding ----------------------------------------------------------------

def test_hiding_requires_a_reason(client, make_admin, admin_login, make_org):
    """It is emailed to them unedited, and requiring it is most of what stops
    this being used casually."""
    org = make_org()
    admin_login(make_admin())
    response = client.post(f"/api/admin/organizations/{org.id}/hidden",
                           json={"hidden": True})
    assert response.status_code == 400
    assert response.get_json()["field"] == "reason"


def test_hiding_removes_it_from_every_discovery_surface(
        client, session, make_admin, admin_login, make_org, login):
    """Four places ask this question, and all four have to agree."""
    target = make_org(name="pytest-hide Target", offers=["web_development"],
                      needs=["volunteers"])
    seeker = make_org(name="pytest-hide Seeker", offers=["volunteers"],
                      needs=["web_development"])

    admin_login(make_admin())
    assert client.post(f"/api/admin/organizations/{target.id}/hidden",
                       json={"hidden": True, "reason": "Testing."}
                       ).status_code == 200

    # 1. The public profile.
    assert client.get(
        f"/api/organizations/{target.id}/public").status_code == 404
    # 2. The public directory.
    listed = client.get("/api/directory?q=pytest-hide").get_json()
    assert not any(o["id"] == target.id for o in listed["organizations"])

    login(seeker)
    # 3. The signed-in directory.
    listed = client.get("/api/organizations?q=pytest-hide").get_json()
    assert not any(o["id"] == target.id for o in listed["organizations"])
    # 4. Matching.
    matches = client.get("/api/matches").get_json()
    assert not any(m["id"] == target.id for m in matches["matches"])
    # And the single-organization route.
    assert client.get(f"/api/organizations/{target.id}").status_code == 404


def test_hiding_does_not_touch_an_existing_partnership(
        client, session, make_admin, admin_login, make_org, login):
    """Taking a profile out of a listing is not the same act as withdrawing
    somebody from an agreement they already made."""
    proposer = make_org(offers=["web_development"], needs=["mentors"])
    recipient = make_org(offers=["mentors"], needs=["web_development"])
    login(proposer)
    created = client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["web_development"],
        "recipient_gives": ["mentors"],
    })
    assert created.status_code == 201

    admin_login(make_admin())
    client.post(f"/api/admin/organizations/{recipient.id}/hidden",
                json={"hidden": True, "reason": "Testing."})

    login(proposer)
    proposals = client.get("/api/proposals").get_json()["proposals"]
    mine = [p for p in proposals if p["id"] == created.get_json()["proposal"]["id"]]
    assert mine, "the partnership disappeared when the other side was hidden"
    assert mine[0]["counterpart"]["name"] == recipient.name


def test_hiding_can_be_undone(client, session, make_admin, admin_login,
                              make_org):
    org = make_org(name="pytest-unhide Target")
    admin_login(make_admin())
    client.post(f"/api/admin/organizations/{org.id}/hidden",
                json={"hidden": True, "reason": "Testing."})
    assert client.post(f"/api/admin/organizations/{org.id}/hidden",
                       json={"hidden": False}).status_code == 200

    session.refresh(org)
    assert org.hidden_at is None
    assert org.hidden_reason is None
    assert client.get(f"/api/organizations/{org.id}/public").status_code == 200


def test_the_organization_is_told(client, make_admin, admin_login, make_org,
                                  outbox):
    """Silent removal is what makes people stop trusting a directory -- and it
    does not even buy quiet, since they notice when nobody can find them."""
    org = make_org()
    admin_login(make_admin())
    client.post(f"/api/admin/organizations/{org.id}/hidden",
                json={"hidden": True, "reason": "Testing."})
    assert [kind for kind, _a, _k in outbox] == ["notify_profile_hidden"]


# --- The audit log ---------------------------------------------------------

def test_every_action_is_recorded(client, session, make_admin, admin_login,
                                  make_org):
    admin = make_admin()
    org = make_org(name_flagged=True)
    admin_login(admin)

    client.delete(f"/api/admin/organizations/{org.id}/flag")
    client.post(f"/api/admin/organizations/{org.id}/hidden",
                json={"hidden": True, "reason": "Testing."})

    actions = session.query(AdminAction).filter(
        AdminAction.target_id == org.id).order_by(AdminAction.id).all()
    assert [a.action for a in actions] == [
        "clear_name_flag", "hide_organization"]
    assert all(a.admin_email == admin.email for a in actions)
    assert actions[1].detail["reason"] == "Testing."


def test_a_refused_action_records_nothing(client, session, make_admin,
                                          admin_login, make_org):
    """The log entry and the change it describes are one transaction. An
    action that did not apply must not leave a record saying it did."""
    org = make_org()          # not flagged
    admin_login(make_admin())
    before = session.query(AdminAction).count()

    assert client.delete(
        f"/api/admin/organizations/{org.id}/flag").status_code == 409
    assert session.query(AdminAction).count() == before


def test_the_record_outlives_the_admin(client, session, make_admin,
                                       admin_login, make_org):
    """admin_id is SET NULL with the email kept beside it: removing an admin
    must not quietly erase what they did."""
    admin = make_admin()
    org = make_org(name_flagged=True)
    admin_login(admin)
    client.delete(f"/api/admin/organizations/{org.id}/flag")

    email = admin.email
    session.delete(admin)
    session.commit()

    entry = session.query(AdminAction).filter(
        AdminAction.target_id == org.id).one()
    assert entry.admin_id is None
    assert entry.admin_email == email


# --- Crawlers --------------------------------------------------------------

def test_the_panel_is_kept_out_of_every_index(client):
    assert "Disallow: /admin.html" in client.get("/robots.txt").get_data(as_text=True)
    assert "admin.html" not in client.get("/sitemap.xml").get_data(as_text=True)
    assert 'content="noindex' in client.get("/admin.html").get_data(as_text=True)
