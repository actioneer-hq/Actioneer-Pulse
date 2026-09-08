"""Gateway 429 backoff: retry honoring Retry-After for non-interactive roles; chat bypasses."""

from __future__ import annotations

import pytest
from any_llm.exceptions import RateLimitError

import voiceobs.llm.gateway as gw
from voiceobs.config import ResolvedLLM
from voiceobs.llm.roles import LLMRole


def _resolved(role: LLMRole) -> ResolvedLLM:
    return ResolvedLLM(role=role, provider="anthropic", model="m", api_key="k",
                       base_url=None, max_tokens=256, prompt="p")


def test_backoff_retries_then_succeeds_honoring_retry_after(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(gw.time, "sleep", lambda s: slept.append(s))
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("slow down", retry_after="2")
        return "OK"

    monkeypatch.setattr(gw, "completion", flaky)
    out = gw.complete(_resolved(LLMRole.POST_CALL_ANALYSIS), [{"role": "user", "content": "x"}])
    assert out == "OK"
    assert calls["n"] == 3
    assert slept == [2.0, 2.0]  # honored Retry-After twice


def test_backoff_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(gw.time, "sleep", lambda s: None)
    monkeypatch.setenv("VOICEOBS_LLM_MAX_RETRIES", "3")
    monkeypatch.setattr(gw, "completion",
                        lambda **k: (_ for _ in ()).throw(RateLimitError("rl", retry_after="0")))
    with pytest.raises(RateLimitError):
        gw.complete(_resolved(LLMRole.FAILURE_ANALYSIS), [{"role": "user", "content": "x"}])


def test_interactive_chat_bypasses_backoff(monkeypatch):
    monkeypatch.setattr(gw.time, "sleep", lambda s: pytest.fail("chat must not back off"))
    monkeypatch.setattr(gw, "completion",
                        lambda **k: (_ for _ in ()).throw(RateLimitError("rl", retry_after="5")))
    # a chat role gets no retry loop — the 429 surfaces immediately, no sleeping
    with pytest.raises(RateLimitError):
        gw.complete(_resolved(LLMRole.GLOBAL_CHAT), [{"role": "user", "content": "x"}])
