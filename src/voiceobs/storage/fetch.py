"""Object store access. S3 only for now; other schemes raise."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse


def fetch_bytes(uri: str) -> bytes:
    if uri.startswith("s3://"):
        import boto3  # lazy — only the worker path needs it

        bucket, key = _parse_s3(uri)
        return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    raise NotImplementedError(f"unsupported storage scheme: {uri}")


def presign(uri: str, expires_s: int = 900) -> str:
    """Short-lived GET URL the browser streams directly — the API never proxies bytes."""
    if not uri.startswith("s3://"):
        raise NotImplementedError(f"unsupported storage scheme: {uri}")
    import boto3

    bucket, key = _parse_s3(uri)
    return boto3.client("s3").generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_s
    )


def list_objects(prefix: str) -> list[tuple[str, datetime]]:
    """(s3://uri, last_modified) for every object under an s3:// prefix."""
    if not prefix.startswith("s3://"):
        raise NotImplementedError(f"unsupported storage scheme: {prefix}")
    import boto3

    bucket, key_prefix = _parse_s3(prefix)
    client = boto3.client("s3")
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
