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

# view name -> (source table, curated column list). The agent sees these names only.
AGENT_VIEWS: dict[str, tuple[str, str]] = {
    "calls": ("call", (
        "id, external_call_id, agent_id, source, environment, engine, carrier, "
        "stt_provider, llm_provider, tts_provider, voice, campaign_id, started_at, ended_at, "
        "duration_s, status, terminal_reason, hangup_by, cost_llm, cost_stt, cost_tts, "
        "cost_total, cost_currency, tokens_in, tokens_out, tokens_cached, stt_seconds, "
        "bookmarked, created_at"
    )),
    "events": ("event", (
        "call_id, span_id, parent_span_id, turn_id, t_offset_s, kind, type, name, "
        "duration_s, error, content_text, content_kind"
    )),
    "turns": ("turn", (
        "call_id, turn_index, trigger, interrupted, abandoned, response_latency_ms, stt_lag_ms, "
        "endpointing_ms, llm_ttft_ms, assembly_ms, dispatch_ms, tts_ttfb_ms, playout_ms, "
        "e2e_latency_ms, language, stt_confidence, tokens_in, tokens_out, finish_reason, "
        "tts_cancelled, cut_reason, caller_transcript, llm_spoken"
    )),
    "utterances": ("utterance", "call_id, channel, t_start_s, t_end_s"),
    "metrics": ("metric", "call_id, name, value_num, value_text, available, reason"),
    "judgments": ("judgment", (
        "call_id, disposition, status, sentiment, objective_achieved, answered_by, "
        "primary_language, secondary_languages, script_adherence, escalation_requested, "
        "callback_requested, callback_time, guardrail_violation, guardrail_violation_points, "
        "is_failure, root_cause, model_fault, model_fault_detail, hallucination, "
        "hallucination_detail, suggested_fix, summary, judged_at"
    )),
    "clusters": ("cluster", "lever, cluster_key, label, size, updated_at"),
    "call_clusters": ("call_cluster", "call_id, lever, cluster_key, x, y"),
    "call_embeddings": ("call_embedding", "call_id, field, embedding, model"),
    "agents": ("agent", "id, name, slug"),
}


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
        db.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{ag}"'))
        for view, (table, cols) in AGENT_VIEWS.items():
            db.execute(text(
                f'CREATE OR REPLACE VIEW "{ag}"."{view}" AS SELECT {cols} FROM "{t}"."{table}"'
            ))
        db.execute(text(f'GRANT USAGE ON SCHEMA "{ag}" TO {AGENT_ROLE}'))
        db.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{ag}" TO {AGENT_ROLE}'))
    else:  # SQLite dev — flat schema, no roles; create the menu views for local testing
        for view, (table, cols) in AGENT_VIEWS.items():
            db.execute(text(f"CREATE VIEW IF NOT EXISTS {view} AS SELECT {cols} FROM {table}"))
