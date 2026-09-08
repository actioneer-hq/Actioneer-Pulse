"""OTLP-from-blob backfill: decode stored OTLP files → full-fidelity analysis."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime

from sqlalchemy import func, select

from tests.fixtures.livekit_call import sample_call
from voiceobs.db.models import Agent, AgentAudioConfig, BackfillJob, Call, Organization
from voiceobs.frameworks.otlp import decode_otlp
from voiceobs.worker.backfill import run_job

OLD = datetime(2026, 8, 1, tzinfo=UTC)
_DESC = {
    "bucket": "bucket", "list_prefix": "otlp/",
    "key_regex": r"(?P<call_id>[^/]+)/[^/]+$", "id_group": "call_id",
    "file_map": {"trace.json": "otlp"},
}


def test_decode_otlp_json_and_gzip_json():
    payload = sample_call()
    raw = json.dumps(payload).encode()
    assert decode_otlp(raw, filename="trace.json")["resourceSpans"]
    assert decode_otlp(gzip.compress(raw), filename="trace.json")["resourceSpans"]


def _seed_agent(db) -> None:
    db.add(Organization(id="org1", name="Org", slug="org1"))
    db.add(Agent(id="ag1", org_id="org1", name="Bot", slug="bot"))
    db.add(AgentAudioConfig(agent_id="ag1", enabled=True, provider="s3_compatible", descriptor=_DESC))


def test_run_job_otlp_source_creates_full_call(db_sessionmaker, monkeypatch):
    monkeypatch.setattr("voiceobs.storage.drivers.s3.S3Driver.list",
                        lambda self, descriptor, creds: [("s3://bucket/otlp/c1/trace.json", OLD)])
    # _process_otlp_call does `from voiceobs.storage import fetch_bytes` at call time
    monkeypatch.setattr("voiceobs.storage.fetch_bytes",
                        lambda uri, creds=None: json.dumps(sample_call()).encode())
    monkeypatch.setattr("voiceobs.judge.judge_call", lambda db, call: None)
    monkeypatch.setattr("voiceobs.clustering.service.recluster", lambda db: {})

    with db_sessionmaker() as db:
        _seed_agent(db)
        job = BackfillJob(org_id="org1", agent_id="ag1", source="otlp",
                          options={}, status="queued", created_at=OLD)
        db.add(job)
        db.commit()
        run_job(db, job)

        assert job.status == "done"
        assert job.total == 1 and job.completed == 1 and job.failed == 0
        call = db.scalar(select(Call).where(Call.external_call_id == "c1"))
        assert call is not None
        assert call.analysis_mode == "full"  # OTLP path = full fidelity
        # spans were analysed into events/turns (the real adapter ran)
        assert db.scalar(select(func.count()).select_from(Call)) == 1
        assert call.metric_version is not None
