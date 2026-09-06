"""Chat client for the global-chat agent, over the any-llm gateway. `complete` is a single
non-streaming turn (tool-calling rounds); `stream` yields text deltas for the final answer. Both
take a `ResolvedLLM` (from config.resolve_llm)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field

from voiceobs.config import ResolvedLLM
from voiceobs.llm import gateway


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class Completion:
    content: str
    tool_calls: list[ToolCall]


def complete(
    resolved: ResolvedLLM, messages: list[dict], tools: list[dict] | None = None
) -> Completion:
    """One non-streaming turn. Returns the assistant content + any tool calls it requested."""
    resp = gateway.complete(resolved, messages, tools=tools)
    msg = resp.choices[0].message
    calls = [
        ToolCall(id=tc.id or "", name=tc.function.name, args=_loads(tc.function.arguments))
        for tc in (msg.tool_calls or [])
    ]
    return Completion(content=msg.content or "", tool_calls=calls)


def stream(resolved: ResolvedLLM, messages: list[dict]) -> Iterator[str]:
    """Stream the final answer's text deltas. No tools on this pass."""
    yield from gateway.stream(resolved, messages)


def _loads(raw: str | None) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}
