"""The storage-polling ingest sidecar: sweep a store, ingest settled+new calls via the manifest
runtime, respect the settle-grace window, and advance the per-agent watermark."""

from __future__ import annotations

import json as _json
from datetime import UTC, datetime, timedelta

from voiceobs.storage.config import ResolvedStorage

MANIFEST = {
    "schema": "pulse.integration",
    "version": 1,
    "ingest_method": "storage_polling",
    "integration": {"framework": "custom", "language": "python", "use_case": "support"},
    "connections": [],
    "artifacts": [
        {
            "id": "events",
            "connection": "store",
            "selector": {"object_path_regex": r"^calls/([^/]+)/events\.json$"},
            "correlation": {"call_id": {"from": "path_capture", "group": 1}},
            "decoder": {"type": "json"},
            "emits": [
                {"target": "trace", "mapper": "events-trace"},
                {"target": "call", "mapper": "events-call"},
            ],
        },
    ],
    "mappers": {
        "events-trace": {
            "language": "jsonata", "input": "json", "output": "trace", "cardinality": "one",
            "expression": (
                '{"call_id": _pulse.call_id, "spans": [{"span_id": _pulse.call_id & "-p",'
                ' "parent_span_id": null, "name": "pipeline", "stage": "call",'
                ' "sequence": 0, "attrs": {}, "content": {},'
                ' "events": [$map(data.events, function($e) { {"name": $e.kind,'
                ' "t": $e.t, "attrs": {}, "content": {"detail": $e.detail}} })]}]}'
            ),
        },
        "events-call": {
            "language": "jsonata", "input": "json", "output": "call", "cardinality": "one",
            "expression": '{"call_id": _pulse.call_id, "engine": data.engine}',
        },
    },
    "expected_capabilities": {},
}

EVENTS = {
    "engine": "cascade",
    "events": [
        {"t": 0.42, "kind": "stt.final", "detail": "hello"},
        {"t": 2.10, "kind": "tts.first_audio", "detail": "turn 1"},
    ],
}


def _agent_and_token(client, login_as) -> tuple[str, str]:
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Files Bot"}).json()["id"]
    token = client.post(f"/v1/agents/{aid}/ingest-tokens", json={"name": "w"}).json()["token"]
    return aid, token


def _fake_storage(objects: dict[str, datetime]):
    """objects: {uri: mtime}. Returns a ResolvedStorage whose driver lists them."""
    class FakeDriver:
        scheme = "s3"

        def list(self, descriptor, creds):
            return [(uri, mt) for uri, mt in objects.items()]

    return ResolvedStorage("s3_compatible", {"bucket": "b"}, {}, FakeDriver())


def _wire(monkeypatch, blobs: dict[str, bytes], st: ResolvedStorage) -> None:
    monkeypatch.setattr("voiceobs.worker.poller.resolve_storage", lambda db, aid: st)
    monkeypatch.setattr("voiceobs.integration.runtime.fetch_bytes",
                        lambda uri, creds=None: blobs[uri])


def test_poll_ingests_settled_call(client, login_as, db_sessionmaker, monkeypatch):
    from voiceobs.worker import poller

    _aid, token = _agent_and_token(client, login_as)
    client.put("/v1/ingest/integration-manifest", json=MANIFEST,
               headers={"Authorization": f"Bearer {token}"})

    settled = datetime.now(UTC) - timedelta(hours=1)  # older than the 600s grace
    uri = "s3://b/calls/c-1/events.json"
    st = _fake_storage({uri: settled})
    _wire(monkeypatch, {uri: _json.dumps(EVENTS).encode()}, st)

    with db_sessionmaker() as db:
        assert poller.poll(db) == 1

    detail = client.get("/v1/calls/c-1").json()
    assert detail["call"]["engine"] == "cascade"
    assert detail["turns"], "expected derived turns"
    assert "turns_derived_from_events" in detail["trust"]["reasons"]


def test_settle_grace_excludes_recent_objects(client, login_as, db_sessionmaker, monkeypatch):
    from voiceobs.worker import poller

    _aid, token = _agent_and_token(client, login_as)
    client.put("/v1/ingest/integration-manifest", json=MANIFEST,
               headers={"Authorization": f"Bearer {token}"})

    fresh = datetime.now(UTC)  # inside the grace window → still being written
    uri = "s3://b/calls/c-2/events.json"
    st = _fake_storage({uri: fresh})
    _wire(monkeypatch, {uri: _json.dumps(EVENTS).encode()}, st)

    with db_sessionmaker() as db:
        assert poller.poll(db) == 0  # not settled yet
    assert client.get("/v1/calls/c-2").status_code == 404


def test_watermark_skips_seen_and_advances(client, login_as, db_sessionmaker, monkeypatch):
    from voiceobs.db.models import AgentIntegrationManifest
    from voiceobs.worker import poller

    _aid, token = _agent_and_token(client, login_as)
    client.put("/v1/ingest/integration-manifest", json=MANIFEST,
               headers={"Authorization": f"Bearer {token}"})

    settled = datetime.now(UTC) - timedelta(hours=1)
    uri = "s3://b/calls/c-3/events.json"
    st = _fake_storage({uri: settled})
    _wire(monkeypatch, {uri: _json.dumps(EVENTS).encode()}, st)

    with db_sessionmaker() as db:
        assert poller.poll(db) == 1  # first sweep ingests
        row = db.scalar(select_manifest(AgentIntegrationManifest, _aid))
        assert row.last_polled_modified is not None
        # second sweep: same object, mtime <= watermark → skipped
        assert poller.poll(db) == 0


def test_late_artifact_reprocesses_call(client, login_as, db_sessionmaker, monkeypatch):
    from voiceobs.worker import poller

    _aid, token = _agent_and_token(client, login_as)
    client.put("/v1/ingest/integration-manifest", json=MANIFEST,
               headers={"Authorization": f"Bearer {token}"})

    t1 = datetime.now(UTC) - timedelta(hours=2)
    uri = "s3://b/calls/c-4/events.json"
    st1 = _fake_storage({uri: t1})
    _wire(monkeypatch, {uri: _json.dumps(EVENTS).encode()}, st1)
    with db_sessionmaker() as db:
        assert poller.poll(db) == 1

    # the same call's artifact is rewritten with a newer mtime → max mtime advances → reprocessed
    t2 = datetime.now(UTC) - timedelta(minutes=30)
    st2 = _fake_storage({uri: t2})
    _wire(monkeypatch, {uri: _json.dumps(EVENTS).encode()}, st2)
    with db_sessionmaker() as db:
        assert poller.poll(db) == 1


def select_manifest(model, agent_id):
    from sqlalchemy import select
    return select(model).where(model.agent_id == agent_id)
