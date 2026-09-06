"""Metric thresholds and definitions. The config IS the metric definition —
versioned with metric_version so it can be swept and shipped per sample-rate."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

METRIC_VERSION = 1

# higher_is_better sentinels for the METRICS table below
UP, DOWN, FLAT = True, False, None


class MetricConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    vad_threshold_dbfs: float = -50.0
    turn_gap_s: float = 1.2
    dead_air_min_s: float = 1.5
    echo_gain_min: float = 0.05
    peaks_per_second: int = 50
    energy_frame_ms: float = 20.0  # dBFS profile cadence (matches the VAD framing)
    clip_dbfs: float = -0.1
    partial_coverage_threshold: float = 0.80  # below -> AUDIO_PARTIAL


class MetricDef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    unit: str
    data_type: str
    description: str
    min_value: float | None = None
    max_value: float | None = None
    higher_is_better: bool | None = None
    metric_version: int = METRIC_VERSION


# (name, unit, type, min, max, higher_is_better, description)
_METRICS: tuple[tuple, ...] = (
    # Layer 1 — audio only
    ("capture_coverage", "ratio", "numeric", 0, 1, UP,
     "Real audio vs padding/absent, per channel. Metric zero: gates all others."),
    ("response_latency_ms", "ms", "numeric", 0, None, DOWN,
     "Caller utterance end -> agent utterance start."),
    ("barge_in", "count", "numeric", 0, None, FLAT,
     "Caller-over-agent utterance overlaps. Measured, not inferred."),
    ("dead_air_s", "s", "numeric", 0, None, DOWN,
     "Silence on both channels, padding excluded."),
    ("talk_ratio", "ratio", "numeric", 0, 1, FLAT,
     "Per-side speaking fraction of call duration."),
    ("overlap_ratio", "ratio", "numeric", 0, 1, DOWN,
     "Fraction of duration with both channels speaking."),
    ("turn_count", "count", "numeric", 0, None, FLAT, "Utterance count per side."),
    ("peak_dbfs", "dbfs", "numeric", None, 0, FLAT, "Peak level per channel."),
    ("rms_dbfs", "dbfs", "numeric", None, 0, FLAT, "RMS level per channel."),
    ("clipping_ratio", "ratio", "numeric", 0, 1, DOWN,
     "Fraction of samples at/above the clip threshold."),
    # Layer 2 — spans joined to audio
    ("llm_ttft_ms", "ms", "numeric", 0, None, DOWN,
     "LLM time-to-first-token. Splits LLM from TTS in the response gap."),
    ("assembly_ms", "ms", "numeric", 0, None, DOWN,
     "llm.first_token -> tts span start: clause-assembly latency."),
    ("tts_ttfb_ms", "ms", "numeric", 0, None, DOWN,
     "TTS time-to-first-byte. Second half of the response gap."),
    ("tokens_per_turn", "tokens", "numeric", 0, None, FLAT,
     "Output tokens per turn, not smeared across the call."),
    ("truncation_rate", "ratio", "numeric", 0, 1, DOWN,
     "tts_chars_cut / tts_chars — fraction never heard."),
    ("chars_per_sec", "count", "numeric", 0, None, FLAT,
     "TTS characters per second — is the agent outrunning the listener?"),
    ("cut_reason", "count", "categorical", None, None, FLAT,
     "Why agent speech was truncated: barge_in (healthy) vs hangup."),
    ("unattributed_ms", "ms", "numeric", 0, None, DOWN,
     "Turn duration minus the sum of its children — found by subtraction."),
    # per-side metrics (caller from audio, agent from spans)
    ("talk_ratio_caller", "ratio", "numeric", 0, 1, FLAT, "Caller speaking fraction."),
    ("talk_ratio_agent", "ratio", "numeric", 0, 1, FLAT, "Agent speaking fraction."),
    ("turn_count_caller", "count", "numeric", 0, None, FLAT, "Caller utterance count."),
    ("turn_count_agent", "count", "numeric", 0, None, FLAT, "Agent turn count (spans)."),
    # producer-reported latency (span attribute), stored beside the event-derived value
    ("llm_ttft_reported_ms", "ms", "numeric", 0, None, DOWN,
     "LLM TTFT as the producer reported it (metrics.ttft attribute)."),
    ("tts_ttfb_reported_ms", "ms", "numeric", 0, None, DOWN,
     "TTS TTFB as the producer reported it (metrics.ttfb attribute)."),
)

METRIC_DEFS: tuple[MetricDef, ...] = tuple(
    MetricDef(
        name=n, unit=u, data_type=t, min_value=lo, max_value=hi,
        higher_is_better=hib, description=desc,
    )
    for n, u, t, lo, hi, hib, desc in _METRICS
)

METRIC_DEFS_BY_NAME: dict[str, MetricDef] = {d.name: d for d in METRIC_DEFS}


# ── Model pricing ──────────────────────────────────────────────────────────────
# Call cost lives in its own file (core/pricing.py) so the per-model price map is easy to
# find and grow. Re-exported here for the existing `from voiceobs.core.config import ...`
# call sites.
from voiceobs.core.pricing import (
    COST_CURRENCY,
    MODEL_PRICING,
    CallCost,
    ModelPrice,
    price_call,
)

__all__ = [  # keep the cost names importable from config for back-compat
    "COST_CURRENCY",
    "MODEL_PRICING",
    "CallCost",
    "ModelPrice",
    "price_call",
]
