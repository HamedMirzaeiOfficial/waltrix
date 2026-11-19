"""Idempotency keys for financial mutations.

Rules (also in docs/concurrency.md):

* A key is scoped to ``(organization, operation, key)``.
* We store a SHA-256 fingerprint of the canonical request parameters.
  - same key + same parameters  -> the original outcome is replayed;
  - same key + other parameters -> ``IdempotencyKeyReused`` (409).
* The record is inserted in the *same* database transaction as the financial
  writes. Consequently:
  - it is committed if and only if the outcome is committed;
  - a crash or rollback mid-operation leaves no record, so the key can be
    retried and the operation runs again (nothing was committed the first time);
  - deterministic business failures (e.g. insufficient funds) *are* committed
    as an outcome and replayed - retrying with the same key will not suddenly
    succeed later. Use a new key for a genuinely new attempt.
* Concurrency: ``INSERT ... ON CONFLICT DO NOTHING`` on the unique index blocks
  a second transaction with the same key until the first commits or rolls
  back. It then either sees the committed record (replay) or proceeds as the
  first writer. No request can run the operation twice.
* Records expire after ``RETENTION`` and may be purged with ``purge_expired``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db.models import IdempotencyRecord
from ..errors import IdempotencyKeyReused, ValidationFailed
from .ledger import now

RETENTION = timedelta(hours=24)
MAX_KEY_LENGTH = 255


def fingerprint(operation: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"operation": operation, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_key(key: str) -> str:
    if not key or len(key) > MAX_KEY_LENGTH or not key.isprintable() or key != key.strip():
        raise ValidationFailed("Idempotency-Key must be 1-255 printable characters", field="idempotency_key")
    return key


@dataclass(frozen=True, slots=True)
class StoredOutcome:
    outcome: str
    resource_type: str | None
    resource_id: UUID | None
    error_code: str | None
    error_message: str | None


def claim(
    session: Session, org_id: UUID, operation: str, key: str, fp: str
) -> tuple[IdempotencyRecord | None, StoredOutcome | None]:
    """Claim the key for this transaction, or return the committed outcome to replay.

    Returns ``(record, None)`` when we are the first writer, ``(None, outcome)``
    for a replay.
    """
    for _ in range(2):
        inserted = session.execute(
            insert(IdempotencyRecord)
            .values(
                org_id=org_id,
                operation=operation,
                key=key,
                fingerprint=fp,
                outcome="in_progress",  # never visible after commit; see complete()
                expires_at=now() + RETENTION,
            )
            .on_conflict_do_nothing(index_elements=["org_id", "operation", "key"])
            .returning(IdempotencyRecord.id)
        ).scalar_one_or_none()
        if inserted is not None:
            return session.get_one(IdempotencyRecord, inserted), None

        existing = session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.org_id == org_id,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.key == key,
            )
        ).scalar_one_or_none()
        if existing is None:
            continue  # purged between our INSERT and SELECT; try once more
        if existing.expires_at <= now():
            session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.id == existing.id))
            continue
        if existing.fingerprint != fp:
            raise IdempotencyKeyReused(
                "this Idempotency-Key was already used with different request parameters"
            )
        return None, StoredOutcome(
            existing.outcome,
            existing.resource_type,
            existing.resource_id,
            existing.error_code,
            existing.error_message,
        )
    raise IdempotencyKeyReused("could not claim idempotency key; retry the request")


def complete(
    record: IdempotencyRecord,
    *,
    outcome: str,
    resource_type: str | None,
    resource_id: UUID | None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    record.outcome = outcome
    record.resource_type = resource_type
    record.resource_id = resource_id
    record.error_code = error_code
    record.error_message = error_message


def purge_expired(session: Session) -> int:
    result = session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.expires_at <= now()))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
