"""Producer frameworks. A framework = adapter (OTLP dialect) + calculator (metrics).

`OTLPAdapter` (generic.py) is the framework-agnostic base: it turns any OTLP payload into a
span tree; a dialect subclass just adds the names (stage map, attr aliases). Adding a
framework is "copy a folder": subclass `OTLPAdapter`, then `register(Framework(...))` below.
Supply a `Calculator` subclass only if the producer's timing model differs from the canonical
one. Frameworks import core, never the reverse (import-linter).

The public build ships **LiveKit** as its one concrete dialect. The generic base is present
but NOT registered as a catch-all — a producer that isn't LiveKit is reported unsupported
rather than silently reshaped, until an explicit BYO-OTLP path is added.
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

# Each dialect matches on a signature the others lack. LiveKit is the only shipped dialect;
# the generic OTLPAdapter stays importable as the base (and the foundation for a future
# BYO-OTLP framework) but is deliberately left unregistered.
register(Framework("livekit", LiveKitAdapter()))

__all__ = [
    "Adapter",
    "Framework",
    "LiveKitAdapter",
    "OTLPAdapter",
    "UnsupportedSchema",
    "adapter_for",
    "framework_for",
    "register",
    "register_adapter",
]
