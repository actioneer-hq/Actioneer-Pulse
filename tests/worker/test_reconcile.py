"""reconcile — backfills audio for calls whose artifact POST never arrived."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from voiceobs.db.models import Call, Media, Tombstone
from voiceobs.worker.reconcile import reconcile

OLD = datetime(2026, 8, 1, tzinfo=UTC)  # well past any grace window
URI = "s3://bucket/voice/vastu-hfc/app/camp/recip/c1/audio.wav"


def _seed_call(db, *, spans_complete=True, status="awaiting_media") -> Call:
    call = Call(
        tenant_id="vastu-hfc", external_call_id="c1", source="livekit",
        environment="prod", status=status, spans_complete=spans_complete,
    )
    db.add(call)
    db.commit()
    return call


def _lister(monkeypatch, objects):
    monkeypatch.setattr("voiceobs.worker.reconcile.list_objects", lambda prefix: objects)


def test_backfills_missing_audio(db_sessionmaker, monkeypatch):
    _lister(monkeypatch, [(URI, OLD)])
    with db_sessionmaker() as db:
        call = _seed_call(db)
        assert reconcile(db, "s3://bucket/voice/") == 1
        db.commit()
        media = db.scalar(select(Media).where(Media.call_id == call.id, Media.kind == "audio"))
        assert media.uri == URI
        db.refresh(call)
        assert call.media_ready is True
        assert call.status == "ingested"  # spans_complete + media_ready


def test_skips_when_audio_already_registered(db_sessionmaker, monkeypatch):
    _lister(monkeypatch, [(URI, OLD)])
    with db_sessionmaker() as db:
        call = _seed_call(db)
        db.add(Media(call_id=call.id, tenant_id="vastu-hfc", kind="audio", uri=URI))
        db.commit()
        assert reconcile(db, "s3://bucket/voice/") == 0


def test_skips_tombstoned_call(db_sessionmaker, monkeypatch):
    _lister(monkeypatch, [(URI, OLD)])
    with db_sessionmaker() as db:
        _seed_call(db)
        db.add(Tombstone(tenant_id="vastu-hfc", call_id="c1"))
        db.commit()
        assert reconcile(db, "s3://bucket/voice/") == 0


def test_ignores_recent_objects_within_grace(db_sessionmaker, monkeypatch):
    fresh = datetime.now(UTC) - timedelta(seconds=5)
    _lister(monkeypatch, [(URI, fresh)])
    with db_sessionmaker() as db:
        _seed_call(db)
        assert reconcile(db, "s3://bucket/voice/", grace_s=600) == 0


def test_idempotent_on_rerun(db_sessionmaker, monkeypatch):
    _lister(monkeypatch, [(URI, OLD)])
    with db_sessionmaker() as db:
        _seed_call(db)
        assert reconcile(db, "s3://bucket/voice/") == 1
        db.commit()
        assert reconcile(db, "s3://bucket/voice/") == 0
