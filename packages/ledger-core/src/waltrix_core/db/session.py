"""Engine and session factories."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str, *, pool_size: int = 10, max_overflow: int = 10) -> Engine:
    """Create a SQLAlchemy engine for PostgreSQL (psycopg 3).

    READ COMMITTED is used deliberately: correctness comes from explicit row
    locks taken in a deterministic order plus database constraints, not from
    SERIALIZABLE retries (see docs/concurrency.md).
    """
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return create_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        isolation_level="READ COMMITTED",
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: response objects stay readable after commit.
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
