"""Organizations + membership. An org IS a tenant; every member has a coarse role, and
admins invite/manage members. Granular per-agent grants live on the agents API (they need
agents to exist first)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from voiceobs.api.deps import session_dep
from voiceobs.api.schemas import AgentAccessIn, MemberIn, OrgIn, RoleIn
from voiceobs.auth import current_user, encode_invite, normalize_email
from voiceobs.db.models import Agent, AgentAccess, AppUser, Membership, Organization
from voiceobs.db.provision import provision_org

router = APIRouter(prefix="/v1/orgs")

_ADMIN = ("owner", "admin")
_ROLES = ("owner", "admin", "member", "viewer")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "org"


def unique_org_slug(db: Session, base: str) -> str:
    slug = slugify(base)
    if db.scalar(select(func.count()).select_from(Organization).where(Organization.slug == slug)) == 0:
        return slug
    n = 2
    while db.scalar(select(func.count()).select_from(Organization).where(Organization.slug == f"{slug}-{n}")):
        n += 1
    return f"{slug}-{n}"


def _membership(db: Session, org_id: str, user_id: str) -> Membership | None:
    return db.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )


def _require_admin(db: Session, org_id: str, user: AppUser) -> Membership:
    mem = _membership(db, org_id, user.id)
    if mem is None or mem.role not in _ADMIN:
        raise HTTPException(403, "admin role required")
    return mem


@router.get("")
def list_orgs(user: AppUser = Depends(current_user), db: Session = Depends(session_dep)) -> dict:
    mems = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    role = {m.org_id: m.role for m in mems}
    orgs = db.scalars(
        select(Organization).where(Organization.id.in_([m.org_id for m in mems] or [""]))
    ).all()
    return {"items": [{"id": o.id, "name": o.name, "slug": o.slug, "role": role.get(o.id)}
                      for o in orgs]}


@router.post("")
def create_org(
    body: OrgIn, user: AppUser = Depends(current_user), db: Session = Depends(session_dep)
) -> dict:
    """Provision a NEW tenant in its own schema (schema-per-tenant). Because users are schema-local,
    the caller is cloned into the new schema as its owner (same email + credentials), so they can
    sign in under the new org's slug. This never writes a second org into the caller's schema — that
    would break the one-org-per-schema isolation invariant the whole system relies on."""
    slug = unique_org_slug(db, body.slug or body.name)
    if db.get_bind().dialect.name == "postgresql":
        # capture the caller's identity before provision_org re-pins the session to the new schema
        email, pw_hash, name = user.email, user.password_hash, user.name
        org = provision_org(db, slug, body.name)  # CREATE SCHEMA t_<slug> + full table set, pins it
        owner = AppUser(email=email, password_hash=pw_hash, name=name, is_active=True)
        db.add(owner)
        db.flush()
        db.add(Membership(org_id=org.id, user_id=owner.id, role="owner"))
    else:
        # SQLite (dev/tests): a single flat schema holds every org — no new schema to provision, and
        # the caller already exists here, so reuse their user row for the owner membership.
        org = Organization(name=body.name, slug=slug)
        db.add(org)
        db.flush()
        db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    db.flush()
    return {"id": org.id, "name": org.name, "slug": org.slug}


@router.get("/{org_id}/members")
def list_members(
    org_id: str, user: AppUser = Depends(current_user), db: Session = Depends(session_dep)
) -> dict:
    if _membership(db, org_id, user.id) is None:
        raise HTTPException(403, "no access to this organization")
    rows = db.scalars(select(Membership).where(Membership.org_id == org_id)).all()
    users = {
        u.id: u for u in db.scalars(
            select(AppUser).where(AppUser.id.in_([r.user_id for r in rows] or [""]))
        )
    }
    return {"items": [
        {"membership_id": r.id, "user_id": r.user_id,
         "email": users[r.user_id].email if r.user_id in users else None, "role": r.role}
        for r in rows
    ]}


@router.post("/{org_id}/members")
def add_member(
    org_id: str, body: MemberIn,
    user: AppUser = Depends(current_user), db: Session = Depends(session_dep),
) -> dict:
    _require_admin(db, org_id, user)
    if body.role not in _ROLES:
        raise HTTPException(400, f"role must be one of {_ROLES}")
    email = normalize_email(body.email)
    target = db.scalar(select(AppUser).where(AppUser.email == email))
    invite = None
    if target is None:  # new person — stub account, activated when they accept the invite
        target = AppUser(email=email, is_active=True)
        db.add(target)
        db.flush()
        invite = encode_invite(target.id)
    elif _membership(db, org_id, target.id) is not None:
        raise HTTPException(409, "already a member")
    db.add(Membership(org_id=org_id, user_id=target.id, role=body.role))
    return {"user_id": target.id, "email": email, "role": body.role, "invite_token": invite}


@router.patch("/{org_id}/members/{mid}")
def set_role(
    org_id: str, mid: str, body: RoleIn,
    user: AppUser = Depends(current_user), db: Session = Depends(session_dep),
) -> dict:
    _require_admin(db, org_id, user)
    if body.role not in _ROLES:
        raise HTTPException(400, f"role must be one of {_ROLES}")
    mem = db.get(Membership, mid)
    if mem is None or mem.org_id != org_id:
        raise HTTPException(404, "member not found")
    mem.role = body.role
    return {"status": "ok"}


@router.delete("/{org_id}/members/{mid}")
def remove_member(
    org_id: str, mid: str,
    user: AppUser = Depends(current_user), db: Session = Depends(session_dep),
) -> dict:
    _require_admin(db, org_id, user)
    mem = db.get(Membership, mid)
    if mem is None or mem.org_id != org_id:
        raise HTTPException(404, "member not found")
    db.delete(mem)
    return {"status": "ok"}


@router.put("/{org_id}/members/{mid}/agent-access")
def set_agent_access(
    org_id: str, mid: str, body: AgentAccessIn,
    user: AppUser = Depends(current_user), db: Session = Depends(session_dep),
) -> dict:
    """Replace a member's granular grant set. Empty list = coarse default (all org agents).
    Agent ids must belong to this org."""
    _require_admin(db, org_id, user)
    mem = db.get(Membership, mid)
    if mem is None or mem.org_id != org_id:
        raise HTTPException(404, "member not found")
    valid = {a.id for a in db.scalars(select(Agent).where(Agent.org_id == org_id))}
    bad = [a for a in body.agent_ids if a not in valid]
    if bad:
        raise HTTPException(400, f"agents not in this org: {bad}")
    db.execute(
        AgentAccess.__table__.delete().where(AgentAccess.membership_id == mid)
    )
    for aid in dict.fromkeys(body.agent_ids):  # dedupe, preserve order
        db.add(AgentAccess(membership_id=mid, agent_id=aid))
    return {"status": "ok", "agent_ids": list(dict.fromkeys(body.agent_ids))}
