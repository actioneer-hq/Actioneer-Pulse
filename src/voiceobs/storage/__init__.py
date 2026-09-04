"""Object-store access. Imports nothing from core/api/worker."""

from __future__ import annotations

from voiceobs.storage.config import audio_config, resolve_s3_creds
from voiceobs.storage.fetch import S3Creds, fetch_bytes, list_objects, presign

__all__ = [
    "S3Creds",
    "audio_config",
    "fetch_bytes",
    "list_objects",
    "presign",
    "resolve_s3_creds",
]
