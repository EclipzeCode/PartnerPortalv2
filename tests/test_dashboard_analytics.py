"""The numbers the dashboard's charts are drawn from.

The stat cards can be built from counts. A chart cannot: a line needs one point
per day, including the days nothing happened, and a ratio needs to know what it
is a ratio of.
"""

from datetime import datetime, timedelta, timezone

from models import ProfileView


def stats_for(client):
    return client.get("/api/dashboard").get_json()["stats"]


def test_the_view_series_covers_every_day_in_the_window(client, login, make_org):
    me = make_org()
    login(me)
    series = stats_for(client)["profile_views_series"]

    assert len(series) == 30
    # Oldest first, one day apart, no gaps -- a series with the empty days left
    # out would draw a line straight across a quiet fortnight as a plateau.
    days = [datetime.strptime(p["date"], "%Y-%m-%d").date() for p in series]
    assert days == sorted(days)
    assert all(
        (days[i + 1] - days[i]).days == 1 for i in range(len(days) - 1)
    )
    assert days[-1] == datetime.now(timezone.utc).date()


def test_a_quiet_profile_reports_zeroes_rather_than_nothing(client, login, make_org):
    me = make_org()
    login(me)
    series = stats_for(client)["profile_views_series"]
    assert [p["count"] for p in series] == [0] * 30


def test_views_are_counted_on_the_day_they_happened(client, login, make_org, session):
    me = make_org()
    now = datetime.now(timezone.utc)
    # Two today, one three days ago, and one well outside the window.
    for offset, n in ((0, 2), (3, 1), (45, 5)):
        for i in range(n):
            session.add(ProfileView(
                organization_id=me.id,
                viewer_key=f"pytest-{offset}-{i}",
                viewed_at=now - timedelta(days=offset),
            ))
    session.commit()

    login(me)
    series = stats_for(client)["profile_views_series"]
    by_day = {p["date"]: p["count"] for p in series}

    assert by_day[now.date().strftime("%Y-%m-%d")] == 2
    assert by_day[(now - timedelta(days=3)).date().strftime("%Y-%m-%d")] == 1
    # The one outside the window is not in the series, and has not been
    # silently folded into the first day of it either.
    assert sum(by_day.values()) == 3
    assert by_day[(now - timedelta(days=29)).date().strftime("%Y-%m-%d")] == 0


def test_the_vocabulary_size_rides_along(client, login, make_org):
    """The coverage meters draw "n of 33". The 33 has to come from the same
    place the categories do, or it goes stale the first time one is added."""
    import categories

    me = make_org()
    login(me)
    stats = stats_for(client)
    assert stats["category_total"] == categories.CATEGORY_TOTAL
    assert stats["focus_total"] == categories.FOCUS_TOTAL


def test_an_unfinished_profile_still_gets_the_series(client, login, make_org):
    """That branch of the payload returns early, and a chart with no key at
    all renders differently from one with an empty series."""
    me = make_org(onboarding_complete=False)
    login(me)
    stats = stats_for(client)
    assert len(stats["profile_views_series"]) == 30
    assert stats["category_total"] == 33


# --- The chart range -------------------------------------------------------

def test_the_window_can_be_asked_for(client, login, make_org):
    login(make_org())
    for days in (7, 30, 90):
        stats = client.get(f"/api/dashboard?days={days}").get_json()["stats"]
        assert stats["profile_views_days"] == days
        assert len(stats["profile_views_series"]) == days


def test_an_unrecognized_window_falls_back_rather_than_failing(
        client, login, make_org):
    """A stale bookmark asking for a window that no longer exists should draw
    the usual chart, not an error. The set is fixed because this number
    decides how much of profile_views gets scanned -- twice it, in fact."""
    login(make_org())
    for asked in ("365", "0", "-30", "nonsense", ""):
        stats = client.get(f"/api/dashboard?days={asked}").get_json()["stats"]
        assert stats["profile_views_days"] == 30


def test_the_answer_says_which_window_it_is_for(client, login, make_org):
    """The caption is written from this. A chart labeled with what was asked
    for rather than what was answered would be captioned wrong."""
    login(make_org())
    stats = client.get("/api/dashboard?days=7").get_json()["stats"]
    assert stats["profile_views_days"] == 7
    assert len(stats["profile_views_series"]) == 7


# --- Clearing the notification list ----------------------------------------
# The list is derived, so "read" had nowhere to live and old news sat in it
# for the full sixty days.

def _notifications(client):
    return client.get("/api/notifications").get_json()


def test_marking_read_clears_the_news(client, login, make_org, session):
    from models import Partnership
    me = make_org(offers=["mentors"], needs=["web_development"])
    them = make_org(offers=["web_development"], needs=["mentors"])
    # Something informational: a proposal of mine that was declined.
    session.add(Partnership(
        proposer_id=me.id, recipient_id=them.id,
        status=Partnership.DECLINED,
        proposer_gives=["mentors"], recipient_gives=["web_development"],
        proposer_name=me.name, recipient_name=them.name,
        responded_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc)))
    session.commit()
    login(me)

    before = _notifications(client)
    assert before["unseen"] >= 1
    assert any(not n["seen"] for n in before["notifications"])

    marked = client.post("/api/notifications/read").get_json()
    assert marked["unseen"] == 0
    assert all(n["seen"] for n in marked["notifications"] if not n["actionable"])

    # And it stays cleared on the next read.
    assert _notifications(client)["unseen"] == 0


def test_marking_read_does_not_clear_the_work(client, login, make_org, session):
    """A proposal waiting on an answer has not been dealt with because
    somebody looked at a list, so it is never marked seen and the count of
    what is actionable does not move."""
    from models import Partnership
    me = make_org(offers=["mentors"], needs=["web_development"])
    them = make_org(offers=["web_development"], needs=["mentors"])
    session.add(Partnership(
        proposer_id=them.id, recipient_id=me.id,
        status=Partnership.PENDING,
        proposer_gives=["web_development"], recipient_gives=["mentors"],
        proposer_name=them.name, recipient_name=me.name))
    session.commit()
    login(me)

    before = _notifications(client)
    assert before["actionable"] >= 1

    marked = client.post("/api/notifications/read").get_json()
    assert marked["actionable"] == before["actionable"]
    actionable = [n for n in marked["notifications"] if n["actionable"]]
    assert actionable and all(not n["seen"] for n in actionable)


def test_the_nav_badge_is_untouched_by_marking_read(client, login, make_org,
                                                    session):
    """The badge counts work. Marking the news read has not answered
    anything, so it must not move."""
    from models import Partnership
    me = make_org(offers=["mentors"], needs=["web_development"])
    them = make_org(offers=["web_development"], needs=["mentors"])
    session.add(Partnership(
        proposer_id=them.id, recipient_id=me.id,
        status=Partnership.PENDING,
        proposer_gives=["web_development"], recipient_gives=["mentors"],
        proposer_name=them.name, recipient_name=me.name))
    session.commit()
    login(me)

    before = client.get("/api/me").get_json()["pending_proposals"]
    client.post("/api/notifications/read")
    assert client.get("/api/me").get_json()["pending_proposals"] == before
