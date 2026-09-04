"""build_messages — committed default vs per-tenant prompt override, role-keyed."""

from __future__ import annotations

from voiceobs.judge.prompt import build_messages
from voiceobs.llm import LLMRole, default_prompt


def test_uses_committed_default_when_no_override():
    msgs = build_messages("script", {"text": "hi"})
    sys = msgs[0]["content"]
    assert "call-quality judge" in sys  # the POST_CALL_ANALYSIS default
    assert "{schema}" not in sys        # schema was substituted in


def test_uses_tenant_override_when_set():
    msgs = build_messages("script", {"text": "hi"}, prompt="CUSTOM JUDGE {schema}")
    assert msgs[0]["content"].startswith("CUSTOM JUDGE ")
    assert "call-quality judge" not in msgs[0]["content"]


def test_override_with_stray_braces_does_not_crash():
    # a tenant prompt may contain unrelated braces — must not KeyError
    msgs = build_messages("s", {"text": "hi"}, prompt="Return {json} now. {schema}")
    assert "{json}" in msgs[0]["content"]  # left intact, only {schema} replaced


def test_default_prompt_registry_has_all_roles():
    for role in LLMRole:
        assert default_prompt(role)
