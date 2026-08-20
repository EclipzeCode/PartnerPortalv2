"""Editing a meeting.

A meeting could be created and deleted and nothing else, so moving one by half
an hour meant deleting it and typing all six fields again -- and losing the
description on the way, because there was nothing left to copy it from.
"""

import pytest


@pytest.fixture
def meeting(client, login, make_org):
    org = make_org()
    login(org)
    created = client.post("/api/events", json={
        "title": "Kickoff",
        "date": "2026-09-01",
        "time": "14:00",
        "duration": 1.5,
        "partner": "pytest partner",
        "description": "Agree the scope.",
        "location": "The hall",
    })
    assert created.status_code == 201
    return org, created.get_json()["event"]["id"]


def test_a_single_field_can_be_changed(client, meeting):
    _org, eid = meeting
    response = client.patch(f"/api/events/{eid}", json={"time": "15:30"})
    assert response.status_code == 200
    event = response.get_json()["event"]
    assert event["time"] == "15:30"
    # Everything else is untouched -- this is the failure the old
    # delete-and-retype workaround had.
    assert event["title"] == "Kickoff"
    assert event["description"] == "Agree the scope."
    assert event["location"] == "The hall"
    assert event["duration"] == 1.5


def test_omitted_fields_are_left_alone(client, meeting):
    """A client that knows about the time must not blank the description by
    not mentioning it."""
    _org, eid = meeting
    client.patch(f"/api/events/{eid}", json={"title": "Kickoff, moved"})
    event = client.get("/api/events").get_json()["events"][0]
    assert event["title"] == "Kickoff, moved"
    assert event["description"] == "Agree the scope."


def test_a_field_can_be_cleared_by_sending_it_empty(client, meeting):
    _org, eid = meeting
    event = client.patch(f"/api/events/{eid}",
                         json={"description": "", "location": ""}
                         ).get_json()["event"]
    assert event["description"] == ""
    assert event["location"] == ""


def test_invalid_values_are_refused(client, meeting):
    _org, eid = meeting
    for payload in ({"date": "2026-13-45"}, {"time": "99:99"},
                    {"duration": 0}, {"duration": 25}, {"title": "  "},
                    {"partner": ""}):
        assert client.patch(f"/api/events/{eid}", json=payload).status_code == 400

    # ...and nothing was written by the ones that got partway through.
    event = client.get("/api/events").get_json()["events"][0]
    assert event["title"] == "Kickoff"
    assert event["date"] == "2026-09-01"
    assert event["time"] == "14:00"


def test_a_partly_valid_edit_does_not_half_apply(client, meeting):
    """The valid half of a rejected edit must not survive it."""
    _org, eid = meeting
    assert client.patch(f"/api/events/{eid}", json={
        "title": "Changed", "duration": 99,
    }).status_code == 400
    assert client.get("/api/events").get_json()["events"][0]["title"] == "Kickoff"


def test_another_organizations_meeting_cannot_be_edited(
        client, login, meeting, make_org):
    """Same 404 the delete route gives, so ids cannot be probed either."""
    _org, eid = meeting
    client.post("/logout")
    login(make_org())
    assert client.patch(f"/api/events/{eid}",
                        json={"title": "Hijacked"}).status_code == 404


def test_an_unknown_meeting_is_not_found(client, meeting):
    _org, _eid = meeting
    assert client.patch("/api/events/99999999",
                        json={"title": "x"}).status_code == 404


def test_over_long_values_are_refused(client, meeting):
    _org, eid = meeting
    assert client.patch(f"/api/events/{eid}",
                        json={"title": "x" * 300}).status_code == 400
    assert client.patch(f"/api/events/{eid}",
                        json={"location": "x" * 300}).status_code == 400
