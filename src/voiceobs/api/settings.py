"""Per-tenant platform settings — currently the audio-analysis toggle (off by default)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import now, session_dep
from voiceobs.api.schemas import SettingsIn
from voiceobs.db.models import TenantSettings

router = APIRouter(prefix="/v1")


@router.post("/settings")
def set_settings(
    body: SettingsIn,
    db: Session = Depends(session_dep),
    tenant: str = Header("default", alias="X-Voiceobs-Tenant"),
) -> dict:
    s = db.scalar(select(TenantSettings).where(TenantSettings.tenant_id == tenant))
    if s is None:
        s = TenantSettings(tenant_id=tenant)
        db.add(s)
    s.audio_analysis_enabled = body.audio_analysis_enabled
    s.audio_store_prefix = body.audio_store_prefix
    s.updated_at = now()
    return {"status": "ok"}


@router.get("/settings")
def get_settings(
    db: Session = Depends(session_dep),
    tenant: str = Header("default", alias="X-Voiceobs-Tenant"),
) -> dict:
    s = db.scalar(select(TenantSettings).where(TenantSettings.tenant_id == tenant))
    if s is None:  # unset — the platform default (audio off) applies
        return {"audio_analysis_enabled": None, "audio_store_prefix": None}
    return {
        "audio_analysis_enabled": s.audio_analysis_enabled,
        "audio_store_prefix": s.audio_store_prefix,
    }
