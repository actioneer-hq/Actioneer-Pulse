"""Producer adapters. Import core, never the reverse (import-linter)."""

from __future__ import annotations

from voiceobs.adapters.base import (
    Adapter,
    UnsupportedSchema,
    adapter_for,
    register_adapter,
)
from voiceobs.adapters.generic import OTLPAdapter
from voiceobs.adapters.livekit import LiveKitAdapter
from voiceobs.adapters.vas import VASAdapter

# Specific dialects first; each matches on a signature the others lack.
register_adapter(VASAdapter())
register_adapter(LiveKitAdapter())
# Last: matches anything. A producer VO has never heard of still yields a call and a
# timeline instead of being dropped on the floor.
register_adapter(OTLPAdapter())

__all__ = [
    "Adapter", "LiveKitAdapter", "OTLPAdapter", "UnsupportedSchema",
    "VASAdapter", "adapter_for", "register_adapter",
]
