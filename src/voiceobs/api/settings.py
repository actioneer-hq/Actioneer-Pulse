"""Per-org platform settings — currently the audio-analysis toggle (off by default). Org
comes from the session; writes require admin."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import now, session_dep
from voiceobs.api.schemas import SettingsIn
from voiceobs.auth import current_membership, require_role
from voiceobs.db.models import Membership, TenantSettings

router = APIRouter(prefix="/v1")


@router.post("/settings")
def set_settings(
    body: SettingsIn,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    s = db.scalar(select(TenantSettings))  # one row per schema
    if s is None:
        s = TenantSettings()
        db.add(s)
    s.audio_analysis_enabled = body.audio_analysis_enabled
    s.audio_store_prefix = body.audio_store_prefix
    s.updated_at = now()
    return {"status": "ok"}


@router.get("/settings")
def get_settings(
    db: Session = Depends(session_dep), mem: Membership = Depends(current_membership)
) -> dict:
    s = db.scalar(select(TenantSettings))  # one row per schema
    if s is None:  # unset — the platform default (audio off) applies
        return {"audio_analysis_enabled": None, "audio_store_prefix": None}
    return {
        "audio_analysis_enabled": s.audio_analysis_enabled,
        "audio_store_prefix": s.audio_store_prefix,
    }
