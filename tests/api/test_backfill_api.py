"""Backfill API: preview, create (owner/admin only), status, cancel."""

from __future__ import annotations

from datetime import UTC, datetime

from voiceobs.db.models import Agent, AgentAudioConfig

OLD = datetime(2026, 8, 1, tzinfo=UTC)
_DESC = {
    "bucket": "bucket", "list_prefix": "rec/",
    "key_regex": r"(?P<call_id>[^/]+)/[^/]+$", "id_group": "call_id",
    "file_map": {"audio.wav": "audio"},
}


def _seed_storage(db_sessionmaker) -> None:
    with db_sessionmaker() as db:
        db.add(Agent(id="ag1", org_id="default", name="Bot", slug="bot"))
        db.add(AgentAudioConfig(agent_id="ag1", enabled=True,
                                provider="s3_compatible", descriptor=_DESC))
        db.commit()


def test_preview_counts_calls(authed_client, db_sessionmaker, monkeypatch):
    _seed_storage(db_sessionmaker)
    monkeypatch.setattr(
        "voiceobs.storage.drivers.s3.S3Driver.list",
        lambda self, descriptor, creds: [
            (f"s3://bucket/rec/{c}/audio.wav", OLD) for c in ("a", "b", "c")
        ],
    )
    r = authed_client.get("/v1/backfill/preview", params={"agent_id": "ag1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audio_calls"] == 3
    assert set(body["sample_call_ids"]) == {"a", "b", "c"}


def test_create_and_status(authed_client, db_sessionmaker):
    _seed_storage(db_sessionmaker)
    r = authed_client.post("/v1/backfill", json={"agent_id": "ag1", "source": "audio"})
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    assert r.json()["status"] == "queued"

    s = authed_client.get(f"/v1/backfill/{job_id}")
    assert s.status_code == 200
    assert s.json()["status"] == "queued"


def test_create_rejects_unconfigured_agent(authed_client):
    r = authed_client.post("/v1/backfill", json={"agent_id": "nope", "source": "audio"})
    assert r.status_code == 400


def test_cancel(authed_client, db_sessionmaker):
    _seed_storage(db_sessionmaker)
    job_id = authed_client.post("/v1/backfill", json={"agent_id": "ag1"}).json()["id"]
    r = authed_client.post(f"/v1/backfill/{job_id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_create_requires_admin(login_as, db_sessionmaker):
    _seed_storage(db_sessionmaker)
    viewer = login_as("default", role="viewer")
    r = viewer.post("/v1/backfill", json={"agent_id": "ag1"})
    assert r.status_code == 403
