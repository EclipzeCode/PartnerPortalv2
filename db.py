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

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    future=True,
)

# expire_on_commit=False so objects stay readable after the session commits,
# which is what request handlers want when serializing a response.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
