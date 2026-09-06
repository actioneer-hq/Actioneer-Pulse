"""Judge client over the any-llm gateway — native structured output, with a JSON-content fallback."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from voiceobs.config import ResolvedLLM
from voiceobs.judge import client as judge_client
from voiceobs.judge.client import call_model
from voiceobs.judge.schema import JudgeOutput
from voiceobs.llm import LLMRole

_GOOD = json.dumps({
    "sentiment": "neutral", "objective_achieved": "partial", "answered_by": "human",
    "primary_language": "en", "secondary_languages": [], "script_adherence": "partial",
})


def _resolved() -> ResolvedLLM:
    return ResolvedLLM(role=LLMRole.POST_CALL_ANALYSIS, provider="anthropic", model="m",
                       api_key="sk", base_url=None, max_tokens=512, prompt="p")


def _resp(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_native_parsed_structured_output(monkeypatch):
    parsed = JudgeOutput(sentiment="neutral", objective_achieved="partial", answered_by="human",
                         primary_language="en", secondary_languages=[], script_adherence="partial")
    msg = SimpleNamespace(parsed=parsed, content=None)
    monkeypatch.setattr(judge_client.gateway, "complete", lambda *a, **k: _resp(msg))
    out = call_model(_resolved(), [{"role": "user", "content": "x"}])
    assert out.sentiment == "neutral"
    assert out.answered_by == "human"


def test_json_content_fallback(monkeypatch):
    # provider returned JSON text without a parsed object → we validate the content
    msg = SimpleNamespace(parsed=None, content=_GOOD)
    monkeypatch.setattr(judge_client.gateway, "complete", lambda *a, **k: _resp(msg))
    out = call_model(_resolved(), [{"role": "user", "content": "x"}])
    assert out.objective_achieved == "partial"


def test_malformed_content_raises(monkeypatch):
    msg = SimpleNamespace(parsed=None, content="not json")
    monkeypatch.setattr(judge_client.gateway, "complete", lambda *a, **k: _resp(msg))
    with pytest.raises(ValueError):  # pydantic ValidationError subclasses ValueError
        call_model(_resolved(), [{"role": "user", "content": "x"}])
