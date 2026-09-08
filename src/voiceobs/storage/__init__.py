"""Object-store access — provider-agnostic (S3-compatible + Azure). Imports nothing from
core/api/worker. Drivers lazy-import their SDKs so the base install stays lean."""

from __future__ import annotations

from voiceobs.storage.config import (
    ResolvedStorage,
    audio_config,
    resolve_creds,
    resolve_storage,
)
from voiceobs.storage.drivers import StorageDriver, driver_for_uri, get_driver
from voiceobs.storage.fetch import fetch_bytes, presign

__all__ = [
    "ResolvedStorage",
    "StorageDriver",
    "audio_config",
    "driver_for_uri",
    "fetch_bytes",
    "get_driver",
    "presign",
    "resolve_creds",
    "resolve_storage",
]
