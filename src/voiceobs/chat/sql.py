"""The confined read-only SQL executor the chat agent's `execute_sql` tool runs through.

Queries run on the agent connection — authenticated as the read-only `pulse_agent_ro` role when
`agent_database_url` is set (production/Postgres), pinned to the org's `ag_<slug>` view schema. That
role can only read the curated views, so this is a hard wall, not a filter. On SQLite (dev) there is
no separate role; we fall back to the main engine with `PRAGMA query_only=ON` over the same views —
best-effort read-only, for local testing. Output is capped and JSON-safe; errors are sanitized so a
permission-denied never leaks a real table name."""

from __future__ import annotations

import datetime as _dt
import logging

from sqlalchemy import text

from voiceobs.db.session import agent_session, set_agent_scope, use_agent_schema

log = logging.getLogger(__name__)

_MAX_ROWS = 500
_TIMEOUT_MS = 5000


def _jsonable(v):
    if isinstance(v, _dt.datetime | _dt.date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(v))} bytes>"
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)


def run_agent_sql(org_slug: str, query: str, *, visible_agents: list[str] | None = None,
                  call_id: str | None = None, max_rows: int = _MAX_ROWS) -> dict:
    """Run one read-only query over the org's curated views, scoped to `visible_agents` (None = all,
    for owner/admin) and optionally bound to a single `call_id` (per-call chat). The scope is enforced
    by the view predicates via a per-request setting — NOT by the prompt. Returns
    {columns, rows, row_count, truncated} or {error}. Never raises."""
    session = agent_session()
    is_pg = session.get_bind().dialect.name == "postgresql"
    agents_val = "*" if visible_agents is None else ",".join(visible_agents)
    call_val = call_id or ""
    try:
        if is_pg:
            # Defense-in-depth on top of the pulse_agent_ro role: even a misconfigured role
            # cannot write inside a read-only transaction.
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text(f"SET LOCAL statement_timeout = '{_TIMEOUT_MS}ms'"))
            use_agent_schema(session, org_slug)  # search_path -> ag_<slug>
            # per-transaction scope the view predicates read (parameterized — never injectable)
            session.execute(text("SELECT set_config('pulse.visible_agents', :a, true)"),
                            {"a": agents_val})
            session.execute(text("SELECT set_config('pulse.call_id', :c, true)"), {"c": call_val})
        else:
            session.execute(text("PRAGMA query_only = ON"))  # dev best-effort read-only
            set_agent_scope(agents_val, call_val)  # SQLite: the current_setting UDF reads this
        result = session.execute(text(query))
        if result.returns_rows:
            cols = list(result.keys())
            fetched = result.fetchmany(max_rows + 1)
            truncated = len(fetched) > max_rows
            rows = [[_jsonable(c) for c in r] for r in fetched[:max_rows]]
            return {"columns": cols, "rows": rows, "row_count": len(rows),
                    "truncated": truncated}
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}
    except Exception as e:  # noqa: BLE001 — surface a clean message for the model to self-correct
        return {"error": _sanitize(str(e))}
    finally:
        session.rollback()  # never persist; ends the txn
        if not is_pg:
            try:
                session.execute(text("PRAGMA query_only = OFF"))  # don't leave a pooled conn read-only
            except Exception as e:  # noqa: BLE001
                log.debug("query_only reset failed: %s", e)
        session.close()


def _sanitize(msg: str) -> str:
    """Trim the driver noise to the first line and hide raw schema/table names in
    permission-denied errors (so the agent can't learn the real tables exist)."""
    first = msg.strip().splitlines()[0] if msg.strip() else "query failed"
    low = first.lower()
    if "permission denied" in low or "does not exist" in low:
        return ("query refers to something not available — you may only query the documented "
                "tables (calls, events, turns, utterances, metrics, judgments, clusters, "
                "call_clusters, call_embeddings, agents)")
    return first[:300]
