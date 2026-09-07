"""FastAPI auth/RBAC dependencies. The whole app depends on `current_user` /
`current_membership` and never on *how* the user authenticated.

RBAC model: org role (owner|admin|member|viewer) is coarse; `visible_agent_ids` layers the
granular rule — owner/admin see all; a member/viewer with ZERO explicit grants sees all
(coarse default), with ≥1 grant is restricted to the granted agents.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.auth.session import ACCESS_COOKIE, read_access, read_access_org
from voiceobs.db.models import AgentAccess, AppUser, Call, Membership
from voiceobs.db.session import get_session, use_org_schema

_ADMIN_ROLES = ("owner", "admin")


def current_user(request: Request, db: Session = Depends(get_session)) -> AppUser:
    """Authenticate and pin the request to the token's org schema. The org claim selects the
    schema BEFORE we look up the user, because app_user itself lives inside the org's schema."""
    cookie = request.cookies.get(ACCESS_COOKIE)
    uid = read_access(cookie)
    if not uid:
        raise HTTPException(401, "not authenticated")
    use_org_schema(db, read_access_org(cookie) or "default")
    user = db.get(AppUser, uid)
    if user is None or not user.is_active:
        raise HTTPException(401, "not authenticated")
    return user


def current_membership(
    user: AppUser = Depends(current_user),
    db: Session = Depends(get_session),
) -> Membership:
    """The user's membership in their org. Under schema-per-tenant a user belongs to exactly one
    org (the schema the request is already pinned to), so there is a single membership."""
    mem = db.scalars(select(Membership).where(Membership.user_id == user.id)).first()
    if mem is None:
        raise HTTPException(403, "no access to this organization")
    return mem


def require_role(*roles: str) -> Callable[..., Membership]:
    def dep(mem: Membership = Depends(current_membership)) -> Membership:
        if mem.role not in roles:
            raise HTTPException(403, "insufficient role")
        return mem
    return dep


def visible_agent_ids(db: Session, mem: Membership) -> list[str] | None:
    """The agent ids this membership may see, or None meaning "all agents in the org"."""
    if mem.role in _ADMIN_ROLES:
        return None
    grants = db.scalars(
        select(AgentAccess.agent_id).where(AgentAccess.membership_id == mem.id)
    ).all()
    return list(grants) if grants else None


def get_scoped_call(
    call_id: str,
    mem: Membership = Depends(current_membership),
    db: Session = Depends(get_session),
) -> Call:
    """A call the caller is allowed to see, resolved by external id within their org. Cross-org
    or out-of-grant → 404 (never 403 — don't leak that the call exists)."""
    call = db.scalar(select(Call).where(Call.external_call_id == call_id))
    if call is None:
        raise HTTPException(404, "call not found")
    ids = visible_agent_ids(db, mem)
    if ids is not None and call.agent_id not in ids:
        raise HTTPException(404, "call not found")
    return call
