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
    ("post", "/api/admin/reports/1/handled"),
    ("get", "/api/admin/reports/1/thread"),
    ("delete", "/api/admin/organizations/1/flag"),
    ("post", "/api/admin/organizations/1/hidden"),
    ("get", "/api/admin/organizations/1"),
    ("patch", "/api/admin/organizations/1"),
    ("post", "/api/admin/organizations/1/listed"),
    ("post", "/api/admin/organizations"),
    ("post", "/api/admin/organizations/1/claim-link"),
    ("post", "/api/admin/organizations/1/email"),
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


def test_an_organization_deleting_itself_leaves_the_admin_signed_in(
        client, make_admin, admin_login, make_org, login):
    """Deleting the account used to clear the whole session, admin and all."""
    from conftest import PASSWORD
    org = make_org()
    login(org)
    admin_login(make_admin())

    response = client.delete("/api/account", json={"password": PASSWORD})
    assert response.status_code == 200

    assert client.get("/api/me").status_code == 401
    assert client.get("/api/admin/overview").status_code == 200


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
    assert "Disallow: /admin" in client.get("/robots.txt").get_data(as_text=True)
    assert "/admin" not in client.get("/sitemap.xml").get_data(as_text=True)
    assert 'content="noindex' in client.get("/admin").get_data(as_text=True)


# --- Reading a reported conversation -----------------------------------------

def _reported_thread(client, login, make_org):
    """Two organizations, a proposal, two messages, and a report on it.
    Returns (reporter, reported, report id, proposal id)."""
    from models import ThreadReport
    reporter = make_org(offers=["mentors"], needs=["web_development"])
    reported = make_org(offers=["web_development"], needs=["mentors"])
    login(reported)
    pid = client.post("/api/proposals", json={
        "recipient_id": reporter.id,
        "proposer_gives": ["web_development"], "recipient_gives": ["mentors"],
    }).get_json()["proposal"]["id"]
    client.post(f"/api/proposals/{pid}/messages", json={"body": "Pay us first."})
    client.post("/logout")
    login(reporter)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "That is not how this works."})
    assert client.post(f"/api/proposals/{pid}/report",
                       json={"reason": "Asking for money up front."}).status_code == 201
    client.post("/logout")
    return reporter, reported, pid


def test_an_admin_can_read_the_conversation_a_report_names(
        client, session, make_admin, admin_login, make_org, login):
    from models import AdminAction, ThreadReport
    reporter, reported, pid = _reported_thread(client, login, make_org)
    report = session.query(ThreadReport).filter(
        ThreadReport.partnership_id == pid).one()

    admin = make_admin()
    admin_login(admin)
    response = client.get(f"/api/admin/reports/{report.id}/thread")
    assert response.status_code == 200
    data = response.get_json()
    assert [m["body"] for m in data["messages"]] == [
        "Pay us first.", "That is not how this works."]
    assert [m["sender_name"] for m in data["messages"]] == [
        reported.name, reporter.name]
    assert data["partnership"]["id"] == pid
    assert data["report"]["reason"] == "Asking for money up front."

    # Reading is an action, and is in the log as one.
    logged = session.query(AdminAction).filter(
        AdminAction.action == "read_reported_thread",
        AdminAction.target_id == report.id).one()
    assert logged.admin_email == admin.email
    assert logged.detail["partnership_id"] == pid


def test_a_report_is_the_only_way_to_a_thread(
        client, session, make_admin, admin_login, make_org, login):
    """No route serves a thread by partnership id to an admin: the report is
    the key, and a report id that names no report is a 404."""
    reporter, reported, pid = _reported_thread(client, login, make_org)
    admin_login(make_admin())
    assert client.get(f"/api/admin/reports/999999/thread").status_code == 404
    assert client.get(f"/api/proposals/{pid}/messages").status_code == 401


def test_a_report_on_a_deleted_conversation_says_so(
        client, session, make_admin, admin_login, make_org, login):
    from models import ThreadReport
    reporter, reported, pid = _reported_thread(client, login, make_org)
    report = session.query(ThreadReport).filter(
        ThreadReport.partnership_id == pid).one()
    # The proposal goes with the proposer's account (it was never accepted).
    login(reported)
    from conftest import PASSWORD
    assert client.delete("/api/account", json={"password": PASSWORD}).status_code == 200
    client.post("/logout")

    admin_login(make_admin())
    session.expire_all()
    response = client.get(f"/api/admin/reports/{report.id}/thread")
    assert response.status_code == 410


# --- Editing a profile -----------------------------------------------------

def test_an_admin_edits_only_what_was_sent_and_it_is_logged(
        client, make_admin, admin_login, make_org, session):
    # contact_email set, as onboarding always leaves it.
    org = make_org(name="pytest Before", offers=["volunteers"],
                   needs=["mentors"], website_url="https://before.example",
                   contact_email="hello@before.example")
    admin_login(make_admin())

    response = client.patch(f"/api/admin/organizations/{org.id}", json={
        "organization_name": "pytest After", "offers": ["legal"]})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["changed"] == ["offers", "organization_name"]

    session.refresh(org)
    assert org.name == "pytest After" and org.offers == ["legal"]
    # Everything not sent is untouched.
    assert org.needs == ["mentors"]
    assert org.website_url == "https://before.example"

    log = session.query(AdminAction).filter(
        AdminAction.target_id == org.id).one()
    assert log.action == "edit_organization"
    assert log.detail["fields"] == ["offers", "organization_name"]


def test_admin_edits_follow_the_onboarding_rules(
        client, make_admin, admin_login, make_org):
    org = make_org()
    admin_login(make_admin())
    url = f"/api/admin/organizations/{org.id}"
    # A finished profile keeps the onboarding minimum.
    assert client.patch(url, json={"needs": []}).status_code == 400
    assert client.patch(url, json={"website_url": "not a url"}).status_code == 400
    assert client.patch(url, json={"contact_email": "nope"}).status_code == 400
    # Sign-in and publishing choices are not editable here.
    assert client.patch(url, json={"email": "x@example.com"}).status_code == 400
    assert client.patch(url, json={"links_public": True}).status_code == 400
    assert client.patch(url, json={}).status_code == 400   # nothing changed


def test_an_unclaimed_invitation_can_be_edited_while_incomplete(
        client, make_admin, admin_login, make_org, session):
    invite = make_org(name="pytest Invite", onboarding_complete=False,
                      organization_type=None, location=None,
                      claim_token_hash="pytest-" + "1" * 57)
    invite.email = "invite-pytest@invite.invalid"
    session.commit()
    admin_login(make_admin())
    response = client.patch(f"/api/admin/organizations/{invite.id}",
                            json={"description": "A food pantry in Somerville."})
    assert response.status_code == 200, response.get_json()
    session.refresh(invite)
    assert invite.contact_email is None    # never the placeholder address

    overview = client.get("/api/admin/overview").get_json()
    row = next(o for o in overview["organizations"] if o["id"] == invite.id)
    assert row["invited"] is True


def test_an_invitation_is_listed_once_its_profile_is_complete(
        client, make_admin, admin_login, make_org, session):
    invite = make_org(name="pytest Listed Invite", onboarding_complete=False,
                      organization_type=None,
                      claim_token_hash="pytest-" + "2" * 57)
    invite.email = "invite-pytest2@invite.invalid"
    session.commit()
    admin_login(make_admin())
    url = f"/api/admin/organizations/{invite.id}/listed"

    assert client.post(url, json={"listed": True}).status_code == 400
    session.refresh(invite)
    assert invite.onboarding_complete is False      # still incomplete

    client.patch(f"/api/admin/organizations/{invite.id}",
                 json={"organization_type": "Non-profit",
                       "needs": ["volunteers"], "offers": ["event_space"]})
    response = client.post(url, json={"listed": True})
    assert response.status_code == 200, response.get_json()
    session.refresh(invite)
    assert invite.onboarding_complete is True
    assert client.get(f"/api/organizations/{invite.id}/public").status_code == 200

    assert client.post(url, json={"listed": False}).status_code == 200
    # A claimed account that stalled in onboarding can be listed, keeping its
    # contact address empty; it is taken down with Hide, not unlisted.
    stalled = make_org(onboarding_complete=False, needs=["volunteers"],
                       offers=["event_space"])
    assert stalled.contact_email is None
    response = client.post(f"/api/admin/organizations/{stalled.id}/listed",
                           json={"listed": True})
    assert response.status_code == 200, response.get_json()
    session.refresh(stalled)
    assert stalled.onboarding_complete is True
    assert stalled.contact_email is None
    assert client.post(f"/api/admin/organizations/{stalled.id}/listed",
                       json={"listed": False}).status_code == 409


def test_a_reordered_list_or_an_empty_contact_is_not_an_edit(
        client, make_admin, admin_login, make_org, session):
    org = make_org(offers=["volunteers", "legal"], needs=["mentors"])
    assert org.contact_email is None
    admin_login(make_admin())
    url = f"/api/admin/organizations/{org.id}"

    assert client.patch(url, json={"offers": ["legal", "volunteers"]}
                        ).status_code == 400            # nothing changed
    response = client.patch(url, json={"location": "Newark, NJ"})
    assert response.get_json()["changed"] == ["location"]
    session.refresh(org)
    assert org.contact_email is None

    log = session.query(AdminAction).filter(
        AdminAction.target_id == org.id).one()
    assert log.detail["before"] == {"location": "Testville, TS"}


def test_a_business_added_without_an_email_can_be_claimed(
        client, make_admin, admin_login, session):
    admin_login(make_admin())
    response = client.post("/api/admin/organizations",
                           json={"name": "pytest No Email Co"})
    assert response.status_code == 201, response.get_json()
    org_id = response.get_json()["organization"]["id"]
    assert client.post("/api/admin/organizations",
                       json={"name": "PYTEST no email co"}).status_code == 409

    first = client.post(f"/api/admin/organizations/{org_id}/claim-link")
    second = client.post(f"/api/admin/organizations/{org_id}/claim-link")
    old = first.get_json()["invite"]["claim_url"].split("token=")[1]
    new = second.get_json()["invite"]["claim_url"].split("token=")[1]
    assert client.get(f"/api/invites/{old}").status_code == 404
    assert client.get(f"/api/invites/{new}").get_json()["invite"]["invited_by"] is None

    claimed = client.post(f"/api/invites/{new}/claim", json={
        "email": "pytest-noemail@example.com", "password": "Claim-1234!pass"})
    assert claimed.status_code == 201, claimed.get_json()
    assert client.post(f"/api/admin/organizations/{org_id}/claim-link"
                       ).status_code == 409


def test_an_admin_moves_a_claimed_sign_in(
        client, make_admin, admin_login, make_org, session, outbox):
    org, other = make_org(), make_org()
    previous = org.email
    org.contact_email = previous
    org.email_verified = True
    org.password_reset_token_hash = "pytest-" + "3" * 57
    session.commit()
    admin_login(make_admin())
    url = f"/api/admin/organizations/{org.id}/email"

    assert client.post(url, json={"email": "nope"}).status_code == 400
    assert client.post(url, json={"email": other.email}).status_code == 409
    assert client.post(url, json={"email": previous}).status_code == 400

    response = client.post(url, json={"email": "Pytest-Moved@Example.com"})
    assert response.status_code == 200, response.get_json()
    session.refresh(org)
    assert org.email == org.contact_email == "pytest-moved@example.com"
    assert org.email_verified is False
    assert org.password_reset_token_hash is None
    sent = {kind: args for kind, args, _ in outbox}
    assert sent["notify_email_changed_by_admin"][1] == previous
    assert "notify_email_verification" in sent


def test_an_unclaimed_email_gets_a_fresh_link_and_keeps_its_placeholder(
        client, make_admin, admin_login, make_org, session, outbox):
    invite = make_org(name="pytest Mail Invite", onboarding_complete=False,
                      claim_token_hash="pytest-" + "4" * 57)
    invite.email = "invite-pytest4@invite.invalid"
    session.commit()
    admin_login(make_admin())
    response = client.post(f"/api/admin/organizations/{invite.id}/email",
                           json={"email": "owner@example.com"})
    assert response.status_code == 200, response.get_json()
    session.refresh(invite)
    assert invite.email == "invite-pytest4@invite.invalid"
    assert invite.claim_token_hash != "pytest-" + "4" * 57
    assert [args[2] for kind, args, _ in outbox
            if kind == "notify_invitation"] == ["owner@example.com"]
