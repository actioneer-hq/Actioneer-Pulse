"""S3 driver listing (no network) + descriptor key-regex extraction."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from voiceobs.storage.drivers.s3 import S3Driver


def test_s3_driver_list_paginates(monkeypatch):
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
    got = S3Driver().list({"bucket": "bucket", "list_prefix": "recordings/"}, {})
    assert [u for u, _ in got] == [
        "s3://bucket/recordings/c1/audio.wav",
        "s3://bucket/recordings/c2/audio.wav",
    ]


def test_default_key_regex_extracts_call_id():
    # The default convention descriptor: call_id is the directory before the filename.
    rx = re.compile(r"(?P<call_id>[^/]+)/[^/]+$")
    assert rx.search("recordings/CALL123/audio.wav").group("call_id") == "CALL123"
    assert rx.search("CALL9/audio_caller.wav").group("call_id") == "CALL9"
    assert rx.search("loose.wav") is None  # a bare file (no dir) yields no call_id
