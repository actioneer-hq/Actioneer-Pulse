"""The audio-analysis toggle: OTLP-only by default, Layer 1 only when switched on."""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from tests.adapters.fixtures.vas_call import sample_call
from tests.fixtures.synth import SynthCall
from voiceobs.db.models import Call, Utterance
from voiceobs.worker.process import process


def _register_audio(client) -> None:
    client.post("/v1/traces", json=sample_call())
    client.post("/v1/calls/c1/artifacts", json={
        "kind": "audio", "uri": "s3://bucket/c1.wav", "sha256": "x",
        "channels": 2, "sample_rate": 8000,
        "channel_map": {0: "caller", 1: "agent"}, "t0_offset_s": 0.0,
    })


def _patch_fetch(monkeypatch) -> None:
    wav = SynthCall(duration_s=6.0,
                    speech=[("caller", 1.0, 2.0, 0.8), ("agent", 2.5, 4.0, 0.8)]).build()
    monkeypatch.setattr(
        sys.modules["voiceobs.worker.process"], "fetch_bytes", lambda uri: wav
    )


def test_default_is_otlp_only_even_with_a_wav(client, db_sessionmaker, monkeypatch):
    monkeypatch.delenv("VOICEOBS_AUDIO_ANALYSIS", raising=False)  # global default: off
    _patch_fetch(monkeypatch)
    _register_audio(client)

    with db_sessionmaker() as db:
        analysis_ran = process(db, db.scalars(select(Call)).one())
        db.commit()
        assert analysis_ran in ("ok", "partial")
        assert db.scalar(select(func.count()).select_from(Utterance)) == 0  # audio skipped


def test_toggle_on_runs_layer1(client, db_sessionmaker, monkeypatch):
    monkeypatch.delenv("VOICEOBS_AUDIO_ANALYSIS", raising=False)
    _patch_fetch(monkeypatch)
    _register_audio(client)
    client.post("/v1/settings", json={"audio_analysis_enabled": True},  # per-tenant on
                headers={"X-Voiceobs-Tenant": "vastu-hfc"})  # the call's tenant

    with db_sessionmaker() as db:
        process(db, db.scalars(select(Call)).one())
        db.commit()
        assert db.scalar(select(func.count()).select_from(Utterance)) > 0


def test_settings_roundtrip(client):
    assert client.get("/v1/settings").json()["audio_analysis_enabled"] is None
    client.post("/v1/settings", json={"audio_analysis_enabled": True,
                                      "audio_store_prefix": "s3://bucket/calls/"})
    got = client.get("/v1/settings").json()
    assert got["audio_analysis_enabled"] is True
    assert got["audio_store_prefix"] == "s3://bucket/calls/"


def test_trust_block_shows_audio_off(client, db_sessionmaker, monkeypatch):
    monkeypatch.delenv("VOICEOBS_AUDIO_ANALYSIS", raising=False)
    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        process(db, db.scalars(select(Call)).one())
        db.commit()
    assert client.get("/v1/calls/c1").json()["trust"]["audio_analysis"] is False
