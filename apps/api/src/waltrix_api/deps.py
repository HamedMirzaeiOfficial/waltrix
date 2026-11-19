"""Request dependencies: database session, authentication, tenant resolution, rate limits.

Two credential types:

* **API key** - ``Authorization: Bearer wtx_key_...``. Bound to one
  organization and one role server-side. Any organization header is ignored.
* **Dashboard session** - httpOnly ``waltrix_session`` cookie. The client names
  the organization in ``X-Waltrix-Organization``; the server verifies the
  user's membership and takes the role from the database. For cookie-auth
  unsafe methods we also require ``X-Requested-With: waltrix-web`` (a custom
  header cannot be sent cross-site without a CORS preflight we don't allow),
  in addition to ``SameSite=Strict`` cookies.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from waltrix_core.db.models import User
from waltrix_core.errors import AuthenticationFailed, NotFound
from waltrix_core.services import identity
from waltrix_core.services.context import Actor

from .errors import ApiError
from .ratelimit import limiter
from .settings import Settings, get_settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER_VALUE = "waltrix-web"


def get_db(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def correlation_id(request: Request) -> str | None:
    return request.scope.get("state", {}).get("correlation_id")


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trusted_proxy_count > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hops) >= settings.trusted_proxy_count:
            return hops[-settings.trusted_proxy_count]
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(key: str, limit: int) -> None:
    allowed, retry_after = limiter.hit(key, limit)
    if not allowed:
        raise ApiError(429, "rate_limited", "too many requests", headers={"Retry-After": str(retry_after)})


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


@dataclass(frozen=True, slots=True)
class Credentials:
    user: User | None
    api_actor: Actor | None
    via_cookie: bool


def _credentials(request: Request, db: Session, settings: Settings) -> Credentials:
    token = _bearer(request)
    cid = correlation_id(request)
    if token and token.startswith("wtx_key_"):
        actor = identity.resolve_api_key(db, token, cid)
        db.commit()  # persist throttled last_used_at; ends the auth transaction
        _enforce_rate_limit(f"key:{actor.actor_id}", settings.rate_limit_per_minute)
        return Credentials(None, actor, via_cookie=False)
    cookie = request.cookies.get(settings.session_cookie_name)
    if token or not cookie:
        raise AuthenticationFailed("authentication required")
    user = identity.resolve_session(db, cookie)
    db.commit()
    if request.method not in SAFE_METHODS and request.headers.get("x-requested-with") != CSRF_HEADER_VALUE:
        raise ApiError(403, "csrf_failed", "missing X-Requested-With header for cookie-authenticated request")
    _enforce_rate_limit(
        f"sess:{hashlib.sha256(cookie.encode()).hexdigest()[:16]}", settings.rate_limit_per_minute
    )
    return Credentials(user, None, via_cookie=True)


def current_user(
    request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> User:
    creds = _credentials(request, db, settings)
    if creds.user is None:
        raise ApiError(403, "user_session_required", "this endpoint requires a dashboard user session")
    return creds.user


def current_actor(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_waltrix_organization: str | None = Header(default=None),
) -> Actor:
    creds = _credentials(request, db, settings)
    if creds.api_actor is not None:
        return creds.api_actor
    assert creds.user is not None
    if not x_waltrix_organization:
        raise ApiError(400, "organization_required", "X-Waltrix-Organization header is required")
    try:
        org_id = uuid.UUID(x_waltrix_organization)
    except ValueError as exc:
        raise NotFound("organization not found") from exc
    actor = identity.actor_for_user(db, creds.user, org_id, correlation_id(request))
    db.commit()
    return actor


def idempotency_key(
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
            description="Required. Reuse the same key when retrying the same request.",
        ),
    ],
) -> str:
    """Required on every money-moving request (FastAPI returns 422 when missing)."""
    return idempotency_key


def optional_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str | None:
    return idempotency_key
