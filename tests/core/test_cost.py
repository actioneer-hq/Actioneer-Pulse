"""Model pricing -> call cost. Unpriced sides stay None, never zero."""

from __future__ import annotations

from voiceobs.core.config import ModelPrice, price_call

PRICING = {
    "gpt-4o-mini": ModelPrice(input_per_1m=0.15, output_per_1m=0.60, cached_per_1m=0.075),
    "gpt-4o-mini-tts": ModelPrice(tts_per_1m_chars=60.0),
    "gpt-4o-mini-transcribe": ModelPrice(stt_per_min=0.003),
}


def test_prices_each_side_from_its_model():
    c = price_call(
        llm_model="gpt-4o-mini", stt_model="gpt-4o-mini-transcribe", tts_model="gpt-4o-mini-tts",
        tokens_in=1000, tokens_out=500, tokens_cached=0, tts_chars=2000, stt_seconds=120,
        pricing=PRICING,
    )
    assert c.llm == round(1000 / 1e6 * 0.15 + 500 / 1e6 * 0.60, 6)
    assert c.tts == round(2000 / 1e6 * 60.0, 6)
    assert c.stt == round(120 / 60 * 0.003, 6)
    assert c.total == round(c.llm + c.tts + c.stt, 6)
    assert c.currency == "USD"


def test_cached_tokens_are_discounted_not_double_billed():
    c = price_call(
        llm_model="gpt-4o-mini", stt_model=None, tts_model=None,
        tokens_in=1000, tokens_out=0, tokens_cached=400, tts_chars=None, stt_seconds=None,
        pricing=PRICING,
    )
    # 600 billed at input rate, 400 at the cached rate
    assert c.llm == round(600 / 1e6 * 0.15 + 400 / 1e6 * 0.075, 6)


def test_unpriced_model_leaves_cost_null():
    c = price_call(
        llm_model="some-unlisted-model", stt_model=None, tts_model=None,
        tokens_in=1000, tokens_out=500, tokens_cached=0, tts_chars=None, stt_seconds=None,
        pricing=PRICING,
    )
    assert c.llm is None and c.total is None


def test_unregistered_model_costs_nothing():
    # A model absent from MODEL_PRICING contributes nothing — cost is never guessed.
    c = price_call(
        llm_model="some-unlisted-model", stt_model=None, tts_model=None,
        tokens_in=1000, tokens_out=500, tokens_cached=0, tts_chars=None, stt_seconds=None,
    )
    assert c.total is None


def test_seeded_model_is_priced():
    # MODEL_PRICING ships with common models seeded; add more in core/pricing.py.
    c = price_call(
        llm_model="gpt-4o-mini", stt_model=None, tts_model=None,
        tokens_in=1_000_000, tokens_out=1_000_000, tokens_cached=0,
        tts_chars=None, stt_seconds=None,
    )
    assert c.total == round(0.15 + 0.60, 6)  # $0.15/1M in + $0.60/1M out
