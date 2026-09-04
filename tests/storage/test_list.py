"""storage.list_objects — S3 pagination (no network) and key parsing."""

from __future__ import annotations

from datetime import UTC, datetime

from voiceobs.storage import list_objects
from voiceobs.worker.reconcile import _parse_call_id


def test_list_objects_paginates(monkeypatch):
    class _Paginator:
        def paginate(self, Bucket, Prefix):
            yield {"Contents": [{"Key": "recordings/c1/audio.wav",
                                 "LastModified": datetime(2026, 8, 1, tzinfo=UTC)}]}
            yield {"Contents": [{"Key": "recordings/c2/audio.wav",
                                 "LastModified": datetime(2026, 8, 2, tzinfo=UTC)}]}

    class _Client:
        def get_paginator(self, name):
            return _Paginator()

    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _Client())
    got = list_objects("s3://bucket/recordings/")
    assert [u for u, _ in got] == [
        "s3://bucket/recordings/c1/audio.wav",
        "s3://bucket/recordings/c2/audio.wav",
    ]


def test_parse_call_id_from_key():
    # <prefix>/<call_id>/<file> — call_id is the directory before the filename
    assert _parse_call_id("s3://b/recordings/CALL123/audio.wav", "b", "recordings") == "CALL123"
    # empty prefix works too
    assert _parse_call_id("s3://b/CALL9/audio_caller.wav", "b", "") == "CALL9"
    # a bare file with no call_id directory yields nothing
    assert _parse_call_id("s3://b/recordings/loose.wav", "b", "recordings") is None
