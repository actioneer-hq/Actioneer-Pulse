"""process_audio_only on mixed/mono audio: diarization splits speakers when configured."""

from __future__ import annotations

import io
import sys
import wave

import numpy as np
from sqlalchemy import select

from voiceobs.db.models import Call, Metric
from voiceobs.diarize.client import Diarization, Segment
from voiceobs.worker.process import ensure_audio_call, process_audio_only


def _mixed_wav() -> bytes:
    """A stereo WAV whose two channels are identical (a downmix) → detect_layout == 'mixed'."""
    sr, n = 8000, 8000 * 4
    t = np.arange(n) / sr
    tone = np.zeros(n)
    tone[int(0.3 * sr):int(3.5 * sr)] = 20000 * np.sin(2 * np.pi * 220 * t[int(0.3 * sr):int(3.5 * sr)])
    ch = tone.astype("<i2")
    inter = np.empty(n * 2, dtype="<i2")
    inter[0::2], inter[1::2] = ch, ch
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(inter.tobytes())
    return out.getvalue()


def _seed(db) -> Call:
    from voiceobs.db.models import Media

    call = ensure_audio_call(db, agent_id="ag1", external_call_id="mix-1")
    db.add(Media(call_id=call.id, kind="audio", uri="s3://b/mix-1.wav", sample_rate=8000))
    db.flush()
    return call


def test_mixed_with_diarization_is_diarized(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(sys.modules["voiceobs.worker.process"], "fetch_bytes",
                        lambda uri, creds=None: _mixed_wav())
    # stub the diarization call (bypass config + httpx): agent speaks first, then caller
    diar = Diarization(
        segments=[Segment(0.3, 1.6, "SPK0"), Segment(1.8, 3.4, "SPK1")],
        confidence=0.77,
    )
    monkeypatch.setattr(sys.modules["voiceobs.worker.process"], "_run_diarization",
                        lambda db, agent_id, wav: diar)

    with db_sessionmaker() as db:
        call = _seed(db)
        assert process_audio_only(db, call) == "ok"
        db.commit()
        assert call.analysis_mode == "diarized"
        assert call.audio_layout == "mixed"
        assert call.diarization_confidence == 0.77
        # agent side now available (from the diarized agent segment)
        agent = db.scalar(select(Metric).where(Metric.name == "talk_ratio_agent"))
        assert agent is not None and agent.available and agent.value_num is not None


def test_mixed_without_diarization_stays_audio_only(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(sys.modules["voiceobs.worker.process"], "fetch_bytes",
                        lambda uri, creds=None: _mixed_wav())
    monkeypatch.setattr(sys.modules["voiceobs.worker.process"], "_run_diarization",
                        lambda db, agent_id, wav: None)  # not configured

    with db_sessionmaker() as db:
        call = _seed(db)
        assert process_audio_only(db, call) == "ok"
        db.commit()
        assert call.analysis_mode == "audio-only"
        assert call.audio_layout == "mixed"
        assert call.diarization_confidence is None
        # agent side unavailable without separation
        agent = db.scalar(select(Metric).where(Metric.name == "talk_ratio_agent"))
        assert agent is not None and not agent.available
