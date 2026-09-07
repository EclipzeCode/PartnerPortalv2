"""The limiter's own arithmetic, now that it is one SQL statement.

rate_limited() used to be four round trips -- an advisory lock, a SELECT, an
INSERT and a DELETE -- and is now a single statement with data-modifying CTEs
(_RATE_CLAIM in app.py). The behavior is meant to be identical, which is
exactly the kind of claim worth a test: the counting, the recording, the
refusal and the trim all moved into SQL at once, and nothing that existed
asserted the two halves that are easiest to get wrong there.

Those two are:

* A refused attempt records nothing. If it did, a caller that kept trying
  would push its own window forward and never be let back in -- the limit
  would harden into a ban. Both write paths in the statement are guarded by
  the same `n < max`, and this is what checks that the guard is on both.

* Recording an attempt trims that key's rows older than RATE_MAX_WINDOW. That
  DELETE is the CTE nothing selects from, and Postgres running it anyway --
  because data-modifying CTEs always execute -- is a property of the database
  rather than of this code. Worth pinning: if it were ever not true, nothing
  else here would notice until the table had grown for a month.
"""

import sqlalchemy as sa

import app as app_module
import db as db_module


BUCKET = "pytest_limiter"


def _committed(sql, params):
    """Run `sql` on a connection of its own, and really commit it.

    Not the `session` fixture, and this is the same constraint reset_rate_limits
    describes in conftest: the limiter keeps its own connection deliberately,
    so anything it is meant to see has to be committed for real rather than
    written inside the test's transaction. A row the test session inserts is
    invisible to the limiter and would make a trim look like it did not run.

    The rows are cleaned up by the autouse reset_rate_limits fixture, which
    deletes the table for exactly this reason.
    """
    db = db_module.SessionLocal()
    try:
        result = db.execute(sa.text(sql), params)
        value = result.scalar() if result.returns_rows else None
        db.commit()
        return value
    finally:
        db.close()


def _rows(key):
    return _committed(
        "SELECT count(*) FROM rate_limit_attempts "
        "WHERE bucket = :b AND key = :k",
        {"b": BUCKET, "k": key},
    )


def _stale(key, n=1):
    """`n` attempts for `key`, older than any window the limiter keeps."""
    _committed(
        "INSERT INTO rate_limit_attempts (bucket, key, attempted_at) "
        "SELECT :b, :k, now() - make_interval(secs => :age) "
        "FROM generate_series(1, :n)",
        {"b": BUCKET, "k": key, "age": float(app_module.RATE_MAX_WINDOW + 600),
         "n": n},
    )


def test_exactly_the_budget_is_allowed(clear_rate_limits):
    """Three means three, and the fourth is refused."""
    waits = [app_module.rate_limited(BUCKET, "budget", 3, 900) for _ in range(4)]
    assert waits[:3] == [0, 0, 0], waits
    assert waits[3] > 0, waits


def test_a_refused_attempt_records_nothing(clear_rate_limits):
    """Otherwise the limit hardens into a ban for anyone who keeps trying."""
    for _ in range(2):
        assert app_module.rate_limited(BUCKET, "quiet", 2, 900) == 0
    assert _rows("quiet") == 2

    for _ in range(5):
        assert app_module.rate_limited(BUCKET, "quiet", 2, 900) > 0
    # Five refusals later, still the two that were actually allowed.
    assert _rows("quiet") == 2


def test_the_wait_does_not_grow_by_being_asked(clear_rate_limits):
    """The counterpart to the above, from the caller's side.

    The wait counts down toward the moment the oldest attempt ages out. A
    refusal that recorded would reset that, so the number would stay flat or
    climb however long somebody waited.
    """
    for _ in range(2):
        assert app_module.rate_limited(BUCKET, "countdown", 2, 900) == 0
    first = app_module.rate_limited(BUCKET, "countdown", 2, 900)
    later = app_module.rate_limited(BUCKET, "countdown", 2, 900)
    assert first > 0 and later > 0
    assert later <= first


def test_recording_trims_that_key_of_what_aged_out(clear_rate_limits,
                                                   monkeypatch):
    """The DELETE nothing selects from still runs.

    The table-wide sweep is held off for the length of this test, and that is
    the whole reason it is worth writing. Both deletes remove exactly these
    rows, so with the sweep armed -- which it is at the start of every test,
    see reset_rate_limits -- this passes whether or not the per-key trim in
    _RATE_CLAIM does anything at all. Pushing the sweep out of reach is what
    leaves the CTE as the only thing that could have cleared them.
    """
    import time
    monkeypatch.setattr(app_module, "_rate_sweep_after",
                        time.monotonic() + 3600)

    _stale("stale", 2)
    assert _rows("stale") == 2

    # Well outside any window, so these do not count against the limit -- the
    # attempt is allowed, which is the path that trims.
    assert app_module.rate_limited(BUCKET, "stale", 5, 900) == 0
    assert _rows("stale") == 1   # the two stale ones gone, this one kept


def test_a_refusal_does_not_trim(clear_rate_limits):
    """The trim is guarded by the same condition as the insert.

    Not a behavior anybody depends on, but it is what the shared `n < max`
    guard means, and a trim that ran on the refusal path would be doing table
    maintenance on behalf of whoever is hammering the endpoint.
    """
    # Fill the window first. The stale row goes in *after*, because an
    # allowed attempt trims -- planting it first would mean the first of
    # these two deleted it and the refusal below had nothing left to spare.
    for _ in range(2):
        assert app_module.rate_limited(BUCKET, "refused", 2, 900) == 0
    _stale("refused")
    before = _rows("refused")
    assert before == 3

    assert app_module.rate_limited(BUCKET, "refused", 2, 900) > 0
    # The stale row is still there: the refusal wrote nothing and deleted
    # nothing. The next allowed attempt is what will clear it.
    assert _rows("refused") == before


def test_the_window_is_what_bounds_the_count(clear_rate_limits):
    """Attempts older than the caller's window do not count against it.

    The window is a parameter, not a constant -- /login and the public
    directory pass very different ones -- so the count has to be per-call
    rather than per-key.
    """
    for _ in range(3):
        assert app_module.rate_limited(BUCKET, "windowed", 3, 900) == 0
    # Refused over fifteen minutes...
    assert app_module.rate_limited(BUCKET, "windowed", 3, 900) > 0
    # ...and allowed over one second, which none of them are inside.
    import time
    time.sleep(1.1)
    assert app_module.rate_limited(BUCKET, "windowed", 3, 1) == 0
