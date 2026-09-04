"""Auth endpoints: signup (first user only), login, refresh, logout, logout-all, me,
accept-invite. The session is a short-lived access JWT (httpOnly `vo_access`) backed by a
rotating, revocable refresh token (httpOnly `vo_refresh`). The app only ever reads
current_user afterwards."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from voiceobs.api.deps import session_dep
from voiceobs.api.orgs import unique_org_slug
from voiceobs.api.schemas import AcceptInviteIn, LoginIn, SignupIn
from voiceobs.auth import (
    ACCESS_COOKIE,
    ACCESS_MAX_AGE_S,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    REFRESH_MAX_AGE_S,
    REFRESH_PATH,
    current_user,
    decode_invite,
    hash_password,
    issue_access,
    mint_refresh,
    normalize_email,
    provider_for,
    revoke_all,
    revoke_refresh,
    rotate_refresh,
)
from voiceobs.auth.env import DEV_EMAIL, DEV_PASSWORD, dev_open
from voiceobs.db.models import AppUser, Membership, Organization
from voiceobs.settings import get_settings

router = APIRouter(prefix="/v1/auth")


def _set_auth_cookies(response: Response, user_id: str, db: Session, request: Request) -> None:
    """Mint an access JWT + a rotating refresh token and set the httpOnly cookies. Also sets a
    readable CSRF cookie the SPA echoes back as X-CSRF-Token on unsafe requests."""
    secure = not dev_open()
    ua = request.headers.get("user-agent")
    refresh_plain, _ = mint_refresh(db, user_id, user_agent=ua)
    response.set_cookie(
        ACCESS_COOKIE, issue_access(user_id), max_age=ACCESS_MAX_AGE_S,
        httponly=True, samesite="lax", secure=secure, path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE, refresh_plain, max_age=REFRESH_MAX_AGE_S,
        httponly=True, samesite="lax", secure=secure, path=REFRESH_PATH,
    )
    response.set_cookie(
        CSRF_COOKIE, secrets.token_urlsafe(24), max_age=REFRESH_MAX_AGE_S,
        httponly=False, samesite="lax", secure=secure, path="/",  # readable by the SPA
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")


def require_csrf(request: Request) -> None:
    """Double-submit CSRF guard for cookie-authenticated writes: the X-CSRF-Token header must
    match the vo_csrf cookie. Both are same-origin-only in practice; an attacker's cross-site
    request can send neither. Skipped under dev-open to keep tests/local frictionless."""
    if dev_open():
        return
    header = request.headers.get("x-csrf-token")
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or not secrets.compare_digest(header, cookie):
        raise HTTPException(403, "CSRF check failed")


@router.get("/config")
def config(db: Session = Depends(session_dep)) -> dict:
    """Public bootstrap probe the login page calls first. `signup_open` is true only on a
    fresh install (no users yet). `dev_email`/`dev_password` are non-null ONLY under dev-open,
    so the form can prefill for a one-click sign-in; they are always null in a real deployment.
    """
    signup_open = not db.scalar(select(func.count()).select_from(AppUser))
    dev = dev_open()
    return {
        "dev_open": dev,
        "signup_open": signup_open,
        "dev_email": (get_settings().bootstrap_email or DEV_EMAIL) if dev else None,
        "dev_password": DEV_PASSWORD if dev else None,
    }


@router.post("/signup")
def signup(
    body: SignupIn, request: Request, response: Response, db: Session = Depends(session_dep)
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
    _set_auth_cookies(response, user.id, db, request)
    return {"user": {"id": user.id, "email": user.email},
            "org": {"id": org.id, "name": org.name}}


@router.post("/login")
def login(
    body: LoginIn, request: Request, response: Response, db: Session = Depends(session_dep)
) -> dict:
    user = provider_for("password").authenticate(
        db, {"email": body.email, "password": body.password}
    )
    if user is None:
        raise HTTPException(401, "invalid credentials")
    _set_auth_cookies(response, user.id, db, request)
    return {"user": {"id": user.id, "email": user.email}}


@router.post("/refresh")
def refresh(
    request: Request, response: Response, db: Session = Depends(session_dep),
    _: None = Depends(require_csrf),
) -> dict:
    """Rotate the refresh token and mint a fresh access JWT. The only way an expired access
    session comes back to life; a revoked/reused refresh token is rejected (401)."""
    presented = request.cookies.get(REFRESH_COOKIE)
    rotated = rotate_refresh(db, presented, user_agent=request.headers.get("user-agent"))
    if rotated is None:
        _clear_auth_cookies(response)
        raise HTTPException(401, "invalid or expired session")
    new_refresh, user_id = rotated
    secure = not dev_open()
    response.set_cookie(
        ACCESS_COOKIE, issue_access(user_id), max_age=ACCESS_MAX_AGE_S,
        httponly=True, samesite="lax", secure=secure, path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE, new_refresh, max_age=REFRESH_MAX_AGE_S,
        httponly=True, samesite="lax", secure=secure, path=REFRESH_PATH,
    )
    return {"status": "ok"}


@router.post("/logout")
def logout(
    request: Request, response: Response, db: Session = Depends(session_dep),
    _: None = Depends(require_csrf),
) -> dict:
    """Revoke this session's refresh token and clear cookies. The access JWT dies on its own
    within its short TTL."""
    revoke_refresh(db, request.cookies.get(REFRESH_COOKIE))
    _clear_auth_cookies(response)
    return {"status": "ok"}


@router.post("/logout-all")
def logout_all(
    response: Response, db: Session = Depends(session_dep),
    user: AppUser = Depends(current_user), _: None = Depends(require_csrf),
) -> dict:
    """Log out everywhere: revoke every refresh token for this user."""
    n = revoke_all(db, user.id)
    _clear_auth_cookies(response)
    return {"status": "ok", "revoked": n}


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
    body: AcceptInviteIn, request: Request, response: Response,
    db: Session = Depends(session_dep),
) -> dict:
    uid = decode_invite(body.token)
    if not uid:
        raise HTTPException(400, "invalid or expired invite")
    user = db.get(AppUser, uid)
    if user is None:
        raise HTTPException(400, "invalid invite")
    user.password_hash = hash_password(body.password)
    user.is_active = True
    if body.name:
        user.name = body.name
    _set_auth_cookies(response, user.id, db, request)
    return {"user": {"id": user.id, "email": user.email}}
