"""Resolve a per-agent BYO diarization config from AgentAudioConfig (key decrypted here, one place)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.auth.crypto import decrypt
from voiceobs.db.models import AgentAudioConfig
from voiceobs.diarize.client import DiarizeConfig


def resolve_diarize(db: Session, agent_id: str | None) -> DiarizeConfig | None:
    """The diarization config for an agent, or None (not configured → mixed/mono stays caller-only)."""
    if not agent_id:
        return None
    cfg = db.scalar(select(AgentAudioConfig).where(AgentAudioConfig.agent_id == agent_id))
    if cfg is None or not cfg.diarize_base_url or not cfg.diarize_model:
        return None
    return DiarizeConfig(
        base_url=cfg.diarize_base_url,
        model=cfg.diarize_model,
        api_key=decrypt(cfg.diarize_key_ciphertext),
    )
