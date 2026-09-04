"""Per-model pricing — the single source of truth for call cost.

Add a model here to price it. A model with no entry contributes nothing and the call's
cost stays null (never guessed). Rates are per MILLION tokens / characters and per MINUTE
— the units vendors quote. Keyed by the model name the producer reports
(`gen_ai.request.model`, or the STT/TTS model rolled up from the spans).

All cost calculation imports `MODEL_PRICING` from here; grow this dict as you add models.
The seeded rates are public list prices and approximate — verify against your own contract.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

COST_CURRENCY = "USD"


class ModelPrice(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_per_1m: float = 0.0      # LLM input tokens, per 1M
    output_per_1m: float = 0.0     # LLM output tokens, per 1M
    cached_per_1m: float = 0.0     # cached input tokens, per 1M (usually discounted)
    tts_per_1m_chars: float = 0.0  # TTS, per 1M characters
    stt_per_min: float = 0.0       # STT, per minute of audio


# Approximate public list prices (USD). Edit/extend freely — this dict is meant to grow.
MODEL_PRICING: dict[str, ModelPrice] = {
    # --- OpenAI LLM ---
    "gpt-4o": ModelPrice(input_per_1m=2.50, output_per_1m=10.00, cached_per_1m=1.25),
    "gpt-4o-mini": ModelPrice(input_per_1m=0.15, output_per_1m=0.60, cached_per_1m=0.075),
    "gpt-4.1": ModelPrice(input_per_1m=2.00, output_per_1m=8.00, cached_per_1m=0.50),
    "gpt-4.1-mini": ModelPrice(input_per_1m=0.40, output_per_1m=1.60, cached_per_1m=0.10),
    # --- OpenAI STT (transcription), priced per audio minute ---
    "gpt-4o-transcribe": ModelPrice(stt_per_min=0.006),
    "gpt-4o-mini-transcribe": ModelPrice(stt_per_min=0.003),
    "whisper-1": ModelPrice(stt_per_min=0.006),
    # --- OpenAI TTS, priced per 1M characters ---
    "gpt-4o-mini-tts": ModelPrice(tts_per_1m_chars=12.00),
    "tts-1": ModelPrice(tts_per_1m_chars=15.00),
    "tts-1-hd": ModelPrice(tts_per_1m_chars=30.00),
    # --- common third-party STT/TTS (examples; verify current rates) ---
    "nova-2": ModelPrice(stt_per_min=0.0043),            # Deepgram Nova-2
    "eleven_turbo_v2_5": ModelPrice(tts_per_1m_chars=100.00),  # ElevenLabs Turbo
}


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
