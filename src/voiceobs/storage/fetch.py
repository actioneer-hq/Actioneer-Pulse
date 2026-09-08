"""Uri-based fetch/presign — routes an object uri to the driver for its scheme (`s3://`, `azblob://`).
Used by playback/audio-analysis/transcript. Reconcile enumerates via `driver.list(descriptor)`
instead (see storage/config.resolve_storage). `creds` is a plain dict (or None → default chain)."""

from __future__ import annotations

from voiceobs.storage.drivers import driver_for_uri


def fetch_bytes(uri: str, creds: dict | None = None) -> bytes:
    return driver_for_uri(uri).fetch_bytes(uri, creds)


def presign(uri: str, creds: dict | None = None, expires_s: int = 900) -> str:
    """Short-lived GET URL the browser streams directly — the API never proxies bytes."""
    return driver_for_uri(uri).presign(uri, creds, expires_s)
