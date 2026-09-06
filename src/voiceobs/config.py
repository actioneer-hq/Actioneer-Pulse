"""Central application config — the one place to configure Pulse.

Two layers:
  • SECRETS come from the environment ONLY (`VOICEOBS_`-prefixed): API keys, DATABASE_URL,
    SECRET_KEY, the bootstrap password. They have no in-file default and must never be committed.
  • APP CONFIG lives here as editable defaults (still env-overridable for 12-factor/Docker/tests):
    dev knobs, worker/reconcile, token lifetimes, and the per-role LLM table (LLM_ROLES).

Edit LLM_ROLES to pick the provider/model for each role; put the matching API key in the env
(one per role, see `.env.example`). Other product behavior lives in committed code too: metric
definitions in `core/config.py`, model pricing in `core/pricing.py`, prompts in `llm/prompts.py`.

`get_config()` returns a FRESH Config() each call (not cached) so a test's `monkeypatch.setenv`
takes effect immediately. `core` must never import this (core stays pure) — only auth/db/api/worker/llm do.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict

from voiceobs.llm import LLMRole, default_prompt


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOICEOBS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── SECRETS (env only; no default in a real deployment) ──────────────────────────
    secret_key: str | None = None
    database_url: str | None = None
    bootstrap_password: str = ""
    # Per-role LLM keys — one per role in LLM_ROLES. Model/provider are set below; keys stay in env.
    post_call_api_key: str | None = None
    global_chat_api_key: str | None = None
    per_call_chat_api_key: str | None = None
    failure_analysis_api_key: str | None = None

    # ── APP CONFIG (edit here; env can still override) ───────────────────────────────
    dev_open: bool = False
    log_level: str = "INFO"
    audio_analysis: bool = False        # global default; per-agent config overrides
    allow_delete: bool = False
    # dev-only: when set, fetch_bytes resolves s3://bucket/key from {dir}/key on local disk
    # instead of hitting S3 — lets playback/ingest work without a real bucket.
    dev_audio_dir: str | None = None
    bootstrap_email: str = ""
    bootstrap_org: str = "Default"

    # operational (worker / reconcile)
    worker_poll_s: float = 5.0
    worker_batch: int = 10
    worker_grace_s: float = 60.0
    reconcile_grace_s: float = 600.0
    reconcile_interval_s: float | None = None

    # auth token lifetimes
    access_ttl_min: int = 15
    refresh_ttl_days: int = 14
    invite_ttl_days: int = 7

    @property
    def is_dev_open(self) -> bool:
        """Dev conveniences on: the flag is set, or the DB is SQLite (a source checkout / test).
        Gates secret fallbacks and token-less ingest — never true in a real Postgres deploy
        unless explicitly asked for."""
        return bool(self.dev_open) or (self.database_url or "").startswith("sqlite")

    def _role_api_key(self, role: LLMRole) -> str | None:
        return getattr(self, _ROLE_KEY_FIELD[role])


def get_config() -> Config:
    return Config()


# ── Per-role LLM table — pick provider + model per role; the key comes from env ──────────
@dataclass(frozen=True)
class LLMRoleCfg:
    provider: str                    # any-llm provider id, e.g. "anthropic", "openai"
    model: str
    base_url: str | None = None      # optional; set for an OpenAI-compatible/self-hosted endpoint
    max_tokens: int = 1024


# EDIT ME: the model each role uses. Put the matching key in env (see `.env.example`).
LLM_ROLES: dict[LLMRole, LLMRoleCfg] = {
    LLMRole.POST_CALL_ANALYSIS: LLMRoleCfg(provider="anthropic", model="claude-haiku-4-5"),
    LLMRole.GLOBAL_CHAT:        LLMRoleCfg(provider="anthropic", model="claude-haiku-4-5"),
    LLMRole.PER_CALL_CHAT:      LLMRoleCfg(provider="anthropic", model="claude-haiku-4-5"),
    LLMRole.FAILURE_ANALYSIS:   LLMRoleCfg(provider="anthropic", model="claude-haiku-4-5"),  # reserved
}

_ROLE_KEY_FIELD: dict[LLMRole, str] = {
    LLMRole.POST_CALL_ANALYSIS: "post_call_api_key",
    LLMRole.GLOBAL_CHAT: "global_chat_api_key",
    LLMRole.PER_CALL_CHAT: "per_call_chat_api_key",
    LLMRole.FAILURE_ANALYSIS: "failure_analysis_api_key",
}


@dataclass(frozen=True)
class ResolvedLLM:
    """Everything a client needs to call a role's model: the LLM_ROLES entry + the env key +
    the role's committed default prompt."""
    role: LLMRole
    provider: str
    model: str
    api_key: str
    base_url: str | None
    max_tokens: int
    prompt: str


def resolve_llm(role: LLMRole) -> ResolvedLLM | None:
    """The configured model for a role, or None when its API key is unset (role not configured —
    callers skip gracefully). Merges LLM_ROLES[role] + the env key + default_prompt(role)."""
    cfg = LLM_ROLES.get(role)
    if cfg is None:
        return None
    key = get_config()._role_api_key(role)
    if not key:
        return None
    return ResolvedLLM(
        role=role, provider=cfg.provider, model=cfg.model, api_key=key,
        base_url=cfg.base_url, max_tokens=cfg.max_tokens, prompt=default_prompt(role),
    )
