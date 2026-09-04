"""Resolve a per-agent BYO STT config from AgentAudioConfig (key decrypted here, in one place)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.auth.crypto import decrypt
from voiceobs.db.models import AgentAudioConfig
from voiceobs.groundtruth.stt.client import STTConfig


def resolve_stt(db: Session, agent_id: str | None) -> STTConfig | None:
    """The STT config for an agent, or None (not configured → transcript check is skipped)."""
    if not agent_id:
        return None
    cfg = db.scalar(select(AgentAudioConfig).where(AgentAudioConfig.agent_id == agent_id))
    if cfg is None or not cfg.stt_base_url or not cfg.stt_model:
        return None
    return STTConfig(
        base_url=cfg.stt_base_url,
        model=cfg.stt_model,
        api_key=decrypt(cfg.stt_key_ciphertext),
    )
