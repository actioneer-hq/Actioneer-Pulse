"""Schema tests — metadata stands up and the load-bearing constraints exist.

Runs against in-memory SQLite (no live Postgres in CI). Asserts the 13 tables and
the idempotency/query constraints the docs call out, plus tenant_id everywhere.
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect

from voiceobs.db import Base

# Data tables carry the loose `tenant_id` (= Organization.id). Identity tables DEFINE
# tenancy (real FKs among themselves) and deliberately do NOT carry tenant_id.
DATA_TABLES = {
    "prompt", "call", "raw_fragment", "event", "utterance", "turn", "metric",
    "metric_def", "media", "ingest_run", "annotation", "label", "tombstone",
    "transcript", "judgment", "call_embedding", "tenant_settings", "audio_discrepancy",
    "conversation", "chat_message", "cluster", "call_cluster", "backfill_job", "call_params",
}
IDENTITY_TABLES = {
    "organization", "app_user", "membership", "agent", "agent_access", "ingest_token",
    "refresh_token", "agent_audio_config", "agent_integration_manifest",
    "agent_otlp_mapping", "agent_script",
    "agent_guardrail", "agent_params_upload",
}
EXPECTED_TABLES = DATA_TABLES | IDENTITY_TABLES


def _inspector():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return inspect(engine)


def test_all_tables_created():
    insp = _inspector()
    assert set(insp.get_table_names()) == EXPECTED_TABLES


def test_integration_manifest_has_ingest_routing_columns():
    insp = _inspector()
    cols = {c["name"] for c in insp.get_columns("agent_integration_manifest")}
    assert {"ingest_method", "last_polled_modified"} <= cols


def test_no_tenant_id_on_any_data_table():
    insp = _inspector()
    for table in DATA_TABLES:
        cols = {c["name"] for c in insp.get_columns(table)}
        assert "tenant_id" not in cols, f"{table} should not carry tenant_id"


def test_identity_constraints_and_call_agent_id():
    insp = _inspector()
    assert "agent_id" in {c["name"] for c in insp.get_columns("call")}
    mem_uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("membership")}
    assert ("org_id", "user_id") in mem_uniques
    agent_uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("agent")}
    assert ("org_id", "slug") in agent_uniques
    access_uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("agent_access")}
    assert ("membership_id", "agent_id") in access_uniques
    user_uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("app_user")}
    assert ("email",) in user_uniques


def test_call_unique_external_id():
    insp = _inspector()
    uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("call")}
    assert ("external_call_id",) in uniques


def test_metric_constraints_and_query_index():
    insp = _inspector()
    uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("metric")}
    assert ("call_id", "name", "metric_version") in uniques
    # the daily metric-predicate query index
    idx_names = {i["name"] for i in insp.get_indexes("metric")}
    assert "ix_metric_name_value" in idx_names
    idx_cols = {tuple(i["column_names"]) for i in insp.get_indexes("metric")}
    assert ("name", "value_num") in idx_cols


def test_media_and_turn_and_annotation_uniques():
    insp = _inspector()
    assert ("call_id", "kind", "sha256") in {
        tuple(u["column_names"]) for u in insp.get_unique_constraints("media")
    }
    assert ("call_id", "turn_index") in {
        tuple(u["column_names"]) for u in insp.get_unique_constraints("turn")
    }
    assert ("call_id", "kind", "source", "body_sha256") in {
        tuple(u["column_names"]) for u in insp.get_unique_constraints("annotation")
    }


def test_tombstone_pk():
    insp = _inspector()
    pk_cols = insp.get_pk_constraint("tombstone")["constrained_columns"]
    assert set(pk_cols) == {"call_id"}


def test_event_content_columns_separate_from_attrs():
    insp = _inspector()
    cols = {c["name"] for c in insp.get_columns("event")}
    # shape and content kept apart so DELETE finds text in one place
    assert {"attrs", "content_text", "content_kind"} <= cols
