"""Users, organizations, memberships, sessions and API keys.

Secrets handling:
* Passwords: scrypt (stdlib ``hashlib.scrypt``) with a per-user random salt.
* Session tokens and API keys: 256-bit random secrets; only their SHA-256
  hash is stored. The plaintext is returned exactly once.
* Unknown-user logins still run a full scrypt verification against a dummy
  hash so response time does not reveal which emails are registered.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import ApiKey, Membership, Organization, User, UserSession
from ..enums import ActorType, Role
from ..errors import AuthenticationFailed, Conflict, NotFound, PermissionDenied, ValidationFailed
from ..permissions import API_KEY_ROLES, ROLE_RANK, Permission
from . import audit
from .context import Actor
from .ledger import get_or_create_default_ledger, now

SESSION_TTL = timedelta(hours=12)
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD = 10
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --- passwords --------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b64 = base64.b64encode
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_b64, digest_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise ValidationFailed("a valid email address is required", field="email")
    return email


# --- users and sessions -----------------------------------------------------


def register_user(session: Session, *, email: str, password: str, display_name: str) -> User:
    email = _normalize_email(email)
    if len(password) < MIN_PASSWORD or len(password) > 256:
        raise ValidationFailed(f"password must be {MIN_PASSWORD}-256 characters", field="password")
    display_name = (display_name or "").strip()[:120] or email.split("@")[0]
    with session.begin():
        if session.execute(select(User.id).where(User.email == email)).first():
            raise Conflict("an account with this email already exists")
        user = User(email=email, display_name=display_name, password_hash=hash_password(password))
        session.add(user)
        session.flush()
    return user


def login(session: Session, *, email: str, password: str) -> tuple[User, str]:
    """Return ``(user, session_token)``. Generic error for any failure."""
    try:
        email = _normalize_email(email)
    except ValidationFailed:
        email = ""
    with session.begin():
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
        if not user or not ok or not user.is_active:
            raise AuthenticationFailed("invalid email or password")
        token = "wtx_sess_" + secrets.token_urlsafe(32)
        session.add(UserSession(user_id=user.id, token_hash=_sha256(token), expires_at=now() + SESSION_TTL))
    return user, token


def resolve_session(session: Session, token: str) -> User:
    row = session.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == _sha256(token))
    ).first()
    if row is None:
        raise AuthenticationFailed("invalid or expired session")
    sess, user = row
    if sess.revoked_at is not None or sess.expires_at <= now() or not user.is_active:
        raise AuthenticationFailed("invalid or expired session")
    return user


def logout(session: Session, token: str) -> None:
    with session.begin():
        sess = session.execute(
            select(UserSession).where(UserSession.token_hash == _sha256(token))
        ).scalar_one_or_none()
        if sess and sess.revoked_at is None:
            sess.revoked_at = now()


def membership_for(session: Session, user_id: UUID, org_id: UUID) -> Membership:
    m = (
        session.execute(select(Membership).where(Membership.user_id == user_id, Membership.org_id == org_id))
        .unique()
        .scalar_one_or_none()
    )
    if m is None:
        # Same answer whether the org does not exist or the user is not a member.
        raise NotFound("organization not found")
    return m


def actor_for_user(session: Session, user: User, org_id: UUID, correlation_id: str | None = None) -> Actor:
    m = membership_for(session, user.id, org_id)
    return Actor(org_id, ActorType.USER, str(user.id), user.email, Role(m.role), correlation_id)


def list_memberships(session: Session, user_id: UUID) -> list[Membership]:
    return list(
        session.execute(
            select(Membership).where(Membership.user_id == user_id).order_by(Membership.created_at)
        )
        .unique()
        .scalars()
    )


# --- organizations and members ---------------------------------------------


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "org"
    return f"{slug}-{secrets.token_hex(3)}"


def create_organization(
    session: Session, user: User, *, name: str, correlation_id: str | None = None
) -> Organization:
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ValidationFailed("name must be 1-120 characters", field="name")
    with session.begin():
        org = Organization(name=name, slug=_slugify(name))
        session.add(org)
        session.flush()
        session.add(Membership(org_id=org.id, user_id=user.id, role=Role.OWNER))
        get_or_create_default_ledger(session, org.id)
        actor = Actor(org.id, ActorType.USER, str(user.id), user.email, Role.OWNER, correlation_id)
        audit.record(session, actor, "organization.created", target_type="organization", target_id=org.id)
    return org


def update_organization(session: Session, actor: Actor, *, name: str) -> Organization:
    actor.require(Permission.ORG_MANAGE)
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ValidationFailed("name must be 1-120 characters", field="name")
    with session.begin():
        org = session.get_one(Organization, actor.org_id, with_for_update=True)
        old = org.name
        org.name = name
        audit.record(
            session,
            actor,
            "organization.updated",
            target_type="organization",
            target_id=org.id,
            metadata={"old_name": old, "new_name": name},
        )
    return org


def list_members(session: Session, actor: Actor) -> list[Membership]:
    actor.require(Permission.MEMBERS_READ)
    return list(
        session.execute(
            select(Membership).where(Membership.org_id == actor.org_id).order_by(Membership.created_at)
        )
        .unique()
        .scalars()
    )


def _check_grant(actor: Actor, role: Role) -> None:
    if ROLE_RANK[role] > ROLE_RANK[actor.role]:
        raise PermissionDenied("you cannot grant a role higher than your own")


def add_member(session: Session, actor: Actor, *, email: str, role: Role) -> Membership:
    actor.require(Permission.MEMBERS_MANAGE)
    role = Role(role)
    _check_grant(actor, role)
    email = _normalize_email(email)
    with session.begin():
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            raise NotFound("no registered user with this email; ask them to sign up first")
        exists = session.execute(
            select(Membership.id).where(Membership.org_id == actor.org_id, Membership.user_id == user.id)
        ).first()
        if exists:
            raise Conflict("user is already a member")
        m = Membership(org_id=actor.org_id, user_id=user.id, role=role)
        session.add(m)
        session.flush()
        audit.record(
            session,
            actor,
            "member.added",
            target_type="user",
            target_id=user.id,
            metadata={"role": str(role)},
        )
    session.refresh(m)
    return m


def _owner_count(session: Session, org_id: UUID) -> int:
    return session.execute(
        select(func.count())
        .select_from(Membership)
        .where(Membership.org_id == org_id, Membership.role == Role.OWNER)
    ).scalar_one()


def _lock_membership(session: Session, actor: Actor, membership_id: UUID) -> Membership:
    # Lock all memberships of the org (stable order) so "last owner" checks are race-free.
    rows = (
        session.execute(
            select(Membership)
            .where(Membership.org_id == actor.org_id)
            .order_by(Membership.id)
            .with_for_update(of=Membership)
        )
        .unique()
        .scalars()
        .all()
    )
    for m in rows:
        if m.id == membership_id:
            return m
    raise NotFound("member not found")


def change_member_role(session: Session, actor: Actor, *, membership_id: UUID, role: Role) -> Membership:
    actor.require(Permission.MEMBERS_MANAGE)
    role = Role(role)
    with session.begin():
        m = _lock_membership(session, actor, membership_id)
        _check_grant(actor, role)
        _check_grant(actor, Role(m.role))
        if m.role == Role.OWNER and role != Role.OWNER and _owner_count(session, actor.org_id) <= 1:
            raise Conflict("an organization must keep at least one owner")
        old = m.role
        m.role = role
        audit.record(
            session,
            actor,
            "member.role_changed",
            target_type="user",
            target_id=m.user_id,
            metadata={"from": str(old), "to": str(role)},
        )
    return m


def remove_member(session: Session, actor: Actor, *, membership_id: UUID) -> None:
    actor.require(Permission.MEMBERS_MANAGE)
    with session.begin():
        m = _lock_membership(session, actor, membership_id)
        _check_grant(actor, Role(m.role))
        if m.role == Role.OWNER and _owner_count(session, actor.org_id) <= 1:
            raise Conflict("an organization must keep at least one owner")
        audit.record(session, actor, "member.removed", target_type="user", target_id=m.user_id)
        session.delete(m)


# --- API keys ----------------------------------------------------------------


def create_api_key(
    session: Session, actor: Actor, *, name: str, role: Role, expires_in_days: int | None = None
) -> tuple[ApiKey, str]:
    """Return ``(row, plaintext)``. The plaintext is never stored or shown again."""
    actor.require(Permission.API_KEYS_MANAGE)
    role = Role(role)
    if role not in API_KEY_ROLES:
        raise ValidationFailed("API keys may be finance_operator, auditor or viewer", field="role")
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ValidationFailed("name must be 1-120 characters", field="name")
    if expires_in_days is not None and not 1 <= expires_in_days <= 730:
        raise ValidationFailed("expires_in_days must be 1-730", field="expires_in_days")
    prefix = "wtx_key_" + secrets.token_hex(4)
    plaintext = f"{prefix}_{secrets.token_urlsafe(32)}"
    with session.begin():
        key = ApiKey(
            org_id=actor.org_id,
            name=name,
            prefix=prefix,
            secret_hash=_sha256(plaintext),
            role=role,
            created_by_user_id=UUID(actor.actor_id)
            if actor.actor_type == ActorType.USER and actor.actor_id
            else None,
            expires_at=now() + timedelta(days=expires_in_days) if expires_in_days else None,
        )
        session.add(key)
        session.flush()
        audit.record(
            session,
            actor,
            "api_key.created",
            target_type="api_key",
            target_id=key.id,
            metadata={"prefix": prefix, "role": str(role)},
        )
    return key, plaintext


def list_api_keys(session: Session, actor: Actor) -> list[ApiKey]:
    actor.require(Permission.API_KEYS_MANAGE)
    return list(
        session.execute(
            select(ApiKey).where(ApiKey.org_id == actor.org_id).order_by(ApiKey.created_at.desc())
        ).scalars()
    )


def revoke_api_key(session: Session, actor: Actor, *, key_id: UUID) -> ApiKey:
    actor.require(Permission.API_KEYS_MANAGE)
    with session.begin():
        key = session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == actor.org_id).with_for_update()
        ).scalar_one_or_none()
        if key is None:
            raise NotFound("API key not found")
        if key.revoked_at is None:
            key.revoked_at = now()
            audit.record(
                session,
                actor,
                "api_key.revoked",
                target_type="api_key",
                target_id=key.id,
                metadata={"prefix": key.prefix},
            )
    return key


def rotate_api_key(
    session: Session, actor: Actor, *, key_id: UUID, grace_hours: int = 0
) -> tuple[ApiKey, str]:
    """Issue a replacement key; the old one stops working after ``grace_hours``."""
    actor.require(Permission.API_KEYS_MANAGE)
    if not 0 <= grace_hours <= 168:
        raise ValidationFailed("grace_hours must be 0-168", field="grace_hours")
    with session.begin():
        old = session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == actor.org_id).with_for_update()
        ).scalar_one_or_none()
        if old is None or old.revoked_at is not None:
            raise NotFound("API key not found")
        name, role = old.name, Role(old.role)
        cutoff = now() + timedelta(hours=grace_hours)
        if grace_hours == 0:
            old.revoked_at = now()
        elif old.expires_at is None or old.expires_at > cutoff:
            old.expires_at = cutoff
        audit.record(
            session,
            actor,
            "api_key.rotated",
            target_type="api_key",
            target_id=old.id,
            metadata={"prefix": old.prefix, "grace_hours": grace_hours},
        )
    return create_api_key(session, actor, name=name, role=role)


def resolve_api_key(session: Session, plaintext: str, correlation_id: str | None = None) -> Actor:
    if not plaintext.startswith("wtx_key_"):
        raise AuthenticationFailed("invalid API key")
    key = session.execute(select(ApiKey).where(ApiKey.secret_hash == _sha256(plaintext))).scalar_one_or_none()
    current = now()
    if key is None or key.revoked_at is not None or (key.expires_at and key.expires_at <= current):
        raise AuthenticationFailed("invalid API key")
    # Throttle last_used_at writes to once a minute per key.
    if key.last_used_at is None or current - key.last_used_at > timedelta(minutes=1):
        key.last_used_at = current
    return Actor(key.org_id, ActorType.API_KEY, str(key.id), key.prefix, Role(key.role), correlation_id)


def get_organization(session: Session, org_id: UUID) -> Organization:
    org = session.get(Organization, org_id)
    if org is None:
        raise NotFound("organization not found")
    return org
