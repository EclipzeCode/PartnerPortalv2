"""Meetings arranged inside a conversation, to both calendars.

A meeting with a partnership_id belongs to the partnership: proposed from
the thread, waiting on one side at a time, accepted, moved or declined
there, and visible to both parties once it exists. Every step is a message
of kind 'meeting' in the thread. These tests pin the turn-taking, who sees
what on their dashboard, and what the personal-meeting routes refuse.
"""

import pytest


def _propose(client, recipient):
    return client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    })


@pytest.fixture
def thread(client, login, make_org):
    proposer = make_org(name="pytest-meet Proposer",
                        needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(name="pytest-meet Recipient",
                         needs=["grant_writing"], offers=["web_development"])
    login(proposer)
    created = _propose(client, recipient)
    assert created.status_code == 201
    client.post("/logout")
    return proposer, recipient, created.get_json()["proposal"]["id"]


MEETING = {
    "title": "Kick-off call", "date": "2027-03-10", "time": "15:00",
    "duration": 1, "timezone": "America/Chicago", "location": "Video call",
}


def _dashboard_events(client):
    return client.get("/api/events").get_json()["events"]


def test_a_proposed_meeting_reaches_both_calendars_once_accepted(
        client, login, thread, outbox):
    proposer, recipient, pid = thread

    login(proposer)
    outbox.clear()
    sent = client.post(f"/api/proposals/{pid}/meetings", json=MEETING)
    assert sent.status_code == 201
    meeting = sent.get_json()["meeting"]
    mid = meeting["id"]
    assert meeting["shared"]["status"] == "proposed"
    assert meeting["shared"]["awaiting_them"] is True
    assert meeting["partner"] == "pytest-meet Recipient"
    # The thread got a card, and the other side an email.
    kinds = [m["kind"] for m in
             client.get(f"/api/proposals/{pid}/messages").get_json()["messages"]]
    assert kinds == ["meeting"]
    assert [k for k, _, _ in outbox] == ["notify_meeting_update"]
    assert outbox[0][1][3] == "proposed"
    # On the proposer's dashboard, marked as waiting on the other side.
    mine = [e for e in _dashboard_events(client) if e["id"] == mid]
    assert mine and mine[0]["shared"]["awaiting_you"] is False
    # The proposer cannot answer their own proposal.
    assert client.post(f"/api/proposals/{pid}/meetings/{mid}/accept").status_code == 403
    client.post("/logout")

    login(recipient)
    # Visible to the recipient, from their side, waiting on them.
    theirs = [e for e in _dashboard_events(client) if e["id"] == mid]
    assert theirs and theirs[0]["shared"]["awaiting_you"] is True
    assert theirs[0]["partner"] == "pytest-meet Proposer"
    assert client.get("/api/me").get_json()["awaiting_meetings"] == 1
    bell = client.get("/api/notifications").get_json()
    assert any(n["kind"] == "meeting_proposed" for n in bell["notifications"])

    outbox.clear()
    accepted = client.post(f"/api/proposals/{pid}/meetings/{mid}/accept")
    assert accepted.status_code == 200
    assert accepted.get_json()["meeting"]["shared"]["status"] == "accepted"
    assert outbox[0][1][3] == "accepted"
    assert client.get("/api/me").get_json()["awaiting_meetings"] == 0
    # Both can download it, and it is the same event.
    ics = client.get(f"/api/events/{mid}.ics")
    assert ics.status_code == 200
    assert f"UID:event-{mid}@" in ics.get_data(as_text=True)
    assert "With pytest-meet Proposer" in ics.get_data(as_text=True)
    client.post("/logout")

    login(proposer)
    ics = client.get(f"/api/events/{mid}.ics").get_data(as_text=True)
    assert f"UID:event-{mid}@" in ics
    assert "With pytest-meet Recipient" in ics


def test_moving_a_meeting_hands_the_turn_back(client, login, thread):
    proposer, recipient, pid = thread
    login(proposer)
    mid = client.post(f"/api/proposals/{pid}/meetings",
                      json=MEETING).get_json()["meeting"]["id"]
    client.post("/logout")

    login(recipient)
    # A different time is a counter: it now waits on the proposer.
    moved = client.patch(f"/api/proposals/{pid}/meetings/{mid}",
                         json={"date": "2027-03-11", "time": "10:00"})
    assert moved.status_code == 200
    body = moved.get_json()["meeting"]
    assert body["date"] == "2027-03-11" and body["time"] == "10:00"
    assert body["shared"]["status"] == "proposed"
    assert body["shared"]["awaiting_you"] is False
    # Having countered, the recipient cannot also accept.
    assert client.post(f"/api/proposals/{pid}/meetings/{mid}/accept").status_code == 403
    client.post("/logout")

    login(proposer)
    mine = client.get("/api/events").get_json()["events"]
    row = next(e for e in mine if e["id"] == mid)
    assert row["shared"]["awaiting_you"] is True
    assert client.post(f"/api/proposals/{pid}/meetings/{mid}/accept").status_code == 200

    # Once agreed, a move by either side reopens it...
    reopened = client.patch(f"/api/proposals/{pid}/meetings/{mid}",
                            json={"time": "11:00"})
    assert reopened.get_json()["meeting"]["shared"]["status"] == "proposed"
    assert reopened.get_json()["meeting"]["shared"]["awaiting_you"] is False
    client.post("/logout")
    login(recipient)
    assert client.post(f"/api/proposals/{pid}/meetings/{mid}/accept").status_code == 200
    # ...while a change to the words does not.
    words = client.patch(f"/api/proposals/{pid}/meetings/{mid}",
                         json={"location": "Their office", "title": "Kick-off"})
    assert words.status_code == 200
    assert words.get_json()["meeting"]["shared"]["status"] == "accepted"
    assert words.get_json()["meeting"]["location"] == "Their office"


def test_declined_and_cancelled_meetings_leave_both_calendars(
        client, login, thread):
    proposer, recipient, pid = thread
    login(proposer)
    first = client.post(f"/api/proposals/{pid}/meetings",
                        json=MEETING).get_json()["meeting"]["id"]
    second = client.post(f"/api/proposals/{pid}/meetings",
                         json={**MEETING, "title": "Site visit"}).get_json()["meeting"]["id"]
    # The proposer can take back their own before an answer.
    assert client.post(f"/api/proposals/{pid}/meetings/{second}/cancel").status_code == 200
    assert client.post(f"/api/proposals/{pid}/meetings/{second}/cancel").status_code == 409
    client.post("/logout")

    login(recipient)
    ids = {e["id"] for e in _dashboard_events(client)}
    assert first in ids and second not in ids
    assert client.post(f"/api/proposals/{pid}/meetings/{first}/decline").status_code == 200
    assert first not in {e["id"] for e in _dashboard_events(client)}
    # The thread keeps the record: proposed, proposed, cancelled, declined.
    bodies = [m["body"] for m in
              client.get(f"/api/proposals/{pid}/messages").get_json()["messages"]]
    assert [b.split(" ")[0] for b in bodies] == ["Proposed", "Proposed", "Cancelled", "Declined"]
    client.post("/logout")

    login(proposer)
    assert first not in {e["id"] for e in _dashboard_events(client)}


def test_the_personal_routes_refuse_a_shared_meeting(client, login, thread):
    proposer, recipient, pid = thread
    login(proposer)
    mid = client.post(f"/api/proposals/{pid}/meetings",
                      json=MEETING).get_json()["meeting"]["id"]
    # Editing or deleting it as if it were a private note is refused with a
    # pointer at the conversation -- for the proposer too, who is its owner.
    edited = client.patch(f"/api/events/{mid}", json={"title": "Sneaky"})
    assert edited.status_code == 409 and edited.get_json()["shared"] is True
    assert client.delete(f"/api/events/{mid}").status_code == 409
    client.post("/logout")

    # A stranger sees nothing at all.
    login(recipient)
    assert client.patch(f"/api/events/{mid}", json={"title": "x"}).status_code == 409
    client.post("/logout")


def test_a_stranger_cannot_touch_a_shared_meeting(client, login, thread, make_org):
    proposer, recipient, pid = thread
    login(proposer)
    mid = client.post(f"/api/proposals/{pid}/meetings",
                      json=MEETING).get_json()["meeting"]["id"]
    client.post("/logout")

    login(make_org(name="pytest-meet Stranger"))
    assert client.get(f"/api/events/{mid}.ics").status_code == 404
    assert client.patch(f"/api/events/{mid}", json={"title": "x"}).status_code == 404
    assert client.post(f"/api/proposals/{pid}/meetings/{mid}/accept").status_code == 404
    assert client.post(f"/api/proposals/{pid}/meetings", json=MEETING).status_code == 404


def test_ending_the_partnership_cancels_what_was_never_agreed(
        client, login, thread):
    proposer, recipient, pid = thread
    login(recipient)
    assert client.post(f"/api/proposals/{pid}/accept").status_code == 200
    agreed = client.post(f"/api/proposals/{pid}/meetings",
                         json=MEETING).get_json()["meeting"]["id"]
    pending = client.post(f"/api/proposals/{pid}/meetings",
                          json={**MEETING, "title": "Follow-up"}).get_json()["meeting"]["id"]
    client.post("/logout")

    login(proposer)
    assert client.post(f"/api/proposals/{pid}/meetings/{agreed}/accept").status_code == 200
    assert client.post(f"/api/proposals/{pid}/end", json={"reason": "moving on"}).status_code == 200

    shown = {e["id"]: e for e in _dashboard_events(client)}
    # The agreed one stays, flagged; the one nobody answered is gone.
    assert agreed in shown and shown[agreed]["shared"]["status"] == "accepted"
    assert shown[agreed]["shared"]["partnership_status"] == "ended"
    assert pending not in shown
    # And nothing further can be arranged in a closed conversation.
    assert client.post(f"/api/proposals/{pid}/meetings", json=MEETING).status_code == 409


def test_a_meeting_needs_the_same_things_a_private_one_does(client, login, thread):
    proposer, recipient, pid = thread
    login(proposer)
    missing = client.post(f"/api/proposals/{pid}/meetings",
                          json={"title": "", "date": "nope"})
    assert missing.status_code == 400
    assert "a title" in missing.get_json()["error"]
    assert "a valid date" in missing.get_json()["error"]
    all_day = client.post(f"/api/proposals/{pid}/meetings",
                          json={"title": "Open day", "date": "2027-04-01", "all_day": True})
    assert all_day.status_code == 201
    assert all_day.get_json()["meeting"]["all_day"] is True


@pytest.mark.parametrize("settle, who", [("decline", "recipient"),
                                         ("withdraw", "proposer")])
def test_settling_the_proposal_withdraws_its_proposed_meetings(
        client, login, thread, settle, who):
    """A proposed meeting is a question asked inside the conversation, so it
    goes when the conversation does. It used to stay: on both dashboards as
    "waiting on you", as an actionable bell entry indefinitely, and still
    answerable from a thread every other route said was closed."""
    proposer, recipient, pid = thread

    login(proposer)
    mid = client.post(f"/api/proposals/{pid}/meetings",
                      json=MEETING).get_json()["meeting"]["id"]
    client.post("/logout")

    actor = recipient if who == "recipient" else proposer
    login(actor)
    assert client.post(f"/api/proposals/{pid}/{settle}").status_code == 200
    client.post("/logout")

    # Gone from both calendars, and no longer counted against anybody.
    for org in (proposer, recipient):
        login(org)
        assert mid not in [e["id"] for e in _dashboard_events(client)]
        me = client.get("/api/me").get_json()
        assert me["awaiting_meetings"] == 0
        kinds = [n["kind"] for n in
                 client.get("/api/notifications").get_json()["notifications"]]
        assert "meeting_proposed" not in kinds
        client.post("/logout")

    # And it cannot be answered from the closed thread.
    login(recipient)
    assert client.post(
        f"/api/proposals/{pid}/meetings/{mid}/accept").status_code == 409
