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
# The call's cost is computed from the models it ran and their usage (tokens, TTS
# characters, STT seconds). Register a model here to price it; a model with no entry
# contributes nothing and the call's cost stays null (never guessed). Rates are per
# MILLION tokens / characters and per MINUTE — the units vendors quote.
COST_CURRENCY = "USD"


class ModelPrice(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_per_1m: float = 0.0    # LLM input tokens, per 1M
    output_per_1m: float = 0.0   # LLM output tokens, per 1M
    cached_per_1m: float = 0.0   # cached input tokens, per 1M (usually discounted)
    tts_per_1m_chars: float = 0.0  # TTS, per 1M characters
    stt_per_min: float = 0.0     # STT, per minute of audio


# Keyed by the model name the producer reports (gen_ai.request.model). Populate for
# the models you run, e.g.:
#   "gpt-4o-mini": ModelPrice(input_per_1m=0.15, output_per_1m=0.60),
#   "gpt-4o-mini-tts": ModelPrice(tts_per_1m_chars=60.0),
#   "gpt-4o-mini-transcribe": ModelPrice(stt_per_min=0.003),
MODEL_PRICING: dict[str, ModelPrice] = {}


class CallCost(BaseModel):
    model_config = ConfigDict(frozen=True)

    llm: float | None = None
    stt: float | None = None
    tts: float | None = None
    total: float | None = None
    currency: str = COST_CURRENCY


def price_call(
    *,
    llm_model: str | None,
    stt_model: str | None,
    tts_model: str | None,
    tokens_in: int | None,
    tokens_out: int | None,
    tokens_cached: int | None,
    tts_chars: int | None,
    stt_seconds: float | None,
    pricing: dict[str, ModelPrice] | None = None,
) -> CallCost:
    """Cost of one call from its models and usage. Each side is priced only when its
    model is registered; an unpriced side is None (not zero) so a partial price never
    reads as a complete one."""
    p = MODEL_PRICING if pricing is None else pricing
    llm_p, stt_p, tts_p = p.get(llm_model or ""), p.get(stt_model or ""), p.get(tts_model or "")

    llm = stt = tts = None
    if llm_p is not None:
        billable_in = max((tokens_in or 0) - (tokens_cached or 0), 0)
        llm = round(
            billable_in / 1e6 * llm_p.input_per_1m
            + (tokens_out or 0) / 1e6 * llm_p.output_per_1m
            + (tokens_cached or 0) / 1e6 * llm_p.cached_per_1m,
            6,
        )
    if tts_p is not None and tts_p.tts_per_1m_chars:
        tts = round((tts_chars or 0) / 1e6 * tts_p.tts_per_1m_chars, 6)
    if stt_p is not None and stt_p.stt_per_min:
        stt = round((stt_seconds or 0) / 60 * stt_p.stt_per_min, 6)

    parts = [c for c in (llm, stt, tts) if c is not None]
    total = round(sum(parts), 6) if parts else None
    return CallCost(llm=llm, stt=stt, tts=tts, total=total)
