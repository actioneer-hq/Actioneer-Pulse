"""Object store access. S3 only; other schemes raise.

Credentials: pass an `S3Creds` to use a specific bucket's access key/secret (per-agent audio
config); omit it to fall back to boto3's default credential chain (env / IAM role).

Dev: if `VOICEOBS_DEV_AUDIO_DIR` is set, `fetch_bytes` resolves an ``s3://bucket/key`` from
``{dir}/key`` on local disk instead of calling S3 — so playback/ingest work without a real
bucket. The stored URIs stay real ``s3://`` (identical to prod); only the fetch is redirected."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from voiceobs.settings import get_settings


@dataclass(frozen=True)
class S3Creds:
    access_key_id: str
    secret_access_key: str
    region: str | None = None
    endpoint_url: str | None = None


def _client(creds: S3Creds | None):
    import boto3  # lazy — only the worker/presign paths need it

    if creds is None:
        return boto3.client("s3")
    return boto3.client(
        "s3",
        aws_access_key_id=creds.access_key_id,
        aws_secret_access_key=creds.secret_access_key,
        region_name=creds.region,
        endpoint_url=creds.endpoint_url,
    )


def fetch_bytes(uri: str, creds: S3Creds | None = None) -> bytes:
    if uri.startswith("s3://"):
        bucket, key = _parse_s3(uri)
        dev_dir = get_settings().dev_audio_dir
        if dev_dir:  # dev override: serve the object from local disk keyed by the S3 key
            path = os.path.join(dev_dir, key)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()
            raise FileNotFoundError(f"dev audio not found: {path} (for {uri})")
        return _client(creds).get_object(Bucket=bucket, Key=key)["Body"].read()
    raise NotImplementedError(f"unsupported storage scheme: {uri}")


def presign(uri: str, expires_s: int = 900, creds: S3Creds | None = None) -> str:
    """Short-lived GET URL the browser streams directly — the API never proxies bytes."""
    if not uri.startswith("s3://"):
        raise NotImplementedError(f"unsupported storage scheme: {uri}")
    bucket, key = _parse_s3(uri)
    return _client(creds).generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_s
    )


def list_objects(prefix: str, creds: S3Creds | None = None) -> list[tuple[str, datetime]]:
    """(s3://uri, last_modified) for every object under an s3:// prefix."""
    if not prefix.startswith("s3://"):
        raise NotImplementedError(f"unsupported storage scheme: {prefix}")
    bucket, key_prefix = _parse_s3(prefix)
    client = _client(creds)
    out: list[tuple[str, datetime]] = []
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=key_prefix
    ):
        for obj in page.get("Contents", []):
            out.append((f"s3://{bucket}/{obj['Key']}", obj["LastModified"]))
    return out


def _parse_s3(uri: str) -> tuple[str, str]:
    p = urlparse(uri)
    return p.netloc, p.path.lstrip("/")
