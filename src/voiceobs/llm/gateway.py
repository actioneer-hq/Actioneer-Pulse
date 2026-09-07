"""The single LLM gateway, over any-llm. Every model call in Pulse goes through here so provider
differences (structured output, streaming, tool schemas, max_tokens) are handled in one place
instead of hand-rolled per client. Takes a `ResolvedLLM` (provider/model/key/base_url) from
`config.resolve_llm(role)`."""

from __future__ import annotations

import os
from collections.abc import Iterator

# Normalize provider errors to any-llm's exception hierarchy (AuthenticationError, RateLimitError,
# …). Must be set before any_llm is imported.
os.environ.setdefault("ANY_LLM_UNIFIED_EXCEPTIONS", "1")

from any_llm import completion, embedding

from voiceobs.config import ResolvedEmbedding, ResolvedLLM


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
    return completion(
        messages=messages,
        tools=tools,
        tool_choice="auto" if tools else None,
        response_format=response_format,
        **_kwargs(resolved),
    )


def stream(resolved: ResolvedLLM, messages: list[dict]) -> Iterator[str]:
    """Stream the answer's text deltas. No tools on this pass."""
    for chunk in completion(messages=messages, stream=True, **_kwargs(resolved)):
        piece = chunk.choices[0].delta.content
        if piece:
            yield piece


def embed(resolved: ResolvedEmbedding, inputs: list[str]) -> list[list[float]]:
    """Embed a batch of texts with the BYO embedding model. Returns one vector per input, in order."""
    resp = embedding(
        model=resolved.model, inputs=inputs, provider=resolved.provider,
        api_key=resolved.api_key, api_base=resolved.base_url,
    )
    return [d.embedding for d in resp.data]
