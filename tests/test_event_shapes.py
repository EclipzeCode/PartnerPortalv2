"""Meetings that do not have a start time, or a length, or either.

The events table used to require both, so "all day Thursday" had nowhere to go
and "three o'clock, however long it takes" had to be filed as some invented
number of hours -- which the dashboard then displayed as a fact.
"""

import pytest


BASE = {
    "title": "Kickoff",
    "date": "2026-09-01",
    "time": "14:00",
    "partner": "pytest partner",
}


@pytest.fixture
def org(client, login, make_org):
    o = make_org()
    login(o)
    return o


def create(client, **overrides):
    response = client.post("/api/events", json={**BASE, **overrides})
    return response, response.get_json()


# --- No length given -------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {},                       # duration not mentioned at all
    {"duration": None},       # explicitly nothing
    {"duration": ""},         # an empty form field
])
def test_a_meeting_can_be_saved_without_a_length(client, org, payload):
    response, body = create(client, **payload)
    assert response.status_code == 201
    # null rather than a stand-in: the dashboard draws a start time with no
    # range after it, and it can only tell the difference if the absence
    # survives the round trip.
    assert body["event"]["duration"] is None
    assert body["event"]["time"] == "14:00"


def test_a_length_can_be_removed_from_a_meeting_that_had_one(client, org):
    _r, body = create(client, duration=1.5)
    eid = body["event"]["id"]
    event = client.patch(f"/api/events/{eid}",
                         json={"duration": None}).get_json()["event"]
    assert event["duration"] is None


def test_a_nonsense_length_is_still_refused(client, org):
    """Optional means "may be absent", not "may be anything"."""
    for bad in (0, -1, 25, "soon"):
        response, _ = create(client, duration=bad)
        assert response.status_code == 400, f"duration={bad!r}"


# --- All day ---------------------------------------------------------------

def test_an_all_day_meeting_needs_no_time_and_keeps_no_length(client, org):
    response = client.post("/api/events", json={
        "title": "Conference",
        "date": "2026-09-01",
        "partner": "pytest partner",
        "all_day": True,
        # Both are sent and both are ignored: an all-day meeting has no start
        # time to honor and no length to state.
        "time": "09:30",
        "duration": 3,
    })
    assert response.status_code == 201
    event = response.get_json()["event"]
    assert event["all_day"] is True
    assert event["duration"] is None
    # Midnight, so it sorts to the top of its own day without any ORDER BY
    # having to special-case it.
    assert event["time"] == "00:00"


def test_an_all_day_meeting_still_needs_a_date(client, org):
    response = client.post("/api/events", json={
        "title": "Conference", "partner": "pytest partner", "all_day": True,
    })
    assert response.status_code == 400


def test_a_timed_meeting_still_needs_a_start_time(client, org):
    """Dropping the time is what all_day is for, not something anyone can do
    by leaving the field out."""
    response = client.post("/api/events", json={
        "title": "Sync", "date": "2026-09-01", "partner": "pytest partner",
    })
    assert response.status_code == 400


def test_switching_a_meeting_to_all_day_clears_its_time_and_length(client, org):
    _r, body = create(client, duration=2)
    eid = body["event"]["id"]
    event = client.patch(f"/api/events/{eid}",
                         json={"all_day": True}).get_json()["event"]
    assert event["all_day"] is True
    assert event["time"] == "00:00"
    assert event["duration"] is None


def test_a_length_cannot_be_smuggled_onto_an_all_day_meeting(client, org):
    """The two arriving in separate requests must not leave a row that renders
    as both -- which is what the check constraint is there to make impossible.
    """
    _r, body = create(client, all_day=True)
    eid = body["event"]["id"]
    event = client.patch(f"/api/events/{eid}",
                         json={"duration": 2}).get_json()["event"]
    assert event["duration"] is None
    assert event["all_day"] is True


def test_an_all_day_meeting_can_be_turned_back_into_a_timed_one(client, org):
    _r, body = create(client, all_day=True)
    eid = body["event"]["id"]
    event = client.patch(f"/api/events/{eid}", json={
        "all_day": False, "time": "16:45", "duration": 0.5,
    }).get_json()["event"]
    assert event["all_day"] is False
    assert event["time"] == "16:45"
    assert event["duration"] == 0.5


def test_existing_meetings_are_not_all_day(client, org):
    """Every meeting saved before the column existed is a timed one."""
    _r, body = create(client, duration=1)
    assert body["event"]["all_day"] is False
