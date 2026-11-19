"""Dashboard authentication (cookie sessions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from waltrix_core.db.models import User
from waltrix_core.services import identity

from .. import presenters
from .. import schemas as s
from ..deps import _enforce_rate_limit, client_ip, current_user, get_db
from ..settings import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=int(identity.SESSION_TTL.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure or settings.is_production,
        samesite="strict",
        path=settings.session_cookie_path,
    )


def _me(db: Session, user: User) -> s.MeOut:
    return s.MeOut(
        user=s.UserOut.model_validate(user),
        memberships=[
            presenters.membership_out(m.organization, m.role) for m in identity.list_memberships(db, user.id)
        ],
    )


@router.post("/register", response_model=s.UserOut, status_code=201)
def register(
    body: s.RegisterIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    _enforce_rate_limit(f"register:{client_ip(request, settings)}", settings.login_rate_limit_per_minute)
    return identity.register_user(
        db, email=body.email, password=body.password, display_name=body.display_name
    )


@router.post("/login", response_model=s.MeOut)
def login(
    body: s.LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> s.MeOut:
    ip = client_ip(request, settings)
    _enforce_rate_limit(f"login:{ip}", settings.login_rate_limit_per_minute)
    _enforce_rate_limit(f"login-email:{body.email.strip().lower()}", settings.login_rate_limit_per_minute)
    user, token = identity.login(db, email=body.email, password=body.password)
    _set_cookie(response, settings, token)
    return _me(db, user)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(current_user),
) -> Response:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        identity.logout(db, token)
    response.delete_cookie(settings.session_cookie_name, path=settings.session_cookie_path)
    response.status_code = 204
    return response


@router.get("/me", response_model=s.MeOut)
def me(db: Session = Depends(get_db), user: User = Depends(current_user)) -> s.MeOut:
    return _me(db, user)
