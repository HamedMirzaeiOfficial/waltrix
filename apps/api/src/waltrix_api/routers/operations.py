"""Reconciliation, audit log, overview metrics, reference data and health."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest
from sqlalchemy import text
from sqlalchemy.orm import Session

from waltrix_core.money import CURRENCY_EXPONENTS
from waltrix_core.services import queries, reconciliation
from waltrix_core.services.context import Actor

from .. import presenters
from .. import schemas as s
from ..deps import current_actor, get_db
from ..observability import RECONCILIATION_FINDINGS, REGISTRY

router = APIRouter()
health = APIRouter(tags=["health"])
Limit = Annotated[int, Query(ge=1, le=100)]


@router.post(
    "/reconciliation/runs", response_model=s.ReconciliationRunOut, status_code=201, tags=["reconciliation"]
)
def run_reconciliation(db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    run = reconciliation.run_reconciliation(db, actor)
    RECONCILIATION_FINDINGS.set(run.summary.get("errors", 0))
    return run


@router.get("/reconciliation/runs", response_model=s.PageOut[s.ReconciliationRunOut], tags=["reconciliation"])
def list_runs(
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    limit: Limit = 20,
    cursor: str | None = None,
):
    return presenters.page(
        queries.list_reconciliation_runs(db, actor, limit=limit, cursor=cursor),
        s.ReconciliationRunOut.model_validate,
    )


@router.get("/reconciliation/runs/{run_id}", response_model=s.ReconciliationRunOut, tags=["reconciliation"])
def get_run(run_id: UUID, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    return queries.get_reconciliation_run(db, actor, run_id)


@router.get("/audit-events", response_model=s.PageOut[s.AuditEventOut], tags=["audit"])
def list_audit(
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    limit: Limit = 50,
    cursor: str | None = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    target_id: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: Annotated[str | None, Query(max_length=64)] = None,
):
    return presenters.page(
        queries.list_audit_events(
            db, actor, limit=limit, cursor=cursor, action=action, target_id=target_id, actor_id=actor_id
        ),
        presenters.audit_event,
    )


@router.get("/overview", response_model=s.OverviewOut, tags=["overview"])
def overview(
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
    days: Annotated[int, Query(ge=1, le=365)] = 30,
):
    data = queries.overview(db, actor, days=days)
    run = data.pop("last_reconciliation")
    return s.OverviewOut(
        **data, last_reconciliation=s.ReconciliationRunOut.model_validate(run) if run else None
    )


@router.get("/currencies", response_model=list[s.CurrencyOut], tags=["reference"])
def currencies():
    return [s.CurrencyOut(code=c, exponent=e) for c, e in sorted(CURRENCY_EXPONENTS.items())]


@health.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies."""
    return {"status": "ok"}


@health.get("/readyz", include_in_schema=False)
def readyz(request: Request) -> JSONResponse:
    """Readiness: the database answers and migrations are applied."""
    try:
        with request.app.state.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
    if version is None:
        return JSONResponse({"status": "unavailable", "database": "not migrated"}, status_code=503)
    return JSONResponse({"status": "ready", "schema_version": version})


@health.get("/metrics", include_in_schema=False)
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(REGISTRY).decode(), media_type="text/plain; version=0.0.4")
