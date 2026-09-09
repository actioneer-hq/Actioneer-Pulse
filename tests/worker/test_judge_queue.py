"""Judge queue: enqueue/decode, the judge worker handler, and enqueue-not-inline in analysis/backfill."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from tests.fixtures.livekit_call import sample_call
from tests.fixtures.synth import SynthCall
from voiceobs.bus import Record
from voiceobs.config import get_config
from voiceobs.db.models import Agent, AgentAudioConfig, BackfillJob, Call, Judgment, Organization
from voiceobs.judge.queue import decode_judge, enqueue_judge


def test_enqueue_routes_by_priority(bus):
    enqueue_judge(bus, "vastu-hfc", "c1", backfill=False)
    enqueue_judge(bus, "vastu-hfc", "c2", backfill=True)
    rt = bus.records(get_config().kafka_topic_judge)
    bf = bus.records(get_config().kafka_topic_judge_backfill)
    assert [decode_judge(r) for r in rt] == [("vastu-hfc", "c1")]
    assert [decode_judge(r) for r in bf] == [("vastu-hfc", "c2")]


def test_handle_judge_runs_judge(db_sessionmaker, monkeypatch):
    from voiceobs.worker import judge as jw

    judged: list[str] = []
    monkeypatch.setattr(jw, "judge_call", lambda db, call: judged.append(call.external_call_id))
    with db_sessionmaker() as db:
        db.add(Call(external_call_id="c9", source="x", environment="prod", status="ingested"))
        db.commit()
        rec = Record(topic="judge-requests", key="c9",
                     value=json.dumps({"org": "default", "call_id": "c9"}).encode())
        jw.handle_judge(db, rec)
        assert judged == ["c9"]


def test_handle_judge_missing_call_is_noop(db_sessionmaker, monkeypatch):
    from voiceobs.worker import judge as jw

    monkeypatch.setattr(jw, "judge_call", lambda db, call: (_ for _ in ()).throw(AssertionError))
    with db_sessionmaker() as db:
        rec = Record(topic="judge-requests", key="ghost",
                     value=json.dumps({"org": "default", "call_id": "ghost"}).encode())
        jw.handle_judge(db, rec)  # must not raise, must not call judge_call


def test_realtime_flush_enqueues_not_inline(client, db_sessionmaker, bus, drain, monkeypatch):
    """A grace-swept call is queued for judging (realtime topic), not judged inline."""
    from voiceobs.worker.run import flush_due

    monkeypatch.setenv("VOICEOBS_WORKER_GRACE_S", "0")  # everything is past the grace cutoff
    client.post("/v1/traces", json=sample_call())
    drain()  # assembles the call (spans_complete, no media)

    with db_sessionmaker() as db:
        call = db.scalar(select(Call).where(Call.external_call_id == "c1"))
        call.last_activity_at = datetime.now(UTC) - timedelta(hours=1)
        call.media_ready = False
        db.commit()
        flush_due(db)

    # judging was ENQUEUED, not run inline
    assert [decode_judge(r) for r in bus.records(get_config().kafka_topic_judge)] == [("default", "c1")]
    with db_sessionmaker() as db:
        assert db.scalar(select(func.count()).select_from(Judgment)) == 0


def test_backfill_stt_enqueues_backfill_topic(db_sessionmaker, bus, monkeypatch):
    from voiceobs.groundtruth.stt import Word
    from voiceobs.groundtruth.stt.client import Transcript
    from voiceobs.worker import audio_stt
    from voiceobs.worker.backfill import run_job

    monkeypatch.setattr("voiceobs.storage.drivers.s3.S3Driver.list",
                        lambda self, d, c: [("s3://bucket/rec/c1/audio.wav", datetime(2026, 8, 1, tzinfo=UTC))])
    monkeypatch.setattr(sys.modules["voiceobs.worker.process"], "fetch_bytes",
                        lambda uri, creds=None: SynthCall(
                            duration_s=5.0,
                            speech=[("caller", 0.5, 1.5, 0.8), ("agent", 2.0, 3.5, 0.8)]).build())
    monkeypatch.setattr(audio_stt, "transcribe",
                        lambda stt, w, **k: Transcript(text="hi", words=[Word("hi", 0.6, 1.4)]))
    monkeypatch.setattr("voiceobs.clustering.service.recluster", lambda db: {})

    with db_sessionmaker() as db:
        db.add(Organization(id="org1", name="Org", slug="org1"))
        db.add(Agent(id="ag1", org_id="org1", name="Bot", slug="bot"))
        db.add(AgentAudioConfig(agent_id="ag1", enabled=True, provider="s3_compatible",
                                stt_base_url="https://stt", stt_model="whisper-1",
                                descriptor={"bucket": "bucket", "list_prefix": "rec/",
                                            "key_regex": r"(?P<call_id>[^/]+)/[^/]+$",
                                            "id_group": "call_id", "file_map": {"audio.wav": "audio"}}))
        job = BackfillJob(org_id="org1", agent_id="ag1", source="audio",
                          options={"stt": True}, status="queued",
                          created_at=datetime(2026, 8, 1, tzinfo=UTC))
        db.add(job)
        db.commit()
        run_job(db, job)

    # the Tier-B call was queued to the BACKFILL judge topic (not judged inline, not realtime topic)
    bf = [decode_judge(r) for r in bus.records(get_config().kafka_topic_judge_backfill)]
    assert bf == [("org1", "c1")]
