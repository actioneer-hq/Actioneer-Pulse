"""S3-compatible driver (boto3 + SigV4). Covers AWS S3, MinIO, Cloudflare R2, Ceph, Backblaze B2,
DigitalOcean Spaces, Wasabi, Yandex, Alibaba OSS, and GCS via interop HMAC keys — anything speaking
the S3 API. A non-AWS `endpoint_url` switches to path-style addressing (MinIO/Ceph need it).

Creds dict: access_key_id, secret_access_key, region, endpoint_url (all optional → boto3's default
credential chain). Dev override: VOICEOBS_DEV_AUDIO_DIR serves `s3://…/key` from `{dir}/key`."""

from __future__ import annotations

import os
from datetime import datetime
from urllib.parse import urlparse

from voiceobs.config import get_config


def _client(creds: dict | None):
    import boto3  # lazy — only worker/presign paths need it
    from botocore.config import Config

    if not creds:
        return boto3.client("s3")
    endpoint = creds.get("endpoint_url") or None
    cfg = Config(s3={"addressing_style": "path"}) if endpoint else None  # MinIO/Ceph need path-style
    return boto3.client(
        "s3",
        aws_access_key_id=creds.get("access_key_id"),
        aws_secret_access_key=creds.get("secret_access_key"),
        region_name=creds.get("region"),
        endpoint_url=endpoint,
        config=cfg,
    )


def _parse(uri: str) -> tuple[str, str]:
    p = urlparse(uri)
    return p.netloc, p.path.lstrip("/")


class S3Driver:
    scheme = "s3"

    def list(self, descriptor: dict, creds: dict) -> list[tuple[str, datetime]]:
        bucket = descriptor["bucket"]
        prefix = (descriptor.get("list_prefix") or "").lstrip("/")
        client = _client(creds)
        out: list[tuple[str, datetime]] = []
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                out.append((f"s3://{bucket}/{obj['Key']}", obj["LastModified"]))
        return out

    def fetch_bytes(self, uri: str, creds: dict | None) -> bytes:
        bucket, key = _parse(uri)
        dev_dir = get_config().dev_audio_dir
        if dev_dir:  # dev override: serve from local disk keyed by the S3 key
            path = os.path.join(dev_dir, key)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()
            raise FileNotFoundError(f"dev audio not found: {path} (for {uri})")
        return _client(creds).get_object(Bucket=bucket, Key=key)["Body"].read()

    def presign(self, uri: str, creds: dict | None, expires_s: int = 900) -> str:
        bucket, key = _parse(uri)
        return _client(creds).generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_s
        )
