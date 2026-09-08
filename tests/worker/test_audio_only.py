"""Audio-only analysis: no spans, agent side from VAD, provenance + failure handling."""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from tests.fixtures.synth import SynthCall
from voiceobs.db.models import Call, Event, Media, Metric, Utterance
from voiceobs.db.models import Turn as DBTurn
from voiceobs.worker.process import ensure_audio_call, process_audio_only


def _separated_wav() -> bytes:
    return SynthCall(
        duration_s=6.0,
        speech=[("caller", 0.5, 2.0, 0.8), ("agent", 2.5, 4.5, 0.8)],
    ).build()


def _seed_audio_call(db, wav_kind="audio") -> Call:
    call = ensure_audio_call(db, agent_id=None, external_call_id="bf-1")
    db.add(Media(call_id=call.id, kind=wav_kind, uri="s3://b/bf-1.wav", sample_rate=8000))
    db.flush()
    return call


def test_audio_only_produces_metrics_and_provenance(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(
        sys.modules["voiceobs.worker.process"], "fetch_bytes",
        lambda uri, creds=None: _separated_wav(),
    )
    with db_sessionmaker() as db:
        call = _seed_audio_call(db)
        assert process_audio_only(db, call) == "ok"
        db.commit()

        assert call.analysis_mode == "audio-only"
        assert call.audio_layout == "separated"
        assert call.status == "ingested"
        assert call.analysis_error is None
        # audio metrics landed; agent side present because it came from the agent channel VAD
        assert db.scalar(select(func.count()).select_from(Utterance)) > 0
        agent = db.scalar(select(Metric).where(Metric.name == "talk_ratio_agent"))
        assert agent is not None and agent.available and agent.value_num is not None
        # no spans → no turns, no events
        assert db.scalar(select(func.count()).select_from(DBTurn)) == 0
        assert db.scalar(select(func.count()).select_from(Event)) == 0
        # peaks/energy blobs written for both channels
        assert {m.kind for m in db.scalars(select(Media).where(Media.kind.like("peaks_%")))} == {
            "peaks_caller", "peaks_agent"
        }


def test_audio_only_no_audio_fails_with_reason(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(
        sys.modules["voiceobs.worker.process"], "fetch_bytes",
        lambda uri, creds=None: b"",
    )
    with db_sessionmaker() as db:
        # a Call with no Media at all
        call = ensure_audio_call(db, agent_id=None, external_call_id="bf-empty")
        assert process_audio_only(db, call) == "failed"
        db.commit()
        assert call.status == "failed"
        assert call.analysis_error and "no audio" in call.analysis_error


def test_audio_only_decode_error_fails_gracefully(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(
        sys.modules["voiceobs.worker.process"], "fetch_bytes",
        lambda uri, creds=None: b"not-a-wav-file",
    )
    with db_sessionmaker() as db:
        call = _seed_audio_call(db)
        assert process_audio_only(db, call) == "failed"
        db.commit()
        assert call.status == "failed"
        assert call.analysis_error  # carries the exception summary for the sidebar


def test_ensure_audio_call_is_idempotent(db_sessionmaker):
    with db_sessionmaker() as db:
        a = ensure_audio_call(db, agent_id="ag1", external_call_id="dup")
        b = ensure_audio_call(db, agent_id="ag1", external_call_id="dup")
        db.commit()
        assert a.id == b.id
        assert db.scalar(select(func.count()).select_from(Call)) == 1
