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
