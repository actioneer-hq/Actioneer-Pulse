"""Read-only, RBAC-scoped tools the global-chat agent can call over an org's calls. Every query
is bounded by the caller's membership (org + visible agents) — the agent can never see a call the
user couldn't. Extend the registry to give the agent more reach."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.auth import visible_agent_ids
from voiceobs.db.models import Call, Judgment, Membership, Turn


def _scope(stmt, db: Session, mem: Membership):
    stmt = stmt.where(Call.tenant_id == mem.org_id)
    ids = visible_agent_ids(db, mem)
    if ids is not None:
        stmt = stmt.where(Call.agent_id.in_(ids))
    return stmt


def search_calls(db: Session, mem: Membership, args: dict) -> dict:
    stmt = select(Call).order_by(Call.started_at.desc().nulls_last()).limit(
        min(int(args.get("limit", 20)), 100))
    stmt = _scope(stmt, db, mem)
    if args.get("status"):
        stmt = stmt.where(Call.status == args["status"])
    if args.get("agent_id"):
        stmt = stmt.where(Call.agent_id == args["agent_id"])
    if args.get("q"):
        like = f"%{args['q']}%"
        stmt = stmt.where(Call.external_call_id.ilike(like) | Call.source.ilike(like))
    calls = db.scalars(stmt).all()
    return {"count": len(calls), "calls": [
        {"id": c.external_call_id, "status": c.status, "source": c.source,
         "started_at": c.started_at.isoformat() if c.started_at else None,
         "duration_s": c.duration_s, "llm": c.llm_provider}
        for c in calls
    ]}


def get_call(db: Session, mem: Membership, args: dict) -> dict:
    cid = args.get("external_id") or args.get("id")
    stmt = _scope(select(Call).where(Call.external_call_id == cid), db, mem)
    call = db.scalar(stmt)
    if call is None:
        return {"error": "call not found"}
    turns = db.scalars(select(Turn).where(Turn.call_id == call.id)).all()
    j = db.scalar(select(Judgment).where(Judgment.call_id == call.id))
    return {
        "id": call.external_call_id, "status": call.status, "source": call.source,
        "engine": call.engine, "duration_s": call.duration_s,
        "stt": call.stt_provider, "llm": call.llm_provider, "tts": call.tts_provider,
        "cost": call.cost_total, "turns": len(turns),
        "judgment": None if j is None else {
            "disposition": j.disposition, "sentiment": j.sentiment,
            "objective_achieved": j.objective_achieved, "summary": j.summary},
    }


# name -> (runner, OpenAI tool schema)
_TOOLS: dict[str, tuple[Callable[[Session, Membership, dict], dict], dict]] = {
    "search_calls": (search_calls, {
        "type": "function",
        "function": {
            "name": "search_calls",
            "description": "List/search the org's calls (most recent first). Use to answer "
                           "questions about volume, status, or to find calls to inspect.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string",
                               "description": "filter, e.g. 'ingested', 'unsupported'"},
                    "agent_id": {"type": "string"},
                    "q": {"type": "string", "description": "match call id or source"},
                    "limit": {"type": "integer", "description": "max results (<=100)"},
                },
            },
        },
    }),
    "get_call": (get_call, {
        "type": "function",
        "function": {
            "name": "get_call",
            "description": "Full detail for one call by its external id: providers, cost, turn "
                           "count, and the LLM judgment if present.",
            "parameters": {
                "type": "object",
                "properties": {"external_id": {"type": "string"}},
                "required": ["external_id"],
            },
        },
    }),
}


def schemas() -> list[dict]:
    return [schema for _, schema in _TOOLS.values()]


def run(db: Session, mem: Membership, name: str, args: dict) -> dict:
    entry = _TOOLS.get(name)
    if entry is None:
        return {"error": f"unknown tool: {name}"}
    return entry[0](db, mem, args)
