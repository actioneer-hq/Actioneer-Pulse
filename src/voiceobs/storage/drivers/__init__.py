"""Blob-store drivers. Everything customer-variable (bucket, key layout, which creds) is DATA
(the descriptor + a credential dict); the only per-provider CODE is here, because auth signing
(SigV4 / Azure Shared-Key) is algorithmic, not data. S3-compatible covers S3/MinIO/R2/Ceph/B2/
Spaces/Wasabi/Yandex/Alibaba and GCS (interop HMAC); Azure Blob is the lone S3-incompatible outlier.

Two access patterns:
- `list(descriptor, creds)` — used by reconcile to enumerate a store from the descriptor.
- `fetch_bytes(uri, creds)` / `presign(uri, creds)` — used by playback/analysis for a specific object,
  routed by the uri scheme (`driver_for_uri`)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class StorageDriver(Protocol):
    scheme: str  # the uri scheme this driver's list() emits and fetch/presign consume

    def list(self, descriptor: dict, creds: dict) -> list[tuple[str, datetime]]: ...
    def fetch_bytes(self, uri: str, creds: dict | None) -> bytes: ...
    def presign(self, uri: str, creds: dict | None, expires_s: int = 900) -> str: ...


def get_driver(provider: str) -> StorageDriver:
    """Driver for a provider tag (from AgentAudioConfig.provider). Drivers lazy-import their SDKs."""
    if provider == "s3_compatible":
        from voiceobs.storage.drivers.s3 import S3Driver
        return S3Driver()
    if provider == "azure":
        from voiceobs.storage.drivers.azure import AzureDriver
        return AzureDriver()
    raise ValueError(f"unknown storage provider: {provider}")


def driver_for_uri(uri: str) -> StorageDriver:
    """Driver for a stored object uri, by scheme (`s3://…` or `azblob://…`)."""
    if uri.startswith("s3://"):
        from voiceobs.storage.drivers.s3 import S3Driver
        return S3Driver()
    if uri.startswith("azblob://"):
        from voiceobs.storage.drivers.azure import AzureDriver
        return AzureDriver()
    raise NotImplementedError(f"unsupported storage uri scheme: {uri}")
