"""Transcript ingestion — Tier 1 (derived from turns) and Tier 2 (BYO upload)."""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from tests.fixtures.vas_call import sample_call
from voiceobs.db.models import Call, Transcript
from voiceobs.worker.process import process


def _computed(client, db_sessionmaker) -> None:
    """A call with content on spans, run through the worker (derives a transcript)."""
    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        process(db, db.scalars(select(Call)).one())
        db.commit()


def test_tier1_derived_from_turns(client, db_sessionmaker):
    _computed(client, db_sessionmaker)
    d = client.get("/v1/calls/c1/transcript").json()
    assert d["source"] == "derived"
    lines = d["lines"]
    assert {ln["role"] for ln in lines} == {"caller", "agent"}
    assert any(ln["text"] == "haan ji" for ln in lines)  # caller transcript from the fixture


def test_tier2_byo_overrides_derived(client, db_sessionmaker):
    _computed(client, db_sessionmaker)
    r = client.post("/v1/calls/c1/transcript", json={"format": "text", "text": "MY TRANSCRIPT"})
    assert r.status_code == 200
    d = client.get("/v1/calls/c1/transcript").json()
    assert d["source"] == "byo"
    assert d["text"] == "MY TRANSCRIPT"


def test_tier2_reupload_replaces(client, db_sessionmaker):
    client.post("/v1/traces", json=sample_call())
    client.post("/v1/calls/c1/transcript", json={"text": "v1"})
    client.post("/v1/calls/c1/transcript", json={"text": "v2"})
    with db_sessionmaker() as db:
        assert db.scalar(select(func.count()).select_from(Transcript)) == 1
    assert client.get("/v1/calls/c1/transcript").json()["text"] == "v2"


def test_tier2_by_uri_is_fetched(client, monkeypatch):
    client.post("/v1/traces", json=sample_call())
    monkeypatch.setattr(
        sys.modules["voiceobs.transcript"], "fetch_bytes", lambda uri: b"FROM S3"
    )
    client.post("/v1/calls/c1/transcript", json={"uri": "s3://b/t.txt"})
    assert client.get("/v1/calls/c1/transcript").json()["text"] == "FROM S3"


def test_delete_cascades_transcript(client, db_sessionmaker, monkeypatch):
    monkeypatch.setenv("VOICEOBS_ALLOW_DELETE", "1")
    client.post("/v1/traces", json=sample_call())
    client.post("/v1/calls/c1/transcript", json={"text": "x"})
    client.delete("/v1/calls/c1", headers={"X-Voiceobs-Confirm": "c1"})
    with db_sessionmaker() as db:
        assert db.scalar(select(func.count()).select_from(Transcript)) == 0


def test_transcript_404_for_unknown_call(client):
    assert client.get("/v1/calls/nope/transcript").status_code == 404
