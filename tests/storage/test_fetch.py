"""Storage fetcher — S3 parsing/fetch (no network) and unsupported schemes."""

from __future__ import annotations

import io

import pytest

from voiceobs.storage import fetch_bytes
from voiceobs.storage.fetch import _parse_s3


def test_parse_s3():
    assert _parse_s3("s3://my-bucket/a/b/c.wav") == ("my-bucket", "a/b/c.wav")


def test_fetch_s3_reads_body(monkeypatch):
    class _Client:
        def get_object(self, Bucket, Key):
            assert (Bucket, Key) == ("bucket", "k.wav")
            return {"Body": io.BytesIO(b"AUDIO")}

    import boto3

    monkeypatch.setattr(boto3, "client", lambda svc: _Client())
    assert fetch_bytes("s3://bucket/k.wav") == b"AUDIO"


def test_unsupported_scheme_raises():
    with pytest.raises(NotImplementedError):
        fetch_bytes("gs://bucket/x.wav")
