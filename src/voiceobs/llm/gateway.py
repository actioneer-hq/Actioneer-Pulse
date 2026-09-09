"""The single LLM gateway, over any-llm. Every model call in Pulse goes through here so provider
differences (structured output, streaming, tool schemas, max_tokens) are handled in one place
instead of hand-rolled per client. Takes a `ResolvedLLM` (provider/model/key/base_url) from
`config.resolve_llm(role)`."""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable, Iterator

# Normalize provider errors to any-llm's exception hierarchy (AuthenticationError, RateLimitError,
# …). Must be set before any_llm is imported.
os.environ.setdefault("ANY_LLM_UNIFIED_EXCEPTIONS", "1")

from any_llm import completion, embedding
from any_llm.exceptions import RateLimitError

from voiceobs.config import ResolvedEmbedding, ResolvedLLM, get_config
from voiceobs.llm.roles import INTERACTIVE_ROLES

log = logging.getLogger(__name__)


def _retry_after_seconds(value: str | None) -> float | None:
    """Parse a Retry-After value (seconds; HTTP-date form is ignored → fall back to backoff)."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _with_backoff(fn: Callable, *, interactive: bool):
    """Call an LLM op, retrying on 429 with the server's Retry-After (else exponential backoff +
    jitter), capped at llm_max_retries. Interactive (chat) roles bypass — they never wait on a
    backfill; a rate-limit surfaces to the caller instead."""
    if interactive:
        return fn()
    cfg = get_config()
    for attempt in range(cfg.llm_max_retries):
        try:
            return fn()
        except RateLimitError as e:
            if attempt == cfg.llm_max_retries - 1:
                raise
            delay = _retry_after_seconds(getattr(e, "retry_after", None))
            if delay is None:
                delay = cfg.llm_backoff_base_s * (2 ** attempt) + random.uniform(0, 0.5)
            log.warning("LLM rate-limited; backing off %.1fs (attempt %d/%d)",
                        delay, attempt + 1, cfg.llm_max_retries)
            time.sleep(delay)


def _kwargs(resolved: ResolvedLLM) -> dict:
    return {
        "provider": resolved.provider,
        "model": resolved.model,
        "api_key": resolved.api_key,
        "api_base": resolved.base_url,
        "max_tokens": resolved.max_tokens,
    }


def complete(
    resolved: ResolvedLLM,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    response_format: type | None = None,
):
    """One non-streaming turn. Returns any-llm's ChatCompletion (OpenAI-shaped). Pass
    `response_format=SomePydanticModel` for structured output (read `.choices[0].message.parsed`);
    pass `tools` (OpenAI-style dict schemas) to allow tool calls."""
    interactive = getattr(resolved, "role", None) in INTERACTIVE_ROLES
    return _with_backoff(
        lambda: completion(
            messages=messages,
            tools=tools,
            tool_choice="auto" if tools else None,
            response_format=response_format,
            **_kwargs(resolved),
        ),
        interactive=interactive,
    )


def stream(resolved: ResolvedLLM, messages: list[dict]) -> Iterator[str]:
    """Stream the answer's text deltas. No tools on this pass."""
    for chunk in completion(messages=messages, stream=True, **_kwargs(resolved)):
        piece = chunk.choices[0].delta.content
        if piece:
            yield piece


def embed(resolved: ResolvedEmbedding, inputs: list[str]) -> list[list[float]]:
    """Embed a batch of texts with the BYO embedding model. Returns one vector per input, in order.
    Embeddings are non-interactive → they get the 429 backoff."""
    resp = _with_backoff(
        lambda: embedding(
            model=resolved.model, inputs=inputs, provider=resolved.provider,
            api_key=resolved.api_key, api_base=resolved.base_url,
        ),
        interactive=False,
    )
    return [d.embedding for d in resp.data]
