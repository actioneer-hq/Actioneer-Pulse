"""BYO STT client + per-agent config resolve. No real network."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from voiceobs.auth.crypto import encrypt
from voiceobs.db import Base
from voiceobs.db.models import Agent, AgentAudioConfig, Organization
from voiceobs.groundtruth.stt import STTConfig, resolve_stt, transcribe


def _db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_transcribe_none_config_and_empty_wav():
    assert transcribe(None, b"data") is None
    assert transcribe(STTConfig("https://x/v1", "whisper-1"), b"") is None


def test_transcribe_never_raises_on_network_failure(monkeypatch):
    import httpx
    def boom(*a, **k):
        raise httpx.ConnectError("nope")
    monkeypatch.setattr(httpx, "post", boom)
    # a real config + bytes, but the endpoint is unreachable → None, not an exception
    assert transcribe(STTConfig("https://unreachable/v1", "whisper-1", "sk"), b"RIFFwav") is None


def test_transcribe_parses_words(monkeypatch):
    import httpx

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"text": "haan ji", "words": [
                {"word": "haan", "start": 0.1, "end": 0.4},
                {"word": "ji", "start": 0.4, "end": 0.6}]}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    t = transcribe(STTConfig("https://x/v1", "whisper-1", "sk"), b"RIFFwav")
    assert t.text == "haan ji"
    assert [w.text for w in t.words] == ["haan", "ji"]
    assert t.words[0].start == 0.1


def test_resolve_stt_decrypts_key(monkeypatch):
    monkeypatch.setenv("VOICEOBS_SECRET_KEY", "test-secret")
    db = _db()
    db.add(Organization(id="o1", name="O", slug="o1"))
    db.add(Agent(id="ag1", org_id="o1", name="A", slug="a"))
    db.add(AgentAudioConfig(agent_id="ag1", enabled=True, stt_base_url="https://x/v1",
                            stt_model="whisper-1", stt_key_ciphertext=encrypt("sk-secret")))
    db.commit()
    cfg = resolve_stt(db, "ag1")
    assert cfg.base_url == "https://x/v1" and cfg.model == "whisper-1"
    assert cfg.api_key == "sk-secret"  # decrypted


def test_resolve_stt_none_when_unconfigured():
    db = _db()
    db.add(Organization(id="o1", name="O", slug="o1"))
    db.add(Agent(id="ag2", org_id="o1", name="A", slug="a2"))
    db.add(AgentAudioConfig(agent_id="ag2", enabled=True))  # no STT fields
    db.commit()
    assert resolve_stt(db, "ag2") is None
    assert resolve_stt(db, None) is None
