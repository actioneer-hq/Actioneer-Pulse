"""Producer adapters. Import core, never the reverse (import-linter)."""

from __future__ import annotations

from voiceobs.adapters.base import (
    Adapter,
    UnsupportedSchema,
    adapter_for,
    register_adapter,
)
from voiceobs.adapters.generic import OTLPAdapter
from voiceobs.adapters.vas import VASAdapter

register_adapter(VASAdapter())
# Last: matches anything. A producer VO has never heard of still yields a call and a
# timeline instead of being dropped on the floor.
register_adapter(OTLPAdapter())

__all__ = [
    "Adapter", "OTLPAdapter", "UnsupportedSchema", "VASAdapter",
    "adapter_for", "register_adapter",
]
