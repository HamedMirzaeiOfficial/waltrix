"""Organizations, members and API keys (administrative API; never moves money)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from waltrix_core.db.models import ApiKey, User
from waltrix_core.enums import ActorType
from waltrix_core.permissions import permissions_for
from waltrix_core.services import identity
from waltrix_core.services.context import Actor

from .. import presenters
from .. import schemas as s
from ..deps import current_actor, current_user, get_db
from ..errors import ApiError

router = APIRouter(tags=["organizations"])


def _require_user(actor: Actor) -> None:
    if actor.actor_type != ActorType.USER:
        raise ApiError(403, "user_session_required", "this endpoint requires a dashboard user session")


@router.get("/organizations", response_model=list[s.MembershipOut])
def list_organizations(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[s.MembershipOut]:
    return [presenters.membership_out(m.organization, m.role) for m in identity.list_memberships(db, user.id)]


@router.post("/organizations", response_model=s.OrganizationOut, status_code=201)
def create_organization(
    body: s.OrganizationIn, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return identity.create_organization(db, user, name=body.name)


@router.get("/organizations/current", response_model=s.CurrentOrganizationOut)
def current_organization(db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    org = identity.get_organization(db, actor.org_id)
    return s.CurrentOrganizationOut(
        organization=s.OrganizationOut.model_validate(org),
        role=actor.role,
        permissions=sorted(str(p) for p in permissions_for(actor.role)),
        actor_type=str(actor.actor_type),
    )


@router.patch("/organizations/current", response_model=s.OrganizationOut)
def update_organization(
    body: s.OrganizationIn, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
):
    _require_user(actor)
    return identity.update_organization(db, actor, name=body.name)


def _member(m) -> s.MemberOut:  # type: ignore[no-untyped-def]
    return s.MemberOut(id=m.id, user=s.UserOut.model_validate(m.user), role=m.role, created_at=m.created_at)


@router.get("/organizations/current/members", response_model=list[s.MemberOut])
def list_members(db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    return [_member(m) for m in identity.list_members(db, actor)]


@router.post("/organizations/current/members", response_model=s.MemberOut, status_code=201)
def add_member(body: s.MemberIn, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    _require_user(actor)
    return _member(identity.add_member(db, actor, email=body.email, role=body.role))


@router.patch("/organizations/current/members/{membership_id}", response_model=s.MemberOut)
def change_role(
    membership_id: UUID,
    body: s.MemberRoleIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
):
    _require_user(actor)
    m = identity.change_member_role(db, actor, membership_id=membership_id, role=body.role)
    db.refresh(m)
    return _member(m)


@router.delete("/organizations/current/members/{membership_id}", status_code=204)
def remove_member(membership_id: UUID, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    _require_user(actor)
    identity.remove_member(db, actor, membership_id=membership_id)
    return Response(status_code=204)


# --- API keys -----------------------------------------------------------------


def _key_created(key: ApiKey, secret: str) -> s.ApiKeyCreatedOut:
    return s.ApiKeyCreatedOut(**s.ApiKeyOut.model_validate(key).model_dump(), secret=secret)


@router.get("/api-keys", response_model=list[s.ApiKeyOut], tags=["api-keys"])
def list_api_keys(db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    return identity.list_api_keys(db, actor)


@router.post("/api-keys", response_model=s.ApiKeyCreatedOut, status_code=201, tags=["api-keys"])
def create_api_key(body: s.ApiKeyIn, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    _require_user(actor)
    key, secret = identity.create_api_key(
        db, actor, name=body.name, role=body.role, expires_in_days=body.expires_in_days
    )
    return _key_created(key, secret)


@router.post("/api-keys/{key_id}/revoke", response_model=s.ApiKeyOut, tags=["api-keys"])
def revoke_api_key(key_id: UUID, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)):
    _require_user(actor)
    return identity.revoke_api_key(db, actor, key_id=key_id)


@router.post(
    "/api-keys/{key_id}/rotate", response_model=s.ApiKeyCreatedOut, status_code=201, tags=["api-keys"]
)
def rotate_api_key(
    key_id: UUID, body: s.ApiKeyRotateIn, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
):
    _require_user(actor)
    key, secret = identity.rotate_api_key(db, actor, key_id=key_id, grace_hours=body.grace_hours)
    return _key_created(key, secret)
