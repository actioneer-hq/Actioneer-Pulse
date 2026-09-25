"""The SQL chat-agent's entire visible database: a curated set of read-only VIEWS per org.

The agent connects as `pulse_agent_ro`, a login role granted USAGE on only the `ag_<org>` schema and
SELECT on only these views — nothing on the real `t_<org>` tables, nothing else. Postgres views run
with their owner's rights, so the views read the real tables while the agent role has no grant there.
To the agent, this menu IS the whole database; identity/secret tables don't exist in its world.

Curation drops plumbing/gates/raw-clock/JSON-blob columns and keeps analysis-relevant ones. Transcript
text (turns/events) and the pgvector `embedding` (for cosine `<=>` similarity) are deliberately kept.
On SQLite (dev) the same views are created in the single schema for local testing — no role isolation.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from voiceobs.config import get_config
from voiceobs.db.session import ag_schema, org_schema

AGENT_ROLE = "pulse_agent_ro"

# view name -> (source table, curated column list, scope kind). The agent sees these names only.
# scope kind drives the per-request authorization predicate baked into the view body:
#   "call"       — base table is `call`: filter its own agent_id + id (call id)
#   "agent"      — base table is `agent`: its own id IS the agent id (no call filter)
#   "own_call"   — base row carries agent_id + call_id (call_cluster)
#   "own"        — base row carries agent_id, no call linkage (cluster)
#   "via_call"   — call-keyed row: reach agent_id/id through an EXISTS join to `call`
AGENT_VIEWS: dict[str, tuple[str, str, str]] = {
    "calls": ("call", (
        "id, external_call_id, agent_id, source, environment, engine, carrier, "
        "stt_provider, llm_provider, tts_provider, voice, campaign_id, started_at, ended_at, "
        "duration_s, status, terminal_reason, hangup_by, cost_llm, cost_stt, cost_tts, "
        "cost_total, cost_currency, tokens_in, tokens_out, tokens_cached, stt_seconds, "
        "bookmarked, created_at"
    ), "call"),
    "events": ("event", (
        "call_id, span_id, parent_span_id, turn_id, t_offset_s, kind, type, name, "
        "duration_s, error, content_text, content_kind"
    ), "via_call"),
    "turns": ("turn", (
        "call_id, turn_index, trigger, interrupted, abandoned, response_latency_ms, stt_lag_ms, "
        "endpointing_ms, llm_ttft_ms, assembly_ms, dispatch_ms, tts_ttfb_ms, playout_ms, "
        "e2e_latency_ms, language, stt_confidence, tokens_in, tokens_out, finish_reason, "
        "tts_cancelled, cut_reason, caller_transcript, llm_spoken"
    ), "via_call"),
    "utterances": ("utterance", "call_id, channel, t_start_s, t_end_s", "via_call"),
    "metrics": ("metric", "call_id, name, value_num, value_text, available, reason", "via_call"),
    "judgments": ("judgment", (
        "call_id, disposition, status, sentiment, objective_achieved, answered_by, "
        "primary_language, secondary_languages, script_adherence, escalation_requested, "
        "callback_requested, callback_time, guardrail_violation, guardrail_violation_points, "
        "is_failure, root_cause, model_fault, model_fault_detail, hallucination, "
        "hallucination_detail, suggested_fix, summary, judged_at"
    ), "via_call"),
    "clusters": ("cluster", "lever, cluster_key, label, size, updated_at", "own"),
    "call_clusters": ("call_cluster", "call_id, lever, cluster_key, x, y", "own_call"),
    "call_embeddings": ("call_embedding", "call_id, field, embedding, model", "via_call"),
    "agents": ("agent", "id, name, slug", "agent"),
}


def _agent_member(col: str, is_pg: bool) -> str:
    """SQL predicate: `col` (an agent id) is in the request's visible-agents set (or all = '*')."""
    va = ("current_setting('pulse.visible_agents', true)" if is_pg
          else "current_setting('pulse.visible_agents')")
    if is_pg:
        return f"({va} = '*' OR {col} = ANY(string_to_array({va}, ',')))"
    return f"({va} = '*' OR instr(',' || {va} || ',', ',' || {col} || ',') > 0)"


def _call_match(col: str, is_pg: bool) -> str:
    """SQL predicate: no per-call binding (empty), or `col` (a call id) equals the bound call."""
    cs = ("current_setting('pulse.call_id', true)" if is_pg
          else "current_setting('pulse.call_id')")
    return f"(coalesce({cs}, '') = '' OR {col} = {cs})"


def _predicate(scope: str, t: str, is_pg: bool) -> str:
    """The WHERE body that scopes a view to the request's visible agents (+ bound call). `b` is the
    base-table alias. `t` is the real-schema qualifier (quoted for PG, empty for SQLite)."""
    call_tbl = f'{t}"call"' if is_pg else "call"
    if scope == "call":
        return f"{_agent_member('b.agent_id', is_pg)} AND {_call_match('b.id', is_pg)}"
    if scope == "agent":
        return _agent_member("b.id", is_pg)
    if scope == "own_call":
        return f"{_agent_member('b.agent_id', is_pg)} AND {_call_match('b.call_id', is_pg)}"
    if scope == "own":
        return _agent_member("b.agent_id", is_pg)
    # via_call: reach the owning call's agent_id + id through an EXISTS join
    return (f"EXISTS (SELECT 1 FROM {call_tbl} c WHERE c.id = b.call_id "
            f"AND {_agent_member('c.agent_id', is_pg)} AND {_call_match('c.id', is_pg)})")


def ensure_agent_role(db: Session) -> None:
    """Create the read-only login role if missing (Postgres only, idempotent)."""
    if db.get_bind().dialect.name != "postgresql":
        return
    exists = db.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": AGENT_ROLE}
    ).scalar()
    if not exists:
        pw = get_config().agent_db_password.replace("'", "''")
        db.execute(text(f"CREATE ROLE {AGENT_ROLE} LOGIN PASSWORD '{pw}'"))


def build_agent_views(db: Session, slug: str) -> None:
    """(Re)build the org's curated view menu and grant the agent role read access. Assumes the org's
    real schema (`t_<slug>`) already exists. Postgres: dedicated `ag_<slug>` schema + role grants.
    SQLite: the same views in the single flat schema (no role wall)."""
    is_pg = db.get_bind().dialect.name == "postgresql"
    if is_pg:
        ensure_agent_role(db)
        ag, t = ag_schema(slug), org_schema(slug)
        tq = f'"{t}".'  # schema qualifier for the real tables
        db.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{ag}"'))
        for view, (table, cols, scope) in AGENT_VIEWS.items():
            pred = _predicate(scope, tq, is_pg)
            db.execute(text(
                f'CREATE OR REPLACE VIEW "{ag}"."{view}" AS '
                f'SELECT {cols} FROM "{t}"."{table}" b WHERE {pred}'
            ))
        db.execute(text(f'GRANT USAGE ON SCHEMA "{ag}" TO {AGENT_ROLE}'))
        db.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{ag}" TO {AGENT_ROLE}'))
    else:  # SQLite dev — flat schema, no roles; recreate the menu views (apply current predicate)
        for view, (table, cols, scope) in AGENT_VIEWS.items():
            pred = _predicate(scope, "", is_pg)
            db.execute(text(f"DROP VIEW IF EXISTS {view}"))
            db.execute(text(f"CREATE VIEW {view} AS SELECT {cols} FROM {table} b WHERE {pred}"))
