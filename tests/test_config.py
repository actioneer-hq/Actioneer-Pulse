"""Typed settings: defaults, env override, dev-open derivation."""

from __future__ import annotations

from voiceobs.config import LLM_ROLES, get_config, resolve_llm
from voiceobs.llm import LLMRole


def test_defaults(monkeypatch):
    for k in ("VOICEOBS_WORKER_GRACE_S", "VOICEOBS_ACCESS_TTL_MIN", "VOICEOBS_LOG_LEVEL"):
        monkeypatch.delenv(k, raising=False)
    s = get_config()
    assert s.worker_grace_s == 60.0
    assert s.access_ttl_min == 15
    assert s.log_level == "INFO"


def test_env_override(monkeypatch):
    monkeypatch.setenv("VOICEOBS_WORKER_GRACE_S", "3")
    monkeypatch.setenv("VOICEOBS_ACCESS_TTL_MIN", "5")
    s = get_config()  # fresh read each call, so the override lands
    assert s.worker_grace_s == 3.0
    assert s.access_ttl_min == 5


def test_is_dev_open_from_flag(monkeypatch):
    monkeypatch.delenv("VOICEOBS_DATABASE_URL", raising=False)
    monkeypatch.setenv("VOICEOBS_DEV_OPEN", "1")
    assert get_config().is_dev_open is True


def test_is_dev_open_from_sqlite_url(monkeypatch):
    monkeypatch.delenv("VOICEOBS_DEV_OPEN", raising=False)
    monkeypatch.setenv("VOICEOBS_DATABASE_URL", "sqlite:///x.db")
    assert get_config().is_dev_open is True


def test_not_dev_open_on_postgres(monkeypatch):
    monkeypatch.delenv("VOICEOBS_DEV_OPEN", raising=False)
    monkeypatch.setenv("VOICEOBS_DATABASE_URL", "postgresql://x/y")
    assert get_config().is_dev_open is False


def test_resolve_llm_none_without_key(monkeypatch):
    monkeypatch.delenv("VOICEOBS_POST_CALL_API_KEY", raising=False)
    assert resolve_llm(LLMRole.POST_CALL_ANALYSIS) is None


def test_resolve_llm_configured_from_env_and_table(monkeypatch):
    monkeypatch.setenv("VOICEOBS_POST_CALL_API_KEY", "sk-abc")
    r = resolve_llm(LLMRole.POST_CALL_ANALYSIS)
    assert r is not None
    assert r.api_key == "sk-abc"                          # from env
    assert r.provider == LLM_ROLES[LLMRole.POST_CALL_ANALYSIS].provider  # from config table
    assert r.model == LLM_ROLES[LLMRole.POST_CALL_ANALYSIS].model
    assert r.prompt  # committed default prompt for the role
