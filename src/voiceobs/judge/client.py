"""BYO OpenAI-style model call. Provider-agnostic: send messages, parse the JSON content,
validate it. One retry on a malformed body.

Kept portable across OpenAI-compatible endpoints (OpenAI, Anthropic's compat layer, local
servers): we do NOT send `response_format` (Anthropic rejects `json_object`, others vary) —
the prompt already demands JSON-only, and we extract the JSON object from the reply. `max_tokens`
is always sent because some providers (Anthropic) require it. Override anything via config.params.
"""

from __future__ import annotations

import json

import httpx

from voiceobs.db.models import LLMConfig
from voiceobs.judge.schema import JudgeOutput

TIMEOUT_S = 60.0
DEFAULT_MAX_TOKENS = 1024


def call_model(config: LLMConfig, messages: list[dict]) -> JudgeOutput:
    """POST to {base_url}/chat/completions and validate the reply against JudgeOutput."""
    body = {
        "model": config.model,
        "messages": messages,
        "max_tokens": DEFAULT_MAX_TOKENS,  # required by some providers; overridable via params
        **(config.params or {}),  # client params win — reasoning, temperature, response_format…
    }
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    url = config.base_url.rstrip("/") + "/chat/completions"

    last: Exception | None = None
    for _ in range(2):
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=TIMEOUT_S)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return JudgeOutput.model_validate(json.loads(_extract_json(content)))
        except Exception as e:  # noqa: BLE001 — retry once, then surface
            last = e
    raise RuntimeError(f"judge model call failed: {last}")


def _extract_json(content: str) -> str:
    """The JSON object out of a model reply — tolerating ```json fences or surrounding prose
    (Claude et al. sometimes wrap it). Falls back to the raw content."""
    s = content.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s[3:] else s[3:]
        s = s.removeprefix("json").strip()
    start, end = s.find("{"), s.rfind("}")
    return s[start : end + 1] if start != -1 and end > start else s
