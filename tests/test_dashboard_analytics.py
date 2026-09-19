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
    # The open that marks things read is the one open on which they are
    # new: `seen` in this response says whether each entry was there the
    # last time the panel opened, so the panel can draw the fresh ones as
    # fresh. It used to be computed after the timestamp moved, which made
    # every informational entry arrive already dimmed.
    assert any(not n["seen"] for n in marked["notifications"]
               if not n["actionable"])

    # And it stays cleared on the next read, where the same entry is old news.
    after = _notifications(client)
    assert after["unseen"] == 0
    assert all(n["seen"] for n in after["notifications"] if not n["actionable"])


def test_marking_read_does_not_clear_the_work(client, login, make_org, session):
    """Seen is not answered. Opening the panel marks a waiting proposal seen
    -- the dot is about what is new, and it has now been shown -- but the
    entry stays in the list, still flagged as work, until it is answered."""
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
    assert before["unseen"] >= 1

    marked = client.post("/api/notifications/read").get_json()
    assert marked["actionable"] == before["actionable"]
    assert marked["unseen"] == 0
    actionable = [n for n in marked["notifications"] if n["actionable"]]
    assert actionable

    # Still listed, still flagged as work, and now seen.
    after = _notifications(client)
    assert after["actionable"] == before["actionable"]
    actionable = [n for n in after["notifications"] if n["actionable"]]
    assert actionable and all(n["seen"] for n in actionable)


def test_the_badge_is_what_is_new_and_clears_when_the_panel_opens(
        client, login, make_org, session):
    """/api/me's `unseen` is the dot. It counts the same entries the panel
    lists, whatever their kind, and marking read -- which the panel does on
    opening -- takes it to zero while the work count stands."""
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

    me_before = client.get("/api/me").get_json()
    assert me_before["unseen"] >= 1
    assert me_before["actionable"] >= 1
    assert me_before["unseen"] == _notifications(client)["unseen"]

    client.post("/api/notifications/read")
    me_after = client.get("/api/me").get_json()
    assert me_after["unseen"] == 0
    assert me_after["actionable"] == me_before["actionable"]


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


def test_an_informational_entry_can_be_dismissed_and_stays_gone(
        client, login, make_org, session):
    """News can be cleared one entry at a time. Work cannot: an entry
    waiting on this organization is refused, and the list is what says
    which is which."""
    from datetime import datetime, timezone
    from models import Partnership
    me = make_org(offers=["mentors"], needs=["web_development"])
    them = make_org(offers=["web_development"], needs=["mentors"])
    session.add_all([
        # Waiting on me: actionable, cannot be dismissed.
        Partnership(
            proposer_id=them.id, recipient_id=me.id,
            status=Partnership.PENDING,
            proposer_gives=["web_development"], recipient_gives=["mentors"],
            proposer_name=them.name, recipient_name=me.name),
        # My proposal, declined: news.
        Partnership(
            proposer_id=me.id, recipient_id=them.id,
            status=Partnership.DECLINED,
            responded_at=datetime.now(timezone.utc),
            proposer_gives=["mentors"], recipient_gives=["web_development"],
            proposer_name=me.name, recipient_name=them.name),
    ])
    session.commit()
    login(me)

    items = _notifications(client)["notifications"]
    news = next(i for i in items if i["kind"] == "proposal_declined")
    work = next(i for i in items if i["kind"] == "proposal_received")
    assert news["key"] and work["key"]

    refused = client.post("/api/notifications/dismiss", json={"key": work["key"]})
    assert refused.status_code == 409

    assert client.post("/api/notifications/dismiss",
                       json={"key": news["key"]}).status_code == 200
    after = _notifications(client)["notifications"]
    assert news["key"] not in {i["key"] for i in after}
    assert work["key"] in {i["key"] for i in after}
    # Persisted on the row, not just this read.
    session.refresh(me)
    assert news["key"] in me.dismissed_notifications

    assert client.post("/api/notifications/dismiss",
                       json={"key": "nonsense"}).status_code == 400


def test_everything_dismissable_can_go_at_once(client, login, make_org, session):
    """The panel's Clear: every piece of news in one request, and the work
    exactly where it was."""
    from datetime import datetime, timedelta, timezone
    from models import Partnership
    me = make_org(offers=["mentors"], needs=["web_development"])
    them = make_org(offers=["web_development"], needs=["mentors"])
    other = make_org(offers=["web_development"], needs=["mentors"])
    now = datetime.now(timezone.utc)
    session.add_all([
        Partnership(
            proposer_id=them.id, recipient_id=me.id, status=Partnership.PENDING,
            proposer_gives=["web_development"], recipient_gives=["mentors"],
            proposer_name=them.name, recipient_name=me.name),
        Partnership(
            proposer_id=me.id, recipient_id=them.id, status=Partnership.DECLINED,
            responded_at=now,
            proposer_gives=["mentors"], recipient_gives=["web_development"],
            proposer_name=me.name, recipient_name=them.name),
        Partnership(
            proposer_id=me.id, recipient_id=other.id, status=Partnership.WITHDRAWN,
            responded_at=now - timedelta(days=1),
            proposer_gives=["mentors"], recipient_gives=["web_development"],
            proposer_name=me.name, recipient_name=other.name),
    ])
    session.commit()
    login(me)

    before = _notifications(client)["notifications"]
    news = {i["key"] for i in before if not i["actionable"]}
    work = {i["key"] for i in before if i["actionable"]}
    assert len(news) == 1 and len(work) == 1   # the withdrawal is mine, not news

    cleared = client.post("/api/notifications/dismiss", json={"all": True})
    assert cleared.status_code == 200
    assert set(cleared.get_json()["keys"]) == news

    after = {i["key"] for i in _notifications(client)["notifications"]}
    assert after == work


# --- The poll ----------------------------------------------------------------
# The nav asks /api/me every minute per visible tab. Nearly every ask finds
# nothing changed, and used to pay for the full notification build anyway.

def _me(client, etag=None):
    headers = {"If-None-Match": etag} if etag else {}
    return client.get("/api/me", headers=headers)


def test_an_unchanged_poll_is_a_304(client, login, make_org):
    login(make_org())
    first = _me(client)
    assert first.status_code == 200
    etag = first.headers["ETag"]
    assert etag.startswith('W/')

    again = _me(client, etag)
    assert again.status_code == 304
    assert again.get_data() == b""
    assert again.headers["ETag"] == etag


def test_the_poll_notices_a_proposal_arriving(client, login, make_org):
    me = make_org(offers=["mentors"], needs=["web_development"])
    them = make_org(offers=["web_development"], needs=["mentors"])
    login(me)
    etag = _me(client).headers["ETag"]
    client.post("/logout")

    login(them)
    sent = client.post("/api/proposals", json={
        "recipient_id": me.id,
        "proposer_gives": ["web_development"],
        "recipient_gives": ["mentors"],
    })
    assert sent.status_code == 201
    client.post("/logout")

    login(me)
    changed = _me(client, etag)
    assert changed.status_code == 200
    assert changed.get_json()["pending_proposals"] == 1
    assert changed.headers["ETag"] != etag


def test_the_poll_notices_the_panel_being_opened(client, login, make_org, session):
    """Opening the bell marks things seen, which changes `unseen` and so
    must change the tag -- even though no partnership row moved."""
    from models import Partnership
    me = make_org(offers=["mentors"], needs=["web_development"])
    them = make_org(offers=["web_development"], needs=["mentors"])
    session.add(Partnership(
        proposer_id=me.id, recipient_id=them.id, status=Partnership.DECLINED,
        proposer_gives=["mentors"], recipient_gives=["web_development"],
        proposer_name=me.name, recipient_name=them.name,
        responded_at=datetime.now(timezone.utc)))
    session.commit()
    login(me)
    before = _me(client)
    assert before.get_json()["unseen"] >= 1
    etag = before.headers["ETag"]

    client.post("/api/notifications/read")

    after = _me(client, etag)
    assert after.status_code == 200
    assert after.get_json()["unseen"] == 0

    # And /api/notifications carries the same tag as /api/me for the same
    # state, so a page holding one can ask the other with it.
    listed = client.get("/api/notifications",
                        headers={"If-None-Match": after.headers["ETag"]})
    assert listed.status_code == 304
