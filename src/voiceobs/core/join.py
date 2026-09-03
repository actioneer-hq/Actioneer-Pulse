"""Back-compat surface for the Layer-2 analysis.

`join()` is the functional entry point; it delegates to the default `Calculator`. New code
should prefer `Calculator().analyze(...)` (a framework may supply its own Calculator), but
`join` stays because the API/worker/tests call it directly. `_first_event_t` is re-exported
for tests that reach for it.
"""

from __future__ import annotations

from voiceobs.core.calculator import Calculator, _first_event_t
from voiceobs.core.config import MetricConfig
from voiceobs.core.model import Analysis, AudioAnalysis, Trace

__all__ = ["Calculator", "join"]


def join(
    trace: Trace,
    audio: AudioAnalysis | None,
    cfg: MetricConfig | None = None,
    t0_offset_s: float | None = None,
    audio_enabled: bool = True,
) -> Analysis:
    """Analyse one call with the default (generic) Calculator."""
    return Calculator().analyze(trace, audio, cfg, t0_offset_s, audio_enabled)


_ = _first_event_t  # re-exported for tests importing it from this module
