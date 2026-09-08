"""Backfill worker: discover audio in a store, create + analyse calls audio-only, track failures."""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from sqlalchemy import func, select

from tests.fixtures.synth import SynthCall
from voiceobs.db.models import Agent, AgentAudioConfig, BackfillJob, Call, Organization
from voiceobs.worker.backfill import run_job

OLD = datetime(2026, 8, 1, tzinfo=UTC)


def _seed_agent(db) -> None:
    db.add(Organization(id="org1", name="Org", slug="org1"))
    db.add(Agent(id="ag1", org_id="org1", name="Bot", slug="bot"))
    db.add(AgentAudioConfig(
        agent_id="ag1", enabled=True, provider="s3_compatible",
        descriptor={
            "bucket": "bucket", "list_prefix": "rec/",
            "key_regex": r"(?P<call_id>[^/]+)/[^/]+$", "id_group": "call_id",
            "file_map": {"audio.wav": "audio"},
        },
    ))


def _wav(call_id: str) -> bytes:
    return SynthCall(duration_s=5.0,
                     speech=[("caller", 0.5, 1.5, 0.8), ("agent", 2.0, 3.5, 0.8)]).build()


def test_run_job_backfills_audio_only(db_sessionmaker, monkeypatch):
    uris = [(f"s3://bucket/rec/{cid}/audio.wav", OLD) for cid in ("c1", "c2", "bad")]
    monkeypatch.setattr("voiceobs.storage.drivers.s3.S3Driver.list",
                        lambda self, descriptor, creds: uris)

    def fake_fetch(uri, creds=None):
        return b"corrupt" if "/bad/" in uri else _wav("x")

    monkeypatch.setattr(sys.modules["voiceobs.worker.process"], "fetch_bytes", fake_fetch)
    # clustering is best-effort and needs the analytics extra; make it a no-op here
    monkeypatch.setattr("voiceobs.clustering.service.recluster", lambda db: {})

    with db_sessionmaker() as db:
        _seed_agent(db)
        job = BackfillJob(org_id="org1", agent_id="ag1", source="audio",
                          options={}, status="queued", created_at=OLD)
        db.add(job)
        db.commit()

        run_job(db, job)

        assert job.status == "done"
        assert job.total == 3
        assert job.completed == 2
        assert job.failed == 1
        # two good calls analysed audio-only; the corrupt one marked failed with an error
        good = db.scalars(select(Call).where(Call.status == "ingested")).all()
        assert {c.external_call_id for c in good} == {"c1", "c2"}
        assert all(c.analysis_mode == "audio-only" for c in good)
        bad = db.scalar(select(Call).where(Call.external_call_id == "bad"))
        assert bad.status == "failed" and bad.analysis_error


def test_run_job_respects_limit(db_sessionmaker, monkeypatch):
    uris = [(f"s3://bucket/rec/c{i}/audio.wav", OLD) for i in range(5)]
    monkeypatch.setattr("voiceobs.storage.drivers.s3.S3Driver.list",
                        lambda self, descriptor, creds: uris)
    monkeypatch.setattr(sys.modules["voiceobs.worker.process"], "fetch_bytes",
                        lambda uri, creds=None: _wav("x"))
    monkeypatch.setattr("voiceobs.clustering.service.recluster", lambda db: {})

    with db_sessionmaker() as db:
        _seed_agent(db)
        job = BackfillJob(org_id="org1", agent_id="ag1", source="audio",
                          options={"limit": 2}, status="queued", created_at=OLD)
        db.add(job)
        db.commit()
        run_job(db, job)
        assert job.total == 2
        assert db.scalar(select(func.count()).select_from(Call)) == 2
