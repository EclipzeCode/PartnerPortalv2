"""Database engine and session handling.

Neon is serverless and drops idle connections, so `pool_pre_ping` checks a
connection before handing it out and `pool_recycle` retires them before Neon
does. Without these, the first request after a quiet period fails with a
stale-connection error.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy .env.example to .env and paste the "
        "connection string from your Neon project dashboard."
    )


def _normalize(url):
    """Point SQLAlchemy at psycopg 3.

    Hosting providers hand out `postgresql://` (and older ones `postgres://`),
    both of which SQLAlchemy maps to psycopg2 -- a package this project does
    not install. Naming the driver explicitly keeps the stock connection
    string working, wherever it is pasted from.
    """
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


DATABASE_URL = _normalize(DATABASE_URL)

# How many Postgres connections one worker process may hold.
#
# Left at SQLAlchemy's defaults, this was pool_size=5 with max_overflow=10 --
# fifteen connections per process, and render.yaml starts two workers, so a
# ceiling of thirty against a Neon compute whose own limit is well under that
# on the smaller plans. Nothing here would ever open thirty: gunicorn's sync
# workers handle exactly one request at a time, so one worker needs one
# connection, and the pool's job is to keep that one warm rather than to fan
# out. The defaults were not sized for this app, they were just never said.
#
# Two plus three of overflow, then. The overflow is not for concurrency that
# does not exist -- it is headroom for the moment a connection is being
# recycled or pre-ping finds a dead one, so a request borrows a second rather
# than waiting on the first. Overridable because the right number is a
# property of the deployment, not of this file: raise it with --threads or a
# non-sync worker class, both of which make one process genuinely concurrent.
#
# One correction to the arithmetic above, since it is the kind of thing that
# goes stale quietly. A request on a rate-limited route now needs *two*
# connections at once, not one: the handler holds its own session while the
# limiter deliberately takes a separate one, because an attempt has to be
# recorded even when the handler's transaction is about to be rolled back
# (see _limiter_db in app.py). Two plus three still covers that comfortably
# for a sync worker serving one request at a time -- but anyone adding
# --threads should size this at roughly two per concurrent request rather
# than one, or the second half of a login will queue on pool_timeout behind
# the first half of somebody else's.
POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "2"))
POOL_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "3"))

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=POOL_SIZE,
    max_overflow=POOL_MAX_OVERFLOW,
    # Wait this long for a connection before giving up. The default is 30
    # seconds, which under a burst means a request sitting silently on a
    # queue until the client or Render's proxy has long since given up on it.
    # Ten seconds is past Neon's cold start and short enough that a pool
    # genuinely exhausted surfaces as an error somebody can act on.
    pool_timeout=int(os.environ.get("DB_POOL_TIMEOUT", "10")),
    future=True,
)

# expire_on_commit=False so objects stay readable after the session commits,
# which is what request handlers want when serializing a response.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
