"""Auth endpoints: signup (first user only), login, logout, me, accept-invite. Sessions are
stateless signed cookies; the app only ever reads current_user afterwards."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from voiceobs.api.deps import session_dep
from voiceobs.api.orgs import unique_org_slug
from voiceobs.api.schemas import AcceptInviteIn, LoginIn, SignupIn
from voiceobs.auth import (
    COOKIE_NAME,
    MAX_AGE_S,
    current_user,
    hash_password,
    issue_session,
    normalize_email,
    provider_for,
    read_invite,
)
from voiceobs.auth.env import dev_open
from voiceobs.db.models import AppUser, Membership, Organization

router = APIRouter(prefix="/v1/auth")


def _set_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME, issue_session(user_id), max_age=MAX_AGE_S,
        httponly=True, samesite="lax", secure=not dev_open(), path="/",
    )


@router.post("/signup")
def signup(
    body: SignupIn, response: Response, db: Session = Depends(session_dep)
) -> dict:
    """Open ONLY when no users exist (first-run). After that, growth is invite-only."""
    if db.scalar(select(func.count()).select_from(AppUser)):
        raise HTTPException(403, "signup is closed — ask an admin to invite you")
    email = normalize_email(body.email)
    if not email or not body.password:
        raise HTTPException(400, "email and password are required")
    user = AppUser(email=email, password_hash=hash_password(body.password),
                   name=body.name, is_active=True)
    db.add(user)
    db.flush()
    org = Organization(name=body.org_name or "Default",
                       slug=unique_org_slug(db, body.org_name or "default"))
    db.add(org)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    _set_cookie(response, user.id)
    return {"user": {"id": user.id, "email": user.email},
            "org": {"id": org.id, "name": org.name}}


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(session_dep)) -> dict:
    user = provider_for("password").authenticate(
        db, {"email": body.email, "password": body.password}
    )
    if user is None:
        raise HTTPException(401, "invalid credentials")
    _set_cookie(response, user.id)
    return {"user": {"id": user.id, "email": user.email}}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(user: AppUser = Depends(current_user), db: Session = Depends(session_dep)) -> dict:
    mems = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    orgs = {
        o.id: o for o in db.scalars(
            select(Organization).where(Organization.id.in_([m.org_id for m in mems] or [""]))
        )
    }
    return {
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "memberships": [
            {"org_id": m.org_id, "org_name": orgs[m.org_id].name if m.org_id in orgs else None,
             "role": m.role}
            for m in mems
        ],
    }


@router.post("/accept-invite")
def accept_invite(
    body: AcceptInviteIn, response: Response, db: Session = Depends(session_dep)
) -> dict:
    uid = read_invite(body.token)
    if not uid:
        raise HTTPException(400, "invalid or expired invite")
    user = db.get(AppUser, uid)
    if user is None:
        raise HTTPException(400, "invalid invite")
    user.password_hash = hash_password(body.password)
    user.is_active = True
    if body.name:
        user.name = body.name
    _set_cookie(response, user.id)
    return {"user": {"id": user.id, "email": user.email}}
