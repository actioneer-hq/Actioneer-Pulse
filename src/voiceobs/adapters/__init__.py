"""Producer adapters. Import core, never the reverse (import-linter)."""

from __future__ import annotations

from voiceobs.adapters.base import (
    Adapter,
    UnsupportedSchema,
    adapter_for,
    register_adapter,
)
from voiceobs.adapters.vas import VASAdapter

register_adapter(VASAdapter())

__all__ = ["Adapter", "UnsupportedSchema", "VASAdapter", "adapter_for", "register_adapter"]
