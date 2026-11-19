"""Shared fixtures: a real PostgreSQL database, migrated once per test session.

Set WALTRIX_TEST_DATABASE_URL to point at a disposable database. It is wiped
(TRUNCATE) before every test.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from waltrix_core.db import make_engine, make_session_factory
from waltrix_core.enums import ActorType, Role
from waltrix_core.migrate import downgrade, upgrade
from waltrix_core.services import identity
from waltrix_core.services.context import Actor

DEFAULT_URL = "postgresql://waltrix@127.0.0.1:4822/waltrix_test"
TABLES = (
    "audit_events, reconciliation_runs, idempotency_records, holds, postings, journal_entries, "
    "transactions, wallets, accounts, ledgers, api_keys, user_sessions, memberships, users, organizations"
)


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ.get("WALTRIX_TEST_DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    downgrade(database_url, "base")
    upgrade(database_url)
    eng = make_engine(database_url, pool_size=30, max_overflow=30)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture(autouse=True)
def _clean_db(request: pytest.FixtureRequest) -> None:
    if "engine" not in request.fixturenames and "session_factory" not in request.fixturenames:
        return
    eng: Engine = request.getfixturevalue("engine")
    with eng.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    s = session_factory()
    yield s
    s.close()


def make_org(session: Session, name: str = "Acme") -> tuple[Actor, uuid.UUID]:
    """Create a user + organization; return an OWNER actor and the user id."""
    user = identity.register_user(
        session, email=f"{uuid.uuid4().hex[:8]}@example.test", password="correct-horse-battery", display_name=name
    )
    org = identity.create_organization(session, user, name=name)
    return Actor(org.id, ActorType.USER, str(user.id), user.email, Role.OWNER, "test"), user.id


@pytest.fixture
def owner(session: Session) -> Actor:
    return make_org(session)[0]
