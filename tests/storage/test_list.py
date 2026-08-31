"""storage.list_objects — S3 pagination (no network) and key parsing."""

from __future__ import annotations

from datetime import UTC, datetime

from voiceobs.storage import list_objects
from voiceobs.worker.reconcile import _parse_key


def test_list_objects_paginates(monkeypatch):
    class _Paginator:
        def paginate(self, Bucket, Prefix):
            yield {"Contents": [{"Key": "voice/t/a/c/r/c1/audio.wav",
                                 "LastModified": datetime(2026, 8, 1, tzinfo=UTC)}]}
            yield {"Contents": [{"Key": "voice/t/a/c/r/c2/audio.wav",
                                 "LastModified": datetime(2026, 8, 2, tzinfo=UTC)}]}

    class _Client:
        def get_paginator(self, name):
            return _Paginator()

    import boto3

    monkeypatch.setattr(boto3, "client", lambda svc: _Client())
    got = list_objects("s3://bucket/voice/")
    assert [u for u, _ in got] == [
        "s3://bucket/voice/t/a/c/r/c1/audio.wav",
        "s3://bucket/voice/t/a/c/r/c2/audio.wav",
    ]


def test_parse_key_extracts_tenant_and_call_id():
    assert _parse_key("s3://b/voice/vastu-hfc/app/camp/recip/CALL123/audio.wav") == (
        "vastu-hfc", "CALL123",
    )
    assert _parse_key("s3://b/legacy/no-voice-prefix/x.wav") is None
