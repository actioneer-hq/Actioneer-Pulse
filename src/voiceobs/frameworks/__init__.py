"""Producer frameworks. A framework = adapter (OTLP dialect) + calculator (metrics).

Adding one: create a subpackage, subclass `OTLPAdapter` for the dialect, and register a
`Framework` below. Supply a `Calculator` subclass only if the producer's timing model
differs from the canonical one. Frameworks import core, never the reverse (import-linter).
"""

from __future__ import annotations

from voiceobs.frameworks.base import (
    Adapter,
    Framework,
    UnsupportedSchema,
    adapter_for,
    framework_for,
    register,
    register_adapter,
)
from voiceobs.frameworks.generic import OTLPAdapter
from voiceobs.frameworks.livekit import LiveKitAdapter
from voiceobs.frameworks.vas import VASAdapter

# Specific dialects first; each matches on a signature the others lack. The generic OTLP
# adapter matches anything, so it is registered last — a producer VO has never heard of
# still yields a call and a timeline instead of being dropped on the floor.
register(Framework("vas", VASAdapter()))
register(Framework("livekit", LiveKitAdapter()))
register(Framework("otlp", OTLPAdapter()))

__all__ = [
    "Adapter",
    "Framework",
    "LiveKitAdapter",
    "OTLPAdapter",
    "UnsupportedSchema",
    "VASAdapter",
    "adapter_for",
    "framework_for",
    "register",
    "register_adapter",
]
