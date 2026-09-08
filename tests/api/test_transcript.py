"""Transcript ingestion — Tier 1 (derived from turns) and Tier 2 (BYO upload)."""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from tests.fixtures.livekit_call import sample_call
from voiceobs.db.models import Call, Transcript
from voiceobs.worker.process import process


def _computed(client, db_sessionmaker, drain) -> None:
    """A call with content on spans, run through the worker (derives a transcript)."""
    client.post("/v1/traces", json=sample_call())
    drain()
    with db_sessionmaker() as db:
        process(db, db.scalars(select(Call)).one())
        db.commit()


def test_tier1_derived_from_turns(client, login_as, db_sessionmaker, drain):
    _computed(client, db_sessionmaker, drain)
    login_as("vastu-hfc")
    d = client.get("/v1/calls/c1/transcript").json()
    assert d["source"] == "derived"
    lines = d["lines"]
    assert {ln["role"] for ln in lines} == {"caller", "agent"}
    assert any(ln["text"] == "haan ji" for ln in lines)  # caller transcript from the fixture


def test_tier2_byo_overrides_derived(client, login_as, db_sessionmaker, drain):
    _computed(client, db_sessionmaker, drain)
    r = client.post("/v1/calls/c1/transcript", json={"format": "text", "text": "MY TRANSCRIPT"})
    assert r.status_code == 200
    login_as("vastu-hfc")
    d = client.get("/v1/calls/c1/transcript").json()
    assert d["source"] == "byo"
    assert d["text"] == "MY TRANSCRIPT"


def test_tier2_reupload_replaces(client, login_as, db_sessionmaker, drain):
    client.post("/v1/traces", json=sample_call())
    drain()
    client.post("/v1/calls/c1/transcript", json={"text": "v1"})
    client.post("/v1/calls/c1/transcript", json={"text": "v2"})
    with db_sessionmaker() as db:
        assert db.scalar(select(func.count()).select_from(Transcript)) == 1
    login_as("vastu-hfc")
    assert client.get("/v1/calls/c1/transcript").json()["text"] == "v2"


def test_tier2_by_uri_is_fetched(client, login_as, monkeypatch, drain):
    client.post("/v1/traces", json=sample_call())
    drain()
    monkeypatch.setattr(
        sys.modules["voiceobs.transcript"], "fetch_bytes", lambda uri: b"FROM S3"
    )
    client.post("/v1/calls/c1/transcript", json={"uri": "s3://b/t.txt"})
    login_as("vastu-hfc")
    assert client.get("/v1/calls/c1/transcript").json()["text"] == "FROM S3"


def test_delete_cascades_transcript(client, db_sessionmaker, monkeypatch, drain):
    monkeypatch.setenv("VOICEOBS_ALLOW_DELETE", "1")
    client.post("/v1/traces", json=sample_call())
    drain()
    client.post("/v1/calls/c1/transcript", json={"text": "x"})
    client.delete("/v1/calls/c1", headers={"X-Voiceobs-Confirm": "c1"})
    with db_sessionmaker() as db:
        assert db.scalar(select(func.count()).select_from(Transcript)) == 0


def test_transcript_404_for_unknown_call(client, login_as):
    login_as("default")
    assert client.get("/v1/calls/nope/transcript").status_code == 404
