"""OpenAI-compatible chat client for the global-chat agent. Provider-agnostic (proven against
Anthropic's compat endpoint): always sends max_tokens, never response_format.

`complete` is a single non-streaming turn used for the tool-calling rounds; `stream` yields text
deltas for the final answer. Both take the tenant's `role=global_chat` LLMConfig."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx

from voiceobs.db.models import LLMConfig

TIMEOUT_S = 120.0
DEFAULT_MAX_TOKENS = 1024


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class Completion:
    content: str
    tool_calls: list[ToolCall]


def _headers(cfg: LLMConfig) -> dict:
    h = {"Content-Type": "application/json"}
    if cfg.api_key:
        h["Authorization"] = f"Bearer {cfg.api_key}"
    return h


def complete(cfg: LLMConfig, messages: list[dict], tools: list[dict] | None = None) -> Completion:
    """One non-streaming turn. Returns the assistant content + any tool calls it requested."""
    body: dict = {
        "model": cfg.model,
        "messages": messages,
        "max_tokens": DEFAULT_MAX_TOKENS,
        **(cfg.params or {}),
    }
    if tools:
        body["tools"] = tools
    resp = httpx.post(cfg.base_url.rstrip("/") + "/chat/completions",
                      json=body, headers=_headers(cfg), timeout=TIMEOUT_S)
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    calls = [
        ToolCall(id=tc.get("id", ""), name=tc["function"]["name"],
                 args=_loads(tc["function"].get("arguments")))
        for tc in (msg.get("tool_calls") or [])
    ]
    return Completion(content=msg.get("content") or "", tool_calls=calls)


def stream(cfg: LLMConfig, messages: list[dict]) -> Iterator[str]:
    """Stream the final answer's text deltas (SSE, `stream:true`). No tools on this pass."""
    body = {
        "model": cfg.model,
        "messages": messages,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "stream": True,
        **(cfg.params or {}),
    }
    with httpx.stream("POST", cfg.base_url.rstrip("/") + "/chat/completions",
                      json=body, headers=_headers(cfg), timeout=TIMEOUT_S) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0].get("delta", {})
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            piece = delta.get("content")
            if piece:
                yield piece


def _loads(raw: str | None) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}
