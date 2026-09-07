"""Moving and cancelling a single occurrence of a repeating meeting.

Editing was series-only, so "we are skipping next week" and "move just this
week to Thursday" both meant ending the series and starting another. An
EventException records the difference instead.

Two shapes and only two -- cancelled, or moved -- and the interesting cases
are all about the boundary between an occurrence and the series it belongs
to: that moving one does not move the others, that the occurrence keeps its
identity when it moves so a second edit finds it again, and that the series
can still be edited as a whole afterwards.
"""

from datetime import date, timedelta

import pytest

from models import Event, EventException


def _monday(weeks_ahead=1):
    """A Monday comfortably inside the dashboard's window."""
    today = date.today()
    ahead = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    return ahead + timedelta(weeks=weeks_ahead)


@pytest.fixture
def weekly(client, session, make_org, login):
    """A weekly meeting running for eight weeks, and a signed-in client."""
    org = make_org()
    c = login(org)
    start = _monday()
    response = c.post("/api/events", json={
        "title": "pytest standing check-in",
        "partner": "pytest partner",
        "date": start.strftime("%Y-%m-%d"),
        "time": "14:00",
        "duration": 1,
        "repeat": "weekly",
        "repeat_until": (start + timedelta(weeks=7)).strftime("%Y-%m-%d"),
    })
    assert response.status_code == 201, response.get_data(as_text=True)
    return c, response.get_json()["event"], start


def _occurrences(client):
    return client.get("/api/events").get_json()["events"]


def test_moving_one_occurrence_leaves_the_rest_alone(weekly, session):
    client, event, start = weekly
    third = start + timedelta(weeks=2)
    moved_to = third + timedelta(days=3)

    response = client.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence",
        "occurrence": third.strftime("%Y-%m-%d"),
        "date": moved_to.strftime("%Y-%m-%d"),
        "time": "10:30",
    })
    assert response.status_code == 200, response.get_data(as_text=True)

    rows = _occurrences(client)
    dates = {r["date"] for r in rows}
    assert moved_to.strftime("%Y-%m-%d") in dates
    assert third.strftime("%Y-%m-%d") not in dates
    # The other seven are untouched, at the series' own time.
    others = [r for r in rows if r["date"] != moved_to.strftime("%Y-%m-%d")]
    assert len(others) == 7
    assert {r["time"] for r in others} == {"14:00"}

    moved = next(r for r in rows if r["date"] == moved_to.strftime("%Y-%m-%d"))
    assert moved["time"] == "10:30"
    assert moved["moved"] is True
    # Its identity is still the date the series lands on, not where it went.
    assert moved["occurs_on"] == third.strftime("%Y-%m-%d")
    assert moved["id"] == event["id"]


def test_cancelling_one_occurrence_skips_only_that_week(weekly):
    client, event, start = weekly
    skipped = start + timedelta(weeks=3)

    response = client.delete(
        f"/api/events/{event['id']}"
        f"?scope=occurrence&occurrence={skipped.strftime('%Y-%m-%d')}")
    assert response.status_code == 200, response.get_data(as_text=True)

    rows = _occurrences(client)
    assert len(rows) == 7
    assert skipped.strftime("%Y-%m-%d") not in {r["date"] for r in rows}
    # The series itself is still there, either side of the gap.
    assert (skipped - timedelta(weeks=1)).strftime("%Y-%m-%d") in {
        r["date"] for r in rows}
    assert (skipped + timedelta(weeks=1)).strftime("%Y-%m-%d") in {
        r["date"] for r in rows}


def test_moving_the_same_occurrence_twice_edits_one_exception(weekly, session):
    """The second move addresses it by its original date, not by where it went.

    Otherwise a week moved twice becomes two meetings: one exception for the
    real occurrence and another for a date the series never lands on.
    """
    client, event, start = weekly
    third = start + timedelta(weeks=2)

    for offset, at in ((3, "10:30"), (1, "16:00")):
        response = client.patch(f"/api/events/{event['id']}", json={
            "scope": "occurrence",
            "occurrence": third.strftime("%Y-%m-%d"),
            "date": (third + timedelta(days=offset)).strftime("%Y-%m-%d"),
            "time": at,
        })
        assert response.status_code == 200, response.get_data(as_text=True)

    assert session.query(EventException).filter(
        EventException.event_id == event["id"]).count() == 1

    rows = _occurrences(client)
    assert len(rows) == 8
    landed = next(r for r in rows if r["occurs_on"] == third.strftime("%Y-%m-%d"))
    assert landed["date"] == (third + timedelta(days=1)).strftime("%Y-%m-%d")
    assert landed["time"] == "16:00"


def test_an_unstated_field_keeps_what_the_occurrence_already_had(weekly):
    """Not what the series has -- otherwise a second edit springs it back."""
    client, event, start = weekly
    third = start + timedelta(weeks=2)

    client.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence", "occurrence": third.strftime("%Y-%m-%d"),
        "date": third.strftime("%Y-%m-%d"), "time": "09:15",
    })
    # Now move the date only. The 09:15 has to survive.
    client.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence", "occurrence": third.strftime("%Y-%m-%d"),
        "date": (third + timedelta(days=2)).strftime("%Y-%m-%d"),
    })

    rows = _occurrences(client)
    moved = next(r for r in rows if r["occurs_on"] == third.strftime("%Y-%m-%d"))
    assert moved["time"] == "09:15"
    assert moved["date"] == (third + timedelta(days=2)).strftime("%Y-%m-%d")


def test_cancelling_an_occurrence_that_was_moved_clears_where_it_went(
        weekly, session):
    """The constraint requires a cancellation to carry no schedule."""
    client, event, start = weekly
    third = start + timedelta(weeks=2)

    client.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence", "occurrence": third.strftime("%Y-%m-%d"),
        "date": (third + timedelta(days=3)).strftime("%Y-%m-%d"),
    })
    response = client.delete(
        f"/api/events/{event['id']}"
        f"?scope=occurrence&occurrence={third.strftime('%Y-%m-%d')}")
    assert response.status_code == 200

    row = session.query(EventException).filter(
        EventException.event_id == event["id"]).one()
    assert row.cancelled is True
    assert (row.date, row.time, row.duration, row.all_day) == (
        None, None, None, None)
    assert len(_occurrences(client)) == 7


def test_the_whole_series_can_still_be_deleted(weekly, session):
    client, event, start = weekly
    client.delete(
        f"/api/events/{event['id']}"
        f"?scope=occurrence&occurrence="
        f"{(start + timedelta(weeks=2)).strftime('%Y-%m-%d')}")

    response = client.delete(f"/api/events/{event['id']}")
    assert response.status_code == 200
    assert _occurrences(client) == []
    # The exception went with it rather than being left pointing at nothing.
    assert session.query(EventException).filter(
        EventException.event_id == event["id"]).count() == 0


def test_editing_the_series_still_moves_every_unexcepted_occurrence(weekly):
    client, event, start = weekly
    third = start + timedelta(weeks=2)
    client.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence", "occurrence": third.strftime("%Y-%m-%d"),
        "date": third.strftime("%Y-%m-%d"), "time": "09:15",
    })

    response = client.patch(f"/api/events/{event['id']}", json={"time": "17:00"})
    assert response.status_code == 200

    rows = _occurrences(client)
    by_occurrence = {r["occurs_on"]: r for r in rows}
    assert by_occurrence[start.strftime("%Y-%m-%d")]["time"] == "17:00"
    # The excepted one keeps what it was given. An exception states its own
    # schedule outright, so a series edit does not reach into it.
    assert by_occurrence[third.strftime("%Y-%m-%d")]["time"] == "09:15"


def test_an_occurrence_the_series_never_lands_on_is_refused(weekly):
    client, event, start = weekly
    not_a_monday = start + timedelta(days=2)

    response = client.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence",
        "occurrence": not_a_monday.strftime("%Y-%m-%d"),
        "date": not_a_monday.strftime("%Y-%m-%d"),
    })
    assert response.status_code == 400
    assert "repeats on" in response.get_json()["error"]


def test_scope_occurrence_needs_to_say_which_one(weekly):
    client, event, _start = weekly
    response = client.patch(f"/api/events/{event['id']}",
                            json={"scope": "occurrence", "time": "10:00"})
    assert response.status_code == 400
    assert "which occurrence" in response.get_json()["error"]


def test_an_unknown_scope_is_refused(weekly):
    client, event, _start = weekly
    response = client.patch(f"/api/events/{event['id']}",
                            json={"scope": "everything", "time": "10:00"})
    assert response.status_code == 400
    assert "series or occurrence" in response.get_json()["error"]


def test_what_a_meeting_is_cannot_be_changed_for_one_occurrence(weekly):
    """Refused rather than ignored -- see the model for why only four fields."""
    client, event, start = weekly
    third = start + timedelta(weeks=2)

    response = client.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence", "occurrence": third.strftime("%Y-%m-%d"),
        "title": "pytest different title",
    })
    assert response.status_code == 400
    assert "Edit the series" in response.get_json()["error"]
    # ...and nothing was written on the way to refusing.
    rows = _occurrences(client)
    assert {r["title"] for r in rows} == {"pytest standing check-in"}


def test_a_one_off_ignores_the_scope(client, make_org, login):
    """There is no distinction to draw, so asking for one is not an error."""
    org = make_org()
    c = login(org)
    when = _monday()
    created = c.post("/api/events", json={
        "title": "pytest one off", "partner": "pytest partner",
        "date": when.strftime("%Y-%m-%d"), "time": "11:00",
    }).get_json()["event"]

    response = c.patch(f"/api/events/{created['id']}",
                       json={"scope": "occurrence", "time": "12:00"})
    assert response.status_code == 200
    assert response.get_json()["event"]["time"] == "12:00"

    # And deleting it really deletes it rather than cancelling one occurrence.
    assert c.delete(f"/api/events/{created['id']}?scope=occurrence"
                    ).status_code == 200
    assert _occurrences(c) == []


def test_another_organization_cannot_touch_an_occurrence(weekly, make_org,
                                                         login, client):
    _owner_client, event, start = weekly
    intruder = login(make_org())
    third = start + timedelta(weeks=2)

    assert intruder.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence", "occurrence": third.strftime("%Y-%m-%d"),
        "time": "08:00",
    }).status_code == 404
    assert intruder.delete(
        f"/api/events/{event['id']}?scope=occurrence"
        f"&occurrence={third.strftime('%Y-%m-%d')}").status_code == 404


def test_a_moved_occurrence_is_counted_once(weekly):
    """The total is what the "view all" control says, so it must not drift."""
    client, event, start = weekly
    payload = client.get("/api/events").get_json()
    assert payload["total"] == 8

    third = start + timedelta(weeks=2)
    client.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence", "occurrence": third.strftime("%Y-%m-%d"),
        "date": (third + timedelta(days=3)).strftime("%Y-%m-%d"),
    })
    assert client.get("/api/events").get_json()["total"] == 8

    client.delete(f"/api/events/{event['id']}?scope=occurrence"
                  f"&occurrence={third.strftime('%Y-%m-%d')}")
    assert client.get("/api/events").get_json()["total"] == 7


def test_the_calendar_export_carries_both_kinds(weekly):
    """A cancellation is an EXDATE; a move is a RECURRENCE-ID override."""
    client, event, start = weekly
    skipped = start + timedelta(weeks=1)
    moved = start + timedelta(weeks=2)

    client.delete(f"/api/events/{event['id']}?scope=occurrence"
                  f"&occurrence={skipped.strftime('%Y-%m-%d')}")
    client.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence", "occurrence": moved.strftime("%Y-%m-%d"),
        "date": (moved + timedelta(days=3)).strftime("%Y-%m-%d"),
        "time": "10:30",
    })

    body = client.get(f"/api/events/{event['id']}.ics").get_data(as_text=True)

    assert f"EXDATE" in body
    assert skipped.strftime("%Y%m%d") + "T140000" in body
    assert "RECURRENCE-ID" in body
    assert moved.strftime("%Y%m%d") + "T140000" in body
    # The override's own start, where the occurrence actually is.
    assert (moved + timedelta(days=3)).strftime("%Y%m%d") + "T103000" in body
    # One series plus one override.
    assert body.count("BEGIN:VEVENT") == 2
    assert body.count("END:VEVENT") == 2
    # Same UID on both: that is what makes it an override rather than a
    # second meeting.
    assert body.count(f"UID:event-{event['id']}@") == 2


def test_an_exception_for_a_week_the_series_no_longer_reaches_is_ignored(
        weekly, session):
    """Shortening a series must not resurrect an orphaned exception.

    The row stays -- lengthening the series again should bring its exception
    back with it -- but nothing renders it while it is out of range.
    """
    client, event, start = weekly
    late = start + timedelta(weeks=6)
    client.patch(f"/api/events/{event['id']}", json={
        "scope": "occurrence", "occurrence": late.strftime("%Y-%m-%d"),
        "date": (late + timedelta(days=1)).strftime("%Y-%m-%d"),
    })

    # Now end the series before that occurrence.
    response = client.patch(f"/api/events/{event['id']}", json={
        "repeat": "weekly",
        "repeat_until": (start + timedelta(weeks=3)).strftime("%Y-%m-%d"),
    })
    assert response.status_code == 200

    rows = _occurrences(client)
    assert len(rows) == 4
    assert (late + timedelta(days=1)).strftime("%Y-%m-%d") not in {
        r["date"] for r in rows}
    # The row is still there, waiting in case the series is extended again.
    assert session.query(EventException).filter(
        EventException.event_id == event["id"]).count() == 1

    body = client.get(f"/api/events/{event['id']}.ics").get_data(as_text=True)
    assert body.count("BEGIN:VEVENT") == 1   # no override for a dead date


def test_moving_an_occurrence_into_view_from_outside_the_window(
        client, session, make_org, login):
    """The window applies to where an occurrence is, not where it started.

    A meeting moved backwards into this fortnight has to appear in it, even
    though the date the series produced is outside -- which is the case the
    base expansion cannot find on its own.
    """
    org = make_org()
    c = login(org)
    # A series starting well beyond the dashboard's recent-history floor.
    start = date.today() - timedelta(days=120)
    created = c.post("/api/events", json={
        "title": "pytest long runner", "partner": "pytest partner",
        "date": start.strftime("%Y-%m-%d"), "time": "14:00",
        "repeat": "weekly",
        "repeat_until": (start + timedelta(weeks=60)).strftime("%Y-%m-%d"),
    }).get_json()["event"]

    event = session.get(Event, created["id"])
    horizon = date.today() + timedelta(days=365)
    floor = date.today() - timedelta(days=14)

    # An occurrence from before the floor, moved to today.
    old = next(o.occurs_on for o in event.occurrences(horizon)
               if o.date < floor)
    session.add(EventException(event_id=event.id, occurs_on=old,
                               cancelled=False, date=date.today(),
                               time=event.time, all_day=False))
    session.commit()
    session.expire(event)

    landed = event.occurrences(horizon, since=floor)
    assert date.today() in [o.date for o in landed]
    assert old in [o.occurs_on for o in landed]
