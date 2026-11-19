"""Programmatic migrations: ``upgrade(database_url)`` for host applications and tests."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_DIR = Path(__file__).parent / "migrations"


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str, revision: str) -> None:
    command.downgrade(alembic_config(database_url), revision)
