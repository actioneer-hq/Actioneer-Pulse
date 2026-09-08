"""Tier B: STT → Turns for audio-only calls, and the process_audio_only STT path."""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from tests.fixtures.synth import SynthCall
from voiceobs.core.model import Utterance
from voiceobs.db.models import AgentAudioConfig, Call, Media
from voiceobs.db.models import Turn as DBTurn
from voiceobs.groundtruth.stt import Word
from voiceobs.groundtruth.stt.client import Transcript
from voiceobs.worker import audio_stt
from voiceobs.worker.audio_stt import build_turns, transcribe_sides
from voiceobs.worker.process import ensure_audio_call, process_audio_only


def test_build_turns_pairs_caller_then_agent():
    utts = [
        Utterance(channel="caller", t_start=0.0, t_end=1.0),
        Utterance(channel="agent", t_start=1.2, t_end=2.5),
        Utterance(channel="caller", t_start=3.0, t_end=3.5),
    ]
    words = {
        "caller": [Word("hello", 0.1, 0.5), Word("there", 0.6, 0.9), Word("bye", 3.1, 3.4)],
        "agent": [Word("hi", 1.3, 1.6), Word("friend", 1.7, 2.2)],
    }
    turns = build_turns(utts, words)
    assert len(turns) == 2  # one caller→agent turn, one trailing caller-only turn
    assert turns[0].transcript == "hello there"
    assert turns[0].llm_spoken == "hi friend"
    assert turns[1].transcript == "bye" and turns[1].llm_spoken is None


def test_transcribe_sides_separated(monkeypatch):
    wav = SynthCall(duration_s=4.0,
                    speech=[("caller", 0.2, 1.0, 0.8), ("agent", 1.5, 2.5, 0.8)]).build()

    def fake_transcribe(stt, w, **k):
        # return distinct text per channel so we can tell them apart
        return Transcript(text="x", words=[Word("caller-side", 0.2, 1.0)])

    monkeypatch.setattr(audio_stt, "transcribe", fake_transcribe)
    from voiceobs.groundtruth.stt import STTConfig

    out = transcribe_sides(STTConfig("https://x", "m"), wav, "separated", None,
                           {0: "caller", 1: "agent"})
    assert set(out) == {"caller", "agent"}
    assert out["caller"] and out["agent"]


def _seed_stt_call(db) -> Call:
    db.add(AgentAudioConfig(agent_id="ag1", enabled=True, provider="s3_compatible",
                            stt_base_url="https://stt.example", stt_model="whisper-1"))
    call = ensure_audio_call(db, agent_id="ag1", external_call_id="stt-1")
    db.add(Media(call_id=call.id, kind="audio", uri="s3://b/stt-1.wav", sample_rate=8000))
    db.flush()
    return call


def test_process_audio_only_tier_b(db_sessionmaker, monkeypatch):
    wav = SynthCall(duration_s=6.0,
                    speech=[("caller", 0.5, 2.0, 0.8), ("agent", 2.5, 4.5, 0.8)]).build()
    monkeypatch.setattr(sys.modules["voiceobs.worker.process"], "fetch_bytes",
                        lambda uri, creds=None: wav)

    def fake_transcribe(stt, w, **k):
        return Transcript(text="hi", words=[Word("hello", 0.6, 1.9), Word("reply", 2.6, 4.4)])

    monkeypatch.setattr(audio_stt, "transcribe", fake_transcribe)
    judged = []
    monkeypatch.setattr("voiceobs.judge.judge_call", lambda db, call: judged.append(call.id))

    with db_sessionmaker() as db:
        call = _seed_stt_call(db)
        assert process_audio_only(db, call, use_stt=True) == "ok"
        db.commit()
        assert call.analysis_mode == "audio-only+stt"
        assert db.scalar(select(func.count()).select_from(DBTurn)) > 0
        assert judged == [call.id]  # the judge ran on the reconstructed transcript


def test_tier_a_when_stt_unconfigured(db_sessionmaker, monkeypatch):
    wav = SynthCall(duration_s=4.0, speech=[("caller", 0.5, 2.0, 0.8)]).build()
    monkeypatch.setattr(sys.modules["voiceobs.worker.process"], "fetch_bytes",
                        lambda uri, creds=None: wav)
    with db_sessionmaker() as db:
        # no AgentAudioConfig with STT → use_stt has nothing to use
        call = ensure_audio_call(db, agent_id="ag1", external_call_id="no-stt")
        db.add(Media(call_id=call.id, kind="audio", uri="s3://b/x.wav", sample_rate=8000))
        db.flush()
        assert process_audio_only(db, call, use_stt=True) == "ok"
        db.commit()
        assert call.analysis_mode == "audio-only"  # no +stt
        assert db.scalar(select(func.count()).select_from(DBTurn)) == 0
