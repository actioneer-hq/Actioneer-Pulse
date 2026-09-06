"""Typed application settings — the single source of truth for env-driven config.

Split: **env** holds secrets + per-deployment knobs (this file); **committed code** holds product
behavior (metric defs in core/config.py, model pricing in core/pricing.py, LLM prompts in llm/).
Everything here is `VOICEOBS_`-prefixed and can live in a `.env` (see .env.example).

`get_settings()` returns a FRESH Settings() each call (not cached) so a test's
`monkeypatch.setenv` takes effect immediately; hot paths that want a snapshot read it once.
`core` must never import this (core stays pure) — only auth/db/api/worker do."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOICEOBS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- secrets (no default; required outside dev-open) ---
    secret_key: str | None = None
    database_url: str | None = None
    bootstrap_password: str = ""

    # --- deployment knobs ---
    dev_open: bool = False
    log_level: str = "INFO"
    audio_analysis: bool = False        # global default; per-agent config overrides
    allow_delete: bool = False
    # dev-only: when set, fetch_bytes resolves s3://bucket/key from {dir}/key on local disk
    # instead of hitting S3 — lets playback/ingest work without a real bucket. Prod leaves
    # this unset and always goes to S3; the DB still stores real s3:// URIs either way.
    dev_audio_dir: str | None = None
    bootstrap_email: str = ""
    bootstrap_org: str = "Default"

    # --- operational (worker / reconcile) ---
    worker_poll_s: float = 5.0
    worker_batch: int = 10
    worker_grace_s: float = 60.0
    reconcile_grace_s: float = 600.0
    reconcile_interval_s: float | None = None

    # --- auth token lifetimes ---
    access_ttl_min: int = 15
    refresh_ttl_days: int = 14
    invite_ttl_days: int = 7

    @property
    def is_dev_open(self) -> bool:
        """Dev conveniences on: the flag is set, or the DB is SQLite (a source checkout / test).
        Gates secret fallbacks and token-less ingest — never true in a real Postgres deploy
        unless explicitly asked for."""
        return bool(self.dev_open) or (self.database_url or "").startswith("sqlite")


def get_settings() -> Settings:
    return Settings()
