"""BYO model client — parses/validates a chat-completions reply; retries once."""

from __future__ import annotations

import json

import httpx
import pytest

from voiceobs.db.models import LLMConfig
from voiceobs.judge.client import call_model


def _reply(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]},
        request=httpx.Request("POST", "https://m/v1/chat/completions"),
    )


_GOOD = json.dumps({
    "sentiment": "neutral", "objective_achieved": "partial", "answered_by": "human",
    "primary_language": "en", "secondary_languages": [], "script_adherence": "partial",
})


def _cfg() -> LLMConfig:
    return LLMConfig(tenant_id="t", base_url="https://m/v1", model="gpt-x",
                       api_key="sk-1", params={"temperature": 0})


def test_valid_reply_parsed(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _reply(_GOOD))
    out = call_model(_cfg(), [{"role": "user", "content": "x"}])
    assert out.sentiment == "neutral"
    assert out.answered_by == "human"


def test_malformed_then_fails(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _reply("not json"))
    with pytest.raises(RuntimeError):
        call_model(_cfg(), [{"role": "user", "content": "x"}])
