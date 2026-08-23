"""The zone a meeting is written in, and the calendar file that carries it.

A meeting was a date and a wall-clock time and nothing else, which is a
complete thought only while everyone involved is in one place. Two
organizations agreeing to meet at three had no way to say whose three.

The zone is recorded rather than the time converted to UTC, and these pin the
reason: an instant computed today for a meeting months away bakes in an offset
that is a *prediction*. When the meeting turns out to be on the far side of a
DST boundary, the stored instant keeps the wrong offset and the meeting moves
an hour on its own. Recording "15:00" and "America/Chicago" cannot do that.
"""

import pytest

import icalendar

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


def ics_for(client, event_id):
    response = client.get(f"/api/events/{event_id}.ics")
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.mimetype == "text/calendar"
    return icalendar.Calendar.from_ical(response.get_data(as_text=True))


def vevent(calendar):
    return next(c for c in calendar.walk() if c.name == "VEVENT")


# --- Storing the zone ------------------------------------------------------

def test_a_meeting_records_the_zone_it_was_written_in(client, org):
    response, body = create(client, timezone="America/Chicago")
    assert response.status_code == 201
    assert body["event"]["timezone"] == "America/Chicago"


def test_a_meeting_saved_without_a_zone_keeps_none(client, org):
    """Which is every meeting saved before the column existed.

    Null means "nobody recorded where", and the dashboard reads those in the
    viewer's own zone -- the assumption they were written under. Inventing a
    zone for them would be putting an answer in someone else's diary.
    """
    _, body = create(client)
    assert body["event"]["timezone"] is None


@pytest.mark.parametrize("bogus", [
    "Mars/Olympus",
    "Not a zone",
    "../../etc/passwd",       # ZoneInfo would happily read a path
    "x" * 80,                 # longer than the column
])
def test_an_unrecognised_zone_is_dropped_not_fatal(client, org, bogus):
    """The meeting is the thing being saved.

    A browser reporting a zone this tzdata has never heard of should not cost
    someone their entry, so the name is dropped and the row lands with none --
    exactly where it would have been before any of this existed.
    """
    response, body = create(client, timezone=bogus)
    assert response.status_code == 201
    assert body["event"]["timezone"] is None


def test_editing_a_meeting_does_not_re_file_it(client, org):
    """The zone belongs to the meeting, not to whoever last opened the form.

    Someone editing the title from a laptop in another country must not
    silently move the meeting, so a PATCH that says nothing about the zone
    leaves it alone.
    """
    _, body = create(client, timezone="America/Chicago")
    event_id = body["event"]["id"]

    patched = client.patch(f"/api/events/{event_id}",
                           json={"title": "Kickoff, renamed"})
    assert patched.status_code == 200
    assert patched.get_json()["event"]["timezone"] == "America/Chicago"


def test_a_client_that_means_it_can_change_the_zone(client, org):
    _, body = create(client, timezone="America/Chicago")
    event_id = body["event"]["id"]

    moved = client.patch(f"/api/events/{event_id}",
                         json={"timezone": "Europe/London"})
    assert moved.status_code == 200
    assert moved.get_json()["event"]["timezone"] == "Europe/London"

    # Unlike create, an explicit bad zone here is a mistake worth reporting:
    # the caller named the field.
    bad = client.patch(f"/api/events/{event_id}", json={"timezone": "Mars/Olympus"})
    assert bad.status_code == 400
    assert client.get("/api/events").get_json()["events"][0]["timezone"] \
        == "Europe/London"


# --- The calendar file -----------------------------------------------------

def test_the_same_wall_clock_resolves_either_side_of_a_dst_boundary(client, org):
    """The whole reason the zone is stored instead of a UTC instant.

    Two meetings at 15:00 in the same zone, one in March and one in
    November, are five and six hours behind UTC respectively. Nothing in the
    stored row differs but the date -- the offset is worked out when the file
    is written, from the rules in force, rather than guessed at save time.
    """
    _, march = create(client, date="2026-07-01", time="15:00",
                      timezone="America/Chicago", duration=1)
    _, november = create(client, date="2026-12-01", time="15:00",
                         timezone="America/Chicago", duration=1)

    summer = vevent(ics_for(client, march["event"]["id"])).decoded("DTSTART")
    winter = vevent(ics_for(client, november["event"]["id"])).decoded("DTSTART")

    assert summer.utcoffset().total_seconds() == -5 * 3600, "CDT expected"
    assert winter.utcoffset().total_seconds() == -6 * 3600, "CST expected"
    # Both still say three o'clock where the meeting is, which is the promise.
    assert summer.strftime("%H:%M") == "15:00"
    assert winter.strftime("%H:%M") == "15:00"


def test_the_file_carries_a_timezone_definition(client, org):
    """A TZID naming a zone nothing defines is not valid iCalendar.

    Clients are forgiving about this and it is still wrong, so the
    observances are emitted rather than assumed. An independent parser
    resolving DTSTART to the right instant is the proof they are usable.
    """
    _, body = create(client, date="2026-07-01", time="15:00",
                     timezone="Europe/London", duration=2)
    calendar = ics_for(client, body["event"]["id"])

    zones = [c for c in calendar.walk() if c.name == "VTIMEZONE"]
    assert len(zones) == 1
    assert str(zones[0]["TZID"]) == "Europe/London"

    start = vevent(calendar).decoded("DTSTART")
    assert start.utcoffset().total_seconds() == 3600, "BST expected in July"

    # Asserted on the observances themselves, not only on what a parser makes
    # of them: icalendar carries its own tzdata and would resolve a bare TZID
    # correctly even if this block were wrong, so reading DTSTART back does
    # not on its own prove the definition is right. London in 2026 changes
    # twice, GMT->BST and back.
    observances = [c for c in zones[0].walk() if c.name in ("STANDARD", "DAYLIGHT")]
    shifts = [
        (c.name, int(c["TZOFFSETFROM"].td.total_seconds()),
         int(c["TZOFFSETTO"].td.total_seconds()))
        for c in observances
    ]
    assert shifts == [
        ("STANDARD", 0, 0),          # the span the year opens in
        ("DAYLIGHT", 0, 3600),       # clocks forward in March
        ("STANDARD", 3600, 0),       # and back in October
    ], shifts


def test_a_meeting_with_no_length_gets_no_end_time(client, org):
    """Inventing an hour would put a time in a calendar nobody agreed to.

    The card on the dashboard makes the same choice: a start, and nothing
    after it.
    """
    _, body = create(client, timezone="America/Chicago", duration=None)
    entry = vevent(ics_for(client, body["event"]["id"]))
    assert "DTSTART" in entry
    assert "DTEND" not in entry


def test_an_all_day_meeting_spans_exactly_one_day(client, org):
    """DATE values, and an exclusive end -- so the end is the next morning.

    No zone is involved either: a date is the same date everywhere, and
    attaching one would make an all-day meeting start at a different hour
    depending on who opened the file.
    """
    from datetime import date

    _, body = create(client, date="2026-09-01", all_day=True,
                     timezone="America/Chicago")
    calendar = ics_for(client, body["event"]["id"])
    entry = vevent(calendar)

    assert entry.decoded("DTSTART") == date(2026, 9, 1)
    assert entry.decoded("DTEND") == date(2026, 9, 2)
    assert not [c for c in calendar.walk() if c.name == "VTIMEZONE"]


def test_a_meeting_with_no_zone_is_written_as_floating_time(client, org):
    """No TZID and no Z, which iCalendar defines as "wherever you are".

    That is not a fallback so much as an exact statement of what a row with
    no recorded zone knows: a wall clock, and nothing about where.
    """
    _, body = create(client, timezone=None, duration=1)
    response = client.get(f"/api/events/{body['event']['id']}.ics")
    text = response.get_data(as_text=True)

    assert "DTSTART:20260901T140000" in text
    assert "TZID" not in text
    assert vevent(icalendar.Calendar.from_ical(text)).decoded("DTSTART").tzinfo is None


def test_the_text_survives_the_format(client, org):
    """Semicolons, commas and newlines all mean something in an .ics line."""
    _, body = create(client, title="Q3 review; scope, budget",
                     location="Cafe Noel, Austin",
                     description="First line\nSecond line",
                     timezone="America/Chicago")
    entry = vevent(ics_for(client, body["event"]["id"]))

    assert str(entry["SUMMARY"]) == "Q3 review; scope, budget"
    assert str(entry["LOCATION"]) == "Cafe Noel, Austin"
    assert "First line\nSecond line" in str(entry["DESCRIPTION"])
    # Who it is with has nowhere else to go in a calendar entry.
    assert "pytest partner" in str(entry["DESCRIPTION"])


def test_re_importing_updates_rather_than_duplicates(client, org):
    """A stable UID is what stops a second download becoming a second meeting."""
    _, body = create(client, timezone="America/Chicago")
    event_id = body["event"]["id"]

    first = str(vevent(ics_for(client, event_id))["UID"])
    second = str(vevent(ics_for(client, event_id))["UID"])
    assert first == second
    assert str(event_id) in first


# --- Who may download it ---------------------------------------------------

def test_another_organizations_meeting_cannot_be_downloaded(
        client, login, make_org, org):
    """A diary is private, and a guessable .ics URL would publish it."""
    _, body = create(client, timezone="America/Chicago")
    event_id = body["event"]["id"]

    client.post("/logout")
    intruder = make_org(name="pytest-ics intruder")
    login(intruder)

    # 404 rather than 403: the same answer an id that does not exist gets, so
    # this cannot be used to find out which meeting ids are real.
    assert client.get(f"/api/events/{event_id}.ics").status_code == 404
    assert client.get("/api/events/999999999.ics").status_code == 404


def test_the_calendar_file_needs_a_session(client, org):
    _, body = create(client, timezone="America/Chicago")
    event_id = body["event"]["id"]
    client.post("/logout")
    assert client.get(f"/api/events/{event_id}.ics").status_code == 401


def test_the_file_is_never_cached_by_anything_in_between(client, org):
    """It is one organization's diary travelling over a shared network."""
    _, body = create(client, timezone="America/Chicago")
    response = client.get(f"/api/events/{body['event']['id']}.ics")
    assert response.headers["Cache-Control"] == "no-store"
    assert "attachment" in response.headers["Content-Disposition"]
