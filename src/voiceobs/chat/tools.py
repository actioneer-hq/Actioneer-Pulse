"""The global-chat agent's single tool: `execute_sql`. It runs a read-only query through the
confined agent connection (`chat/sql.run_agent_sql`) over the org's curated view menu — the agent
can only ever see/read those views (see db/agent_views.py). Tenant scope is the schema; the org
slug is read from the request session (one org per schema)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.chat.sql import run_agent_sql
from voiceobs.db.models import Membership, Organization


def execute_sql(db: Session, mem: Membership, args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "no query provided"}
    slug = db.scalar(select(Organization.slug)) or "default"  # one org per schema
    return run_agent_sql(slug, query)


_TOOLS = {
    "execute_sql": (execute_sql, {
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
    }),
}


def schemas() -> list[dict]:
    return [schema for _, schema in _TOOLS.values()]


def run(db: Session, mem: Membership, name: str, args: dict) -> dict:
    entry = _TOOLS.get(name)
    if entry is None:
        return {"error": f"unknown tool: {name}"}
    return entry[0](db, mem, args)
