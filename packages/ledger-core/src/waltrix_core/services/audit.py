"""Operational audit events (who did what), separate from financial postings."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..db.models import AuditEvent
from .context import Actor

# Keys that must never end up in audit metadata, even by accident.
_FORBIDDEN_KEYS = {"password", "secret", "token", "api_key", "authorization", "key"}


def _scrub(meta: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in meta.items() if k.lower() not in _FORBIDDEN_KEYS}


def record(
    session: Session,
    actor: Actor,
    action: str,
    *,
    target_type: str | None = None,
    target_id: UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        org_id=actor.org_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        correlation_id=actor.correlation_id,
        metadata_=_scrub(metadata or {}),
    )
    session.add(event)
    return event
