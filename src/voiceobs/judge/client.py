"""BYO OpenAI-style model call. The bare backbone: send messages + the client's params,
parse the JSON content, validate it. One retry on a malformed body."""

from __future__ import annotations

import json

import httpx

from voiceobs.db.models import LLMConfig
from voiceobs.judge.schema import JudgeOutput

TIMEOUT_S = 60.0


def call_model(config: LLMConfig, messages: list[dict]) -> JudgeOutput:
    """POST to {base_url}/chat/completions and validate the reply against JudgeOutput."""
    body = {
        "model": config.model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        **(config.params or {}),  # client params win — reasoning, temperature, etc.
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
            return JudgeOutput.model_validate(json.loads(content))
        except Exception as e:  # noqa: BLE001 — retry once, then surface
            last = e
    raise RuntimeError(f"judge model call failed: {last}")
