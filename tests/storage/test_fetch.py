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


def test_dev_audio_dir_serves_from_local_disk(monkeypatch, tmp_path):
    # dev override: s3://bucket/key resolves to {DEV_AUDIO_DIR}/key on disk, no S3 call.
    (tmp_path / "call").mkdir()
    (tmp_path / "call" / "c1.wav").write_bytes(b"LOCALAUDIO")
    monkeypatch.setenv("VOICEOBS_DEV_AUDIO_DIR", str(tmp_path))

    import boto3
    monkeypatch.setattr(boto3, "client", lambda svc: pytest.fail("must not hit S3 in dev mode"))
    assert fetch_bytes("s3://any-bucket/call/c1.wav") == b"LOCALAUDIO"


def test_dev_audio_dir_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEOBS_DEV_AUDIO_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        fetch_bytes("s3://bucket/nope.wav")
