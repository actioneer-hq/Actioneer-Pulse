"""The global-chat agent's single tool: `execute_sql`. It runs a read-only query through the
confined agent connection (`chat/sql.run_agent_sql`) over the org's curated view menu — the agent
can only ever see/read those views (see db/agent_views.py). Tenant scope is the schema; the org
slug is read from the request session (one org per schema)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.auth import visible_agent_ids
from voiceobs.chat.sql import run_agent_sql
from voiceobs.db.models import Call, Membership, Organization


def execute_sql(db: Session, mem: Membership, args: dict, *, call: Call | None = None) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "no query provided"}
    slug = db.scalar(select(Organization.slug)) or "default"  # one org per schema
    # Enforce per-agent RBAC server-side (not via the prompt): the view predicates restrict rows to
    # the caller's visible agents, and — in per-call chat — to the bound call only.
    allowed = visible_agent_ids(db, mem)  # None => owner/admin (all agents)
    return run_agent_sql(slug, query, visible_agents=allowed,
                         call_id=(call.id if call is not None else None))


_SQL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "execute_sql",
        "description": "Run ONE read-only SQL query (PostgreSQL) over the documented tables and "
                       "get back the rows. Use it for any question that needs real data.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "A single SELECT/WITH query. Always add a LIMIT."},
            },
            "required": ["query"],
        },
    },
}


def _audio_native_schema(bound_call: bool) -> dict:
    # Per-call chat is bound to its call (prompt only); global chat must name the call_id.
    props = {"prompt": {"type": "string",
                        "description": "The question to ask about the call's audio."}}
    required = ["prompt"]
    if not bound_call:
        props["call_id"] = {"type": "string", "description": "External id of the call to listen to."}
        required.append("call_id")
    return {
        "type": "function",
        "function": {
            "name": "audio_native_llm",
            "description": "Send a call's recording to an audio model that LISTENS and answers. "
                           "ONLY for questions that require hearing the audio (tone, emotion, raised "
                           "voices, background noise/music, audio quality, crosstalk). Never for "
                           "anything the tables answer (transcripts, metrics, timings, counts) — use "
                           "execute_sql for those. Slow and costly: call it on one specific call only.",
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


def schemas(audio_native: bool = False, bound_call: bool = False) -> list[dict]:
    out = [_SQL_SCHEMA]
    if audio_native:
        out.append(_audio_native_schema(bound_call))
    return out


def run(db: Session, mem: Membership, name: str, args: dict, *, call: Call | None = None) -> dict:
    if name == "execute_sql":
        return execute_sql(db, mem, args, call=call)
    if name == "audio_native_llm":
        return _run_audio_native(db, mem, args, call)
    return {"error": f"unknown tool: {name}"}


def _run_audio_native(db: Session, mem: Membership, args: dict, call: Call | None) -> dict:
    from voiceobs.chat import audio_native

    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return {"error": "no prompt provided"}
    target = call
    if target is None:  # global chat — resolve the named call within the org (respect visibility)
        cid = (args.get("call_id") or "").strip()
        if not cid:
            return {"error": "call_id is required"}
        target = db.scalar(select(Call).where(Call.external_call_id == cid))
        allowed = visible_agent_ids(db, mem)
        if target is None or (allowed is not None and target.agent_id not in allowed):
            return {"error": f"call not found: {cid}"}
    return {"analysis": audio_native.analyze(db, target, prompt)}
