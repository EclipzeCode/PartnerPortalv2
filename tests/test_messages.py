"""Messages on a proposal.

A proposal carried exactly one message and one reply, so two organizations
working out what "event space" actually means had to leave the site and use
the contact email on the card -- which is also where what they agreed stops
being written down.

The thread hangs off the partnership, and that is the whole access rule: you
can write to an organization because there is a live proposal between you,
not because you found them in the directory.
"""

import pytest

from models import Message, Partnership

PASSWORD = "Test1234!verify"


def _propose(client, recipient):
    return client.post("/api/proposals", json={
        "recipient_id": recipient.id,
        "proposer_gives": ["grant_writing"],
        "recipient_gives": ["web_development"],
    })


@pytest.fixture
def thread(client, login, make_org):
    """A pending proposal between two organizations."""
    proposer = make_org(name="pytest-msg Proposer",
                        needs=["web_development"], offers=["grant_writing"])
    recipient = make_org(name="pytest-msg Recipient",
                         needs=["grant_writing"], offers=["web_development"])
    login(proposer)
    created = _propose(client, recipient)
    assert created.status_code == 201
    client.post("/logout")
    return proposer, recipient, created.get_json()["proposal"]["id"]


# --- Who may write ----------------------------------------------------------

def test_both_parties_can_write_and_read(client, login, thread):
    proposer, recipient, pid = thread

    login(proposer)
    assert client.post(f"/api/proposals/{pid}/messages",
                       json={"body": "Which weeks do you need the hall?"}
                       ).status_code == 201
    client.post("/logout")

    login(recipient)
    body = client.get(f"/api/proposals/{pid}/messages").get_json()
    assert body["count"] == 1
    assert body["messages"][0]["body"] == "Which weeks do you need the hall?"
    # Attribution is from the reader's point of view.
    assert body["messages"][0]["mine"] is False
    assert body["messages"][0]["sender_name"] == "pytest-msg Proposer"

    assert client.post(f"/api/proposals/{pid}/messages",
                       json={"body": "The first two of March."}).status_code == 201


def test_an_outsider_cannot_read_or_write(client, login, thread, make_org):
    """Same "not found" every other proposal route gives, so a thread id
    cannot be probed for existence either."""
    _proposer, _recipient, pid = thread
    outsider = make_org(name="pytest-msg Outsider",
                        needs=["legal"], offers=["legal"])
    login(outsider)
    assert client.get(f"/api/proposals/{pid}/messages").status_code == 404
    assert client.post(f"/api/proposals/{pid}/messages",
                       json={"body": "hello"}).status_code == 404


def test_a_thread_needs_a_session(client, thread):
    _proposer, _recipient, pid = thread
    assert client.get(f"/api/proposals/{pid}/messages").status_code == 401


# --- When the thread is open ------------------------------------------------

def test_an_accepted_partnership_keeps_its_thread_open(client, login, thread):
    proposer, recipient, pid = thread
    login(recipient)
    client.post(f"/api/proposals/{pid}/accept", json={})
    assert client.post(f"/api/proposals/{pid}/messages",
                       json={"body": "Great -- let's book it."}).status_code == 201


@pytest.mark.parametrize("close", ["decline", "withdraw"])
def test_a_refused_proposal_closes_its_thread(client, login, thread, close):
    """Declining is a no, and a channel that stays open after a no is the
    unsolicited approach this model avoids everywhere else."""
    proposer, recipient, pid = thread
    actor = recipient if close == "decline" else proposer
    login(actor)
    assert client.post(f"/api/proposals/{pid}/{close}", json={}).status_code == 200

    response = client.post(f"/api/proposals/{pid}/messages",
                           json={"body": "But wait"})
    assert response.status_code == 409
    # Still readable: the record of what was said does not go away.
    assert client.get(f"/api/proposals/{pid}/messages").status_code == 200
    assert client.get(f"/api/proposals/{pid}/messages").get_json()["open"] is False


def test_ending_a_partnership_closes_its_thread(client, login, thread):
    proposer, recipient, pid = thread
    login(recipient)
    client.post(f"/api/proposals/{pid}/accept", json={})
    client.post(f"/api/proposals/{pid}/end", json={})
    assert client.post(f"/api/proposals/{pid}/messages",
                       json={"body": "one more thing"}).status_code == 409


# --- Validation -------------------------------------------------------------

def test_an_empty_message_is_refused(client, login, thread):
    proposer, _recipient, pid = thread
    login(proposer)
    for body in ("", "   "):
        response = client.post(f"/api/proposals/{pid}/messages", json={"body": body})
        assert response.status_code == 400
        assert response.get_json()["field"] == "body"


def test_an_over_long_message_is_refused(client, login, thread):
    proposer, _recipient, pid = thread
    login(proposer)
    response = client.post(f"/api/proposals/{pid}/messages",
                           json={"body": "x" * 5000})
    assert response.status_code == 400
    assert response.get_json()["field"] == "body"


# --- Unread -----------------------------------------------------------------

def test_unread_counts_only_what_the_other_side_sent(client, login, thread):
    proposer, recipient, pid = thread

    login(proposer)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "one"})
    client.post(f"/api/proposals/{pid}/messages", json={"body": "two"})
    # Your own messages are not waiting on you.
    assert client.get("/api/me").get_json()["unread_messages"] == 0
    client.post("/logout")

    login(recipient)
    assert client.get("/api/me").get_json()["unread_messages"] == 2


def test_reading_a_thread_clears_it(client, login, thread):
    proposer, recipient, pid = thread
    login(proposer)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "one"})
    client.post("/logout")

    login(recipient)
    assert client.get("/api/me").get_json()["unread_messages"] == 1
    client.get(f"/api/proposals/{pid}/messages")
    assert client.get("/api/me").get_json()["unread_messages"] == 0


def test_replying_counts_as_reading(client, login, thread):
    """Otherwise a reply leaves the sender's own thread showing unread
    messages they were plainly looking at as they typed."""
    proposer, recipient, pid = thread
    login(proposer)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "one"})
    client.post("/logout")

    login(recipient)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "replying"})
    assert client.get("/api/me").get_json()["unread_messages"] == 0


def test_the_proposal_list_carries_per_thread_counts(client, login, thread):
    proposer, recipient, pid = thread
    login(proposer)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "one"})
    client.post("/logout")

    login(recipient)
    listed = client.get("/api/proposals").get_json()["proposals"][0]
    assert listed["message_count"] == 1
    assert listed["unread_count"] == 1
    assert listed["messages_open"] is True


# --- Notifications ----------------------------------------------------------

def test_the_other_side_is_emailed(client, login, thread, outbox):
    proposer, _recipient, pid = thread
    login(proposer)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "hello"})
    assert [s for s in outbox if s[0] == "notify_message_received"]


def test_a_run_of_messages_is_one_email(client, login, thread, outbox):
    """One email per message makes an ordinary back-and-forth unusable and
    teaches people to filter the address."""
    proposer, _recipient, pid = thread
    login(proposer)
    for body in ("one", "two", "three", "four"):
        client.post(f"/api/proposals/{pid}/messages", json={"body": body})
    assert len([s for s in outbox if s[0] == "notify_message_received"]) == 1


def test_a_reply_to_a_read_thread_notifies_again(client, login, thread, outbox):
    """Somebody who is up to date and then receives a reply should hear about
    it, however recently the last one was sent."""
    proposer, recipient, pid = thread

    login(proposer)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "one"})
    client.post(f"/api/proposals/{pid}/messages", json={"body": "two"})
    assert len([s for s in outbox if s[0] == "notify_message_received"]) == 1
    client.post("/logout")

    # The recipient catches up...
    login(recipient)
    client.get(f"/api/proposals/{pid}/messages")
    client.post("/logout")

    # ...so the next message is the first thing they have not seen.
    login(proposer)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "three"})
    assert len([s for s in outbox if s[0] == "notify_message_received"]) == 2


# --- Surviving a deleted account --------------------------------------------

def test_a_thread_survives_the_other_organization_leaving(
        client, login, thread, session):
    """SET NULL, like the partnership's own party keys: closing an account
    must not delete your half of a conversation the other side is party to."""
    proposer, recipient, pid = thread
    login(proposer)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "before leaving"})
    client.post("/logout")

    login(recipient)
    client.post(f"/api/proposals/{pid}/accept", json={})
    client.post("/logout")

    login(proposer)
    assert client.delete(
        "/api/account", json={"password": PASSWORD}).status_code == 200
    client.post("/logout")

    login(recipient)
    body = client.get(f"/api/proposals/{pid}/messages").get_json()
    assert body["count"] == 1
    assert body["messages"][0]["body"] == "before leaving"
    # The snapshot keeps it readable rather than showing a blank sender.
    assert body["messages"][0]["sender_name"] == "pytest-msg Proposer"
    assert body["messages"][0]["sender_deleted"] is True


def test_deleting_a_pending_proposal_takes_its_thread(client, login, thread, session):
    """A pending proposal is removed outright when its sender leaves, so the
    thread hanging off it goes with it rather than being orphaned."""
    proposer, _recipient, pid = thread
    login(proposer)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "hello"})
    assert client.delete(
        "/api/account", json={"password": PASSWORD}).status_code == 200

    assert session.query(Message).filter(
        Message.partnership_id == pid).count() == 0
    assert session.get(Partnership, pid) is None


# --- What an open thread polls for ------------------------------------------
# The dialog re-reads this endpoint on a timer while it is open, because a
# reply arriving mid-conversation used to stay invisible until the thread was
# closed and opened again. These pin the three things that behaviour rests on.

def test_a_reply_shows_up_on_a_second_read(client, login, thread):
    """The poll's whole purpose: the same GET, later, returns the new message."""
    proposer, recipient, pid = thread

    login(proposer)
    first = client.get(f"/api/proposals/{pid}/messages").get_json()
    assert first["count"] == 0
    assert first["open"] is True

    # The other side replies while the first is sitting on the open thread.
    client.post("/logout")
    login(recipient)
    assert client.post(f"/api/proposals/{pid}/messages",
                       json={"body": "pytest reply"}).status_code == 201
    client.post("/logout")

    login(proposer)
    second = client.get(f"/api/proposals/{pid}/messages").get_json()
    assert second["count"] == 1
    assert second["messages"][0]["body"] == "pytest reply"
    # Ordered oldest-first with a stable id, which is what the client's
    # "has anything changed" check keys on.
    assert second["messages"][0]["id"] is not None


def test_polling_keeps_the_thread_marked_read(client, login, thread):
    """Re-reading an open thread is reading it, so the badge must stay down."""
    proposer, recipient, pid = thread

    login(recipient)
    client.post(f"/api/proposals/{pid}/messages", json={"body": "pytest one"})
    client.post("/logout")

    login(proposer)
    assert client.get("/api/me").get_json()["unread_messages"] == 1
    client.get(f"/api/proposals/{pid}/messages")            # opening it
    assert client.get("/api/me").get_json()["unread_messages"] == 0
    client.get(f"/api/proposals/{pid}/messages")            # a poll
    assert client.get("/api/me").get_json()["unread_messages"] == 0


def test_the_open_flag_turns_over_when_the_proposal_settles(client, login, thread):
    """A proposal can settle while its thread is on screen.

    The client swaps the compose form for the closed notice on this flag, so
    it has to change without the thread being reopened -- otherwise the form
    stays up and fails on submit.
    """
    proposer, recipient, pid = thread

    login(proposer)
    assert client.get(f"/api/proposals/{pid}/messages").get_json()["open"] is True
    client.post("/logout")

    login(recipient)
    assert client.post(f"/api/proposals/{pid}/decline", json={}).status_code == 200
    client.post("/logout")

    login(proposer)
    settled = client.get(f"/api/proposals/{pid}/messages").get_json()
    assert settled["open"] is False
    # Still readable: closing a thread is not the same as hiding it.
    assert settled["count"] == 0
