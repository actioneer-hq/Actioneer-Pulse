"""Pulse core — pure types + the two analysis functions. No I/O, no DB, no network."""

from __future__ import annotations

from voiceobs.core.audio import analyze_audio
from voiceobs.core.calculator import Calculator
from voiceobs.core.config import (
    METRIC_DEFS,
    METRIC_DEFS_BY_NAME,
    METRIC_VERSION,
    MetricConfig,
    MetricDef,
)
from voiceobs.core.join import join
from voiceobs.core.model import (
    Analysis,
    AudioAnalysis,
    AudioRef,
    CallHeader,
    MetricValue,
    Span,
    SpanEvent,
    Stage,
    Trace,
    TrustReason,
    TrustReport,
    Turn,
    Utterance,
)

__all__ = [
    "METRIC_DEFS",
    "METRIC_DEFS_BY_NAME",
    "METRIC_VERSION",
    "Analysis",
    "AudioAnalysis",
    "AudioRef",
    "Calculator",
    "CallHeader",
    "MetricConfig",
    "MetricDef",
    "MetricValue",
    "Span",
    "SpanEvent",
    "Stage",
    "Trace",
    "TrustReason",
    "TrustReport",
    "Turn",
    "Utterance",
    "analyze_audio",
    "join",
]
