"""The audio path: registered WAV -> analyze_audio -> utterances/peaks/Layer-1."""

from __future__ import annotations

from sqlalchemy import func, select

from tests.fixtures.livekit_call import sample_call
from tests.fixtures.synth import SynthCall
from voiceobs.db.models import Call, Media, Metric, Utterance
from voiceobs.worker.process import process


def _synth_wav() -> bytes:
    return SynthCall(
        duration_s=6.0,
        speech=[("caller", 1.0, 2.0, 0.8), ("agent", 2.5, 4.0, 0.8)],
    ).build()


def _register_audio(client) -> None:
    client.post("/v1/traces", json=sample_call())
    client.post("/v1/calls/c1/artifacts", json={
        "kind": "audio", "uri": "s3://bucket/c1.wav", "sha256": "x",
        "channels": 2, "sample_rate": 8000,
        "channel_map": {0: "caller", 1: "agent"}, "t0_offset_s": 0.0,
    })


def test_audio_produces_utterances_peaks_and_layer1(client, db_sessionmaker, monkeypatch):
    import sys

    monkeypatch.setenv("VOICEOBS_AUDIO_ANALYSIS", "1")  # audio overlay is off by default
    monkeypatch.setattr(
        sys.modules["voiceobs.worker.process"], "fetch_bytes", lambda uri: _synth_wav()
    )
    _register_audio(client)

    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        assert process(db, call) in ("ok", "partial")
        db.commit()

        assert db.scalar(select(func.count()).select_from(Utterance)) > 0
        peaks = db.scalars(select(Media).where(Media.kind.like("peaks_%"))).all()
        assert {m.kind for m in peaks} == {"peaks_caller", "peaks_agent"}
        # a Layer-1 metric now exists (it wouldn't without audio)
        cov = db.scalar(select(Metric).where(Metric.name == "capture_coverage"))
        assert cov is not None and cov.value_num is not None


def test_reprocess_replaces_audio_rows(client, db_sessionmaker, monkeypatch):
    import sys

    monkeypatch.setenv("VOICEOBS_AUDIO_ANALYSIS", "1")
    monkeypatch.setattr(
        sys.modules["voiceobs.worker.process"], "fetch_bytes", lambda uri: _synth_wav()
    )
    _register_audio(client)
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        process(db, call)
        db.commit()
        first = db.scalar(select(func.count()).select_from(Utterance))
        process(db, call)
        db.commit()
        assert db.scalar(select(func.count()).select_from(Utterance)) == first


def test_no_audio_still_spans_only(client, db_sessionmaker):
    client.post("/v1/traces", json=sample_call())  # no artifact registered
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        process(db, call)
        db.commit()
        assert db.scalar(select(func.count()).select_from(Utterance)) == 0
