"""Object-store access. Imports nothing from core/api/worker."""

from __future__ import annotations

from voiceobs.storage.fetch import fetch_bytes, list_objects, presign

__all__ = ["fetch_bytes", "list_objects", "presign"]
