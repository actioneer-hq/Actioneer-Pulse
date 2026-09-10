"""Auth endpoints: signup (first user only), login, refresh, logout, logout-all, me,
accept-invite. The session is a short-lived access JWT (httpOnly `vo_access`) backed by a
rotating, revocable refresh token (httpOnly `vo_refresh`). The app only ever reads
current_user afterwards."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from voiceobs import ratelimit
from voiceobs.api.deps import session_dep
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
from voiceobs.config import get_config
from voiceobs.db.models import AppUser, Membership, Organization
from voiceobs.db.provision import provision_org
from voiceobs.db.session import DEFAULT_ORG, use_org_schema

router = APIRouter(prefix="/v1/auth")

# Readable (non-httpOnly) cookie carrying the active org slug, so the refresh/logout endpoints —
# which run without a valid access token — know which schema to operate in.
ORG_COOKIE = "vo_org"


def _set_auth_cookies(
    response: Response, user_id: str, db: Session, request: Request, org: str = DEFAULT_ORG
) -> None:
    """Mint an access JWT (carrying the org) + a rotating refresh token and set the httpOnly
    cookies. Also sets a readable CSRF cookie and the readable org cookie."""
    secure = not dev_open()
    ua = request.headers.get("user-agent")
    refresh_plain, _ = mint_refresh(db, user_id, user_agent=ua)
    response.set_cookie(
        ACCESS_COOKIE, issue_access(user_id, org), max_age=ACCESS_MAX_AGE_S,
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
    response.set_cookie(
        ORG_COOKIE, org, max_age=REFRESH_MAX_AGE_S,
        httponly=False, samesite="lax", secure=secure, path="/",  # readable by the SPA + refresh
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.delete_cookie(ORG_COOKIE, path="/")


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


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def limit_auth(bucket: str):
    """Per-IP fixed-window rate-limit dependency for an auth endpoint (429 when exceeded).
    No-op under dev-open / when Redis is unconfigured (fail-open)."""
    def dep(request: Request) -> None:
        c = get_config()
        if not ratelimit.allow(
            f"rl:{bucket}:{_client_ip(request)}", c.auth_rate_limit, c.auth_rate_window_s
        ):
            raise HTTPException(429, "too many attempts — slow down and try again")
    return dep


@router.get("/config")
def config(db: Session = Depends(session_dep)) -> dict:
    """Public bootstrap probe the login page calls first. `signup_open` is true only on a
    fresh install (no users yet). `dev_email`/`dev_password` are non-null ONLY under dev-open,
    so the form can prefill for a one-click sign-in; they are always null in a real deployment.
    """
    use_org_schema(db, DEFAULT_ORG)  # the bootstrap org lives in the default schema
    signup_open = not db.scalar(select(func.count()).select_from(AppUser))
    dev = dev_open()
    return {
        "dev_open": dev,
        "signup_open": signup_open,
        "dev_email": (get_config().bootstrap_email or DEV_EMAIL) if dev else None,
        "dev_password": DEV_PASSWORD if dev else None,
    }


@router.post("/signup")
def signup(
    body: SignupIn, request: Request, response: Response, db: Session = Depends(session_dep),
    _rl: None = Depends(limit_auth("signup")),
) -> dict:
    """Open ONLY when no users exist in the default org (first-run). After that, growth is
    invite-only. The bootstrap user + org live in the `default` schema."""
    org = provision_org(db, DEFAULT_ORG, body.org_name or "Default")  # pins the default schema
    if db.scalar(select(func.count()).select_from(AppUser)):
        raise HTTPException(403, "signup is closed — ask an admin to invite you")
    email = normalize_email(body.email)
    if not email or not body.password:
        raise HTTPException(400, "email and password are required")
    if body.org_name:
        org.name = body.org_name
    user = AppUser(email=email, password_hash=hash_password(body.password),
                   name=body.name, is_active=True)
    db.add(user)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    _set_auth_cookies(response, user.id, db, request, DEFAULT_ORG)
    return {"user": {"id": user.id, "email": user.email},
            "org": {"id": org.id, "name": org.name}}


def _ensure_dev_user(db: Session) -> None:
    """Idempotently seed the dev owner in the default org (dev-open only). No-op if it exists."""
    org = provision_org(db, DEFAULT_ORG, "Default")
    email = normalize_email(DEV_EMAIL)
    if db.scalar(select(AppUser).where(AppUser.email == email)):
        return
    user = AppUser(email=email, password_hash=hash_password(DEV_PASSWORD),
                   name="Dev", is_active=True)
    db.add(user)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    db.commit()


@router.post("/login")
def login(
    body: LoginIn, request: Request, response: Response, db: Session = Depends(session_dep),
    _rl: None = Depends(limit_auth("login")),
) -> dict:
    org = (body.org or DEFAULT_ORG).lower()
    email = normalize_email(body.email)
    c = get_config()
    lock_key = f"lock:login:{org}:{email}"
    if ratelimit.fail_count(lock_key) >= c.login_lockout_max:
        raise HTTPException(429, "account temporarily locked after repeated failed logins")
    use_org_schema(db, org)  # authenticate within the org's schema
    # Dev convenience: under dev-open, the login form prefills the seeded dev credentials. If that
    # account doesn't exist yet (fresh DB, or the DB was bootstrapped with a different first user so
    # `bootstrap`/signup no-op'd), create it on the fly so one-click sign-in always works. Never
    # runs in a real deployment (dev_open() false), and only for the exact seeded dev credentials.
    if dev_open() and org == DEFAULT_ORG and email == normalize_email(DEV_EMAIL) \
            and body.password == DEV_PASSWORD:
        _ensure_dev_user(db)
    user = provider_for("password").authenticate(
        db, {"email": body.email, "password": body.password}
    )
    if user is None:
        ratelimit.record_fail(lock_key, c.login_lockout_s)  # per-account brute-force lockout
        raise HTTPException(401, "invalid credentials")
    ratelimit.clear(lock_key)  # a good login resets the counter
    _set_auth_cookies(response, user.id, db, request, org)
    return {"user": {"id": user.id, "email": user.email}}


@router.post("/refresh")
def refresh(
    request: Request, response: Response, db: Session = Depends(session_dep),
    _: None = Depends(require_csrf), _rl: None = Depends(limit_auth("refresh")),
) -> dict:
    """Rotate the refresh token and mint a fresh access JWT. The only way an expired access
    session comes back to life; a revoked/reused refresh token is rejected (401)."""
    org = request.cookies.get(ORG_COOKIE) or DEFAULT_ORG
    use_org_schema(db, org)  # refresh tokens live per-schema
    presented = request.cookies.get(REFRESH_COOKIE)
    rotated = rotate_refresh(db, presented, user_agent=request.headers.get("user-agent"))
    if rotated is None:
        _clear_auth_cookies(response)
        raise HTTPException(401, "invalid or expired session")
    new_refresh, user_id = rotated
    secure = not dev_open()
    response.set_cookie(
        ACCESS_COOKIE, issue_access(user_id, org), max_age=ACCESS_MAX_AGE_S,
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
    use_org_schema(db, request.cookies.get(ORG_COOKIE) or DEFAULT_ORG)
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
    # A user belongs to exactly one org (this schema). current_user already pinned it.
    mem = db.scalar(select(Membership).where(Membership.user_id == user.id))
    org = db.scalar(select(Organization))  # one org per schema
    memberships = (
        [{"org_id": mem.org_id, "org_name": org.name if org else None,
          "org_slug": org.slug if org else None, "role": mem.role}]
        if mem else []
    )
    return {
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "memberships": memberships,
    }


@router.post("/accept-invite")
def accept_invite(
    body: AcceptInviteIn, request: Request, response: Response,
    db: Session = Depends(session_dep),
) -> dict:
    org = request.cookies.get(ORG_COOKIE) or DEFAULT_ORG
    use_org_schema(db, org)  # the invited user lives in the inviting org's schema
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
    _set_auth_cookies(response, user.id, db, request, org)
    return {"user": {"id": user.id, "email": user.email}}
