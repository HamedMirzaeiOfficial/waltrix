"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from waltrix_core import __version__
from waltrix_core.db import make_engine, make_session_factory

from . import errors
from .observability import RequestContextMiddleware, configure_logging
from .routers import auth, ledger, money, operations, organizations, wallets
from .settings import Settings, get_settings

DESCRIPTION = """
Waltrix is a double-entry ledger and wallet engine.

* Amounts are **integers in minor units** (`1250` USD = 12.50 USD).
* Every money-moving `POST` requires an **`Idempotency-Key`** header. Retrying with the same key and
  body returns the original outcome (`Idempotent-Replayed: true`); a different body returns `409`.
* Authenticate servers with `Authorization: Bearer wtx_key_...` (an API key bound to one organization).
* Funding (`/wallets/{id}/credit|debit`) uses a **simulated** funding source. No real bank is involved.
"""


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    app = FastAPI(
        title="Waltrix API",
        version=__version__,
        description=DESCRIPTION,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine or make_engine(settings.database_url, pool_size=settings.db_pool_size)
    app.state.session_factory = make_session_factory(app.state.engine)

    errors.install(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,  # explicit list only; never "*" with credentials
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-Waltrix-Organization",
                "X-Requested-With",
                "X-Correlation-ID",
            ],
            expose_headers=["X-Correlation-ID", "Idempotent-Replayed", "Retry-After"],
        )
    app.add_middleware(RequestContextMiddleware)

    for r in (
        auth.router,
        organizations.router,
        wallets.router,
        money.router,
        ledger.router,
        operations.router,
    ):
        app.include_router(r, prefix="/api/v1")
    app.include_router(operations.health)
    return app
