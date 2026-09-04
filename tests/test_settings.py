"""Typed settings: defaults, env override, dev-open derivation."""

from __future__ import annotations

from voiceobs.settings import get_settings


def test_defaults(monkeypatch):
    for k in ("VOICEOBS_WORKER_GRACE_S", "VOICEOBS_ACCESS_TTL_MIN", "VOICEOBS_LOG_LEVEL"):
        monkeypatch.delenv(k, raising=False)
    s = get_settings()
    assert s.worker_grace_s == 60.0
    assert s.access_ttl_min == 15
    assert s.log_level == "INFO"


def test_env_override(monkeypatch):
    monkeypatch.setenv("VOICEOBS_WORKER_GRACE_S", "3")
    monkeypatch.setenv("VOICEOBS_ACCESS_TTL_MIN", "5")
    s = get_settings()  # fresh read each call, so the override lands
    assert s.worker_grace_s == 3.0
    assert s.access_ttl_min == 5


def test_is_dev_open_from_flag(monkeypatch):
    monkeypatch.delenv("VOICEOBS_DATABASE_URL", raising=False)
    monkeypatch.setenv("VOICEOBS_DEV_OPEN", "1")
    assert get_settings().is_dev_open is True


def test_is_dev_open_from_sqlite_url(monkeypatch):
    monkeypatch.delenv("VOICEOBS_DEV_OPEN", raising=False)
    monkeypatch.setenv("VOICEOBS_DATABASE_URL", "sqlite:///x.db")
    assert get_settings().is_dev_open is True


def test_not_dev_open_on_postgres(monkeypatch):
    monkeypatch.delenv("VOICEOBS_DEV_OPEN", raising=False)
    monkeypatch.setenv("VOICEOBS_DATABASE_URL", "postgresql://x/y")
    assert get_settings().is_dev_open is False
