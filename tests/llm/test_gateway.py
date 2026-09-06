"""The any-llm gateway wrapper — passes the ResolvedLLM through and shapes streaming."""

from __future__ import annotations

from types import SimpleNamespace

from voiceobs.config import ResolvedLLM
from voiceobs.llm import LLMRole, gateway


def _resolved() -> ResolvedLLM:
    return ResolvedLLM(role=LLMRole.GLOBAL_CHAT, provider="anthropic", model="claude-x",
                       api_key="sk-1", base_url=None, max_tokens=256, prompt="p")


def test_complete_forwards_resolved(monkeypatch):
    seen = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message="ok")])

    monkeypatch.setattr(gateway, "completion", fake_completion)
    resp = gateway.complete(_resolved(), [{"role": "user", "content": "hi"}], tools=[{"x": 1}])
    assert resp.choices[0].message == "ok"
    assert seen["provider"] == "anthropic" and seen["model"] == "claude-x"
    assert seen["api_key"] == "sk-1" and seen["max_tokens"] == 256
    assert seen["tools"] == [{"x": 1}] and seen["tool_choice"] == "auto"


def test_stream_yields_content_deltas(monkeypatch):
    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hel"))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),  # skipped
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="lo"))]),
    ]
    monkeypatch.setattr(gateway, "completion", lambda **k: iter(chunks))
    assert "".join(gateway.stream(_resolved(), [{"role": "user", "content": "x"}])) == "Hello"
