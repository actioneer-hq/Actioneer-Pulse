"""reconcile — pull-path audio backfill, per-agent S3 scan matched by call_id in the key."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from voiceobs.db.models import Agent, AgentAudioConfig, Call, Media, Organization, Tombstone
from voiceobs.worker.reconcile import reconcile

OLD = datetime(2026, 8, 1, tzinfo=UTC)  # well past any grace window
URI = "s3://bucket/recordings/c1/audio.wav"


def _seed(db, *, enabled=True, spans_complete=True) -> Agent:
    db.add(Organization(id="org1", name="Org", slug="org1"))
    agent = Agent(id="ag1", org_id="org1", name="Bot", slug="bot")
    db.add(agent)
    db.add(AgentAudioConfig(
        agent_id="ag1", enabled=enabled, provider="s3_compatible",
        descriptor={
            "bucket": "bucket", "list_prefix": "recordings/",
            "key_regex": r"(?P<call_id>[^/]+)/[^/]+$", "id_group": "call_id",
            "file_map": {"audio.wav": "audio", "audio_caller.wav": "audio_caller",
                         "audio_agent.wav": "audio_agent"},
        },
    ))
    db.add(Call(agent_id="ag1", external_call_id="c1", source="livekit",
                environment="prod", status="awaiting_media", spans_complete=spans_complete))
    db.commit()
    return agent


def _lister(monkeypatch, objects):
    # stub the driver's list() so reconcile's resolve_storage → S3Driver().list returns these objects
    monkeypatch.setattr("voiceobs.storage.drivers.s3.S3Driver.list",
                        lambda self, descriptor, creds: objects)


def test_backfills_missing_audio(db_sessionmaker, monkeypatch):
    _lister(monkeypatch, [(URI, OLD)])
    with db_sessionmaker() as db:
        _seed(db)
        assert reconcile(db) == 1
        db.commit()
        call = db.scalar(select(Call).where(Call.external_call_id == "c1"))
        media = db.scalar(select(Media).where(Media.call_id == call.id, Media.kind == "audio"))
        assert media.uri == URI
        assert call.media_ready is True and call.status == "ingested"


def test_two_mono_tracks_both_register(db_sessionmaker, monkeypatch):
    caller = "s3://bucket/recordings/c1/audio_caller.wav"
    agent = "s3://bucket/recordings/c1/audio_agent.wav"
    _lister(monkeypatch, [(caller, OLD), (agent, OLD)])
    with db_sessionmaker() as db:
        _seed(db)
        assert reconcile(db) == 2
        db.commit()
        kinds = {m.kind for m in db.scalars(select(Media))}
        assert kinds == {"audio_caller", "audio_agent"}


def test_disabled_agent_is_skipped(db_sessionmaker, monkeypatch):
    _lister(monkeypatch, [(URI, OLD)])
    with db_sessionmaker() as db:
        _seed(db, enabled=False)
        assert reconcile(db) == 0


def test_skips_when_audio_already_registered(db_sessionmaker, monkeypatch):
    _lister(monkeypatch, [(URI, OLD)])
    with db_sessionmaker() as db:
        _seed(db)
        call = db.scalar(select(Call).where(Call.external_call_id == "c1"))
        db.add(Media(call_id=call.id, kind="audio", uri=URI))
        db.commit()
        assert reconcile(db) == 0


def test_skips_tombstoned_call(db_sessionmaker, monkeypatch):
    _lister(monkeypatch, [(URI, OLD)])
    with db_sessionmaker() as db:
        _seed(db)
        db.add(Tombstone(call_id="c1"))
        db.commit()
        assert reconcile(db) == 0


def test_ignores_recent_objects_within_grace(db_sessionmaker, monkeypatch):
    _lister(monkeypatch, [(URI, datetime.now(UTC) - timedelta(seconds=5))])
    with db_sessionmaker() as db:
        _seed(db)
        assert reconcile(db, grace_s=600) == 0


def test_idempotent_on_rerun(db_sessionmaker, monkeypatch):
    _lister(monkeypatch, [(URI, OLD)])
    with db_sessionmaker() as db:
        _seed(db)
        assert reconcile(db) == 1
        db.commit()
        assert reconcile(db) == 0
