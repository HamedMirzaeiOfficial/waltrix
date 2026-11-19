"""Transaction boundary for every financial mutation.

``run_operation`` owns exactly one PostgreSQL transaction:

    BEGIN
      SET LOCAL lock_timeout
      claim idempotency key            (may replay and return early)
      SAVEPOINT
        execute(): lock rows, validate, post journal entry, update balances
      on BusinessRuleViolation: ROLLBACK TO SAVEPOINT, record FAILED outcome
      complete idempotency record
    COMMIT                             (deferred balance triggers run here)

Either everything above commits or nothing does. Unexpected errors propagate
and roll back the whole transaction, including the idempotency claim.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ..errors import BusinessRuleViolation, ConcurrentRequest, LedgerInvariantViolation
from . import idempotency
from .context import Actor

log = logging.getLogger("waltrix.operations")

LOCK_TIMEOUT_MS = 5000

# (operation, outcome, seconds) observers, e.g. Prometheus metrics in the API.
Observer = Callable[[str, str, float], None]
OBSERVERS: list[Observer] = []


@dataclass(frozen=True, slots=True)
class OperationResult:
    operation: str
    outcome: str  # "succeeded" | "failed"
    resource_type: str | None
    resource_id: UUID | None
    error_code: str | None = None
    error_message: str | None = None
    replayed: bool = False

    @property
    def succeeded(self) -> bool:
        return self.outcome == "succeeded"


Execute = Callable[[Session], tuple[str, UUID]]
OnFailure = Callable[[Session, BusinessRuleViolation], tuple[str, UUID] | None]


def _sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


def run_operation(
    session: Session,
    actor: Actor,
    *,
    operation: str,
    payload: dict[str, Any],
    idempotency_key: str | None,
    execute: Execute,
    on_failure: OnFailure | None = None,
) -> OperationResult:
    if session.in_transaction():
        raise RuntimeError("run_operation must start its own transaction; commit first")
    if idempotency_key is not None:
        idempotency.validate_key(idempotency_key)
    fp = idempotency.fingerprint(operation, payload)
    started = time.perf_counter()
    try:
        with session.begin():
            session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_MS}ms'"))
            record = None
            if idempotency_key is not None:
                record, stored = idempotency.claim(session, actor.org_id, operation, idempotency_key, fp)
                if stored is not None:
                    result = OperationResult(
                        operation,
                        stored.outcome,
                        stored.resource_type,
                        stored.resource_id,
                        stored.error_code,
                        stored.error_message,
                        replayed=True,
                    )
                    _observe(operation, "replayed", started)
                    return result
            try:
                with session.begin_nested():
                    rtype, rid = execute(session)
                result = OperationResult(operation, "succeeded", rtype, rid)
            except BusinessRuleViolation as err:
                # The savepoint rollback discarded every partial write of execute().
                failed = on_failure(session, err) if on_failure else None
                result = OperationResult(
                    operation,
                    "failed",
                    failed[0] if failed else None,
                    failed[1] if failed else None,
                    err.code,
                    err.message,
                )
            if record is not None:
                idempotency.complete(
                    record,
                    outcome=result.outcome,
                    resource_type=result.resource_type,
                    resource_id=result.resource_id,
                    error_code=result.error_code,
                    error_message=result.error_message,
                )
    except DBAPIError as exc:
        state = _sqlstate(exc)
        _observe(operation, "error", started)
        if state in {"55P03", "40P01", "40001"}:  # lock timeout, deadlock, serialization
            raise ConcurrentRequest(
                "the resource is busy with a concurrent request; retry with the same Idempotency-Key"
            ) from exc
        if state in {"23514", "23503", "23505"}:
            # A database constraint caught something the engine did not. This is a bug.
            log.error("database invariant rejected operation %s: %s", operation, state)
            raise LedgerInvariantViolation("the database rejected an invalid ledger write") from exc
        raise
    except Exception:
        _observe(operation, "error", started)
        raise
    _observe(operation, result.outcome, started)
    return result


def _observe(operation: str, outcome: str, started: float) -> None:
    elapsed = time.perf_counter() - started
    for observer in OBSERVERS:
        try:
            observer(operation, outcome, elapsed)
        except Exception:  # observers must never break money movement
            log.exception("operation observer failed")
