"""File onboarding API: analyse a project's calls from files.

An upload is exactly one of:
- a **CSV of call parameters** (`call_id` + one column per script placeholder) + the audio ZIP — Pulse
  transcribes;
- a **JSON `pulse.calls.v1`** (per call: params + transcript, optional script) — no transcription; the
  audio ZIP is optional (only for playback), and without it every call needs its transcript.

Everything is checked before anything runs (script present, every call has its audio and a value
for every `{{placeholder}}`); any problem rejects the upload with the exact list. A valid upload is
stored in the DB (`upload_blob`: the manifest and each audio file) and queued as a `BackfillJob(source="upload")`; progress/cancel/SSE are the
backfill endpoints (/v1/backfill/{id}).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.agents import _org_agent, set_agent_script
from voiceobs.api.deps import now, session_dep
from voiceobs.auth import current_membership, require_role
from voiceobs.config import get_config
from voiceobs.db.models import Agent, AgentScript, BackfillJob, Membership, Prompt
from voiceobs.onboarding.format import (
    FORMAT_ID,
    ManifestError,
    UploadCall,
    UploadManifest,
    format_spec,
    parse_manifest,
    parse_params_csv,
    placeholders,
)
from voiceobs.onboarding.job import UploadError, audio_names, check_upload, extract_audio
from voiceobs.storage.drivers.local import put_blob

router = APIRouter(prefix="/v1")

_CHANNELS = ("auto", "left", "right")
_LANGUAGES = ("hi-IN", "en-IN", "unknown", "bn-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN",
              "ta-IN", "te-IN", "gu-IN")
_MAX_SIDE_FILE = 50 * 1024 * 1024  # CSV / JSON


def _active_script(db: Session, agent: Agent) -> str | None:
    return db.scalar(select(Prompt.text).join(AgentScript, AgentScript.prompt_id == Prompt.id)
                     .where(AgentScript.agent_id == agent.id, AgentScript.active.is_(True)))


@router.get("/uploads/format")
def upload_format(
    agent_id: str | None = None,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(current_membership),
) -> dict:
    """The CSV and JSON schemas for a project, derived from its script's {{placeholders}}."""
    script = _active_script(db, _org_agent(db, mem, agent_id)) if agent_id else None
    return format_spec(script)


def _read_small(f: UploadFile, what: str) -> bytes:
    raw = f.file.read(_MAX_SIDE_FILE + 1)
    if len(raw) > _MAX_SIDE_FILE:
        raise HTTPException(413, f"the {what} file is too large (50 MB max)")
    return raw


def _save(f: UploadFile, target: Path, budget: int) -> int:
    """Stream an upload to disk, refusing it past `budget` bytes. Returns bytes written."""
    written = 0
    with open(target, "wb") as out:
        while chunk := f.file.read(1 << 20):
            written += len(chunk)
            if written > budget:
                raise HTTPException(413, "upload is too large")
            out.write(chunk)
    return written


def _reject(errors: list[str], message: str = "the upload has problems") -> HTTPException:
    return HTTPException(422, {"message": message, "errors": errors[:30]})


@router.post("/agents/{agent_id}/uploads", status_code=201)
def create_upload(
    agent_id: str,
    audio: UploadFile | None = File(None, description="ZIP of call recordings (optional with a JSON)"),
    params_csv: UploadFile | None = File(None, description="CSV of call parameters (mode 1)"),
    manifest: UploadFile | None = File(None, description="pulse.calls.v1 JSON (mode 2)"),
    agent_channel: str = Form("auto"),
    language: str = Form("hi-IN"),
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    agent = _org_agent(db, mem, agent_id)
    if agent_channel not in _CHANNELS:
        raise HTTPException(422, f"agent_channel must be one of {', '.join(_CHANNELS)}")
    if language not in _LANGUAGES:
        raise HTTPException(422, "unsupported language")
    has_csv = params_csv is not None and bool(params_csv.filename)
    has_json = manifest is not None and bool(manifest.filename)
    if has_csv == has_json:
        raise HTTPException(422, "add the call parameters (CSV) or the transcripts (JSON) — exactly one")
    has_audio = audio is not None and bool(audio.filename)
    if has_csv and not has_audio:
        raise HTTPException(422, "a CSV upload needs the audio ZIP — Pulse transcribes the calls from it")

    # Parse the side file into one manifest shape (a CSV becomes params-only calls).
    try:
        if has_json:
            parsed = parse_manifest(_read_small(manifest, "JSON"))
        else:
            rows = parse_params_csv(_read_small(params_csv, "CSV"))
            parsed = UploadManifest(format=FORMAT_ID, calls=[
                UploadCall(call_id=cid, params=p) for cid, p in rows.items()])
    except ManifestError as e:
        kind = "JSON" if has_json else "CSV"
        raise _reject(e.errors, f"the {kind} file is not valid") from e

    script = parsed.script or _active_script(db, agent)
    if not script:
        raise HTTPException(422, "this project has no script — add it in the Script panel, "
                                 "or include `script` in the JSON")
    cfg = get_config()
    if not cfg.sarvam_api_key and any(not c.transcript for c in parsed.calls):
        raise HTTPException(400, "transcription is not configured (VOICEOBS_SARVAM_API_KEY); "
                                 "upload a JSON with transcripts instead")

    with tempfile.TemporaryDirectory(prefix="pulse-upload-") as tmp:
        staging = Path(tmp)
        size, names = 0, None
        if has_audio:
            size = _save(audio, staging / "calls.zip", cfg.max_upload_bytes)
            try:
                names = audio_names(staging / "calls.zip")
            except UploadError as e:
                raise HTTPException(422, str(e)) from e
        required = placeholders(script)
        errors = check_upload(names, parsed.calls, required)
        if errors:
            raise _reject(errors)

        if parsed.script:
            set_agent_script(db, agent, parsed.script, mem.user_id)  # becomes the project's next version
        agent.params_required = bool(required)  # judge waits for params whenever the script has them
        job = BackfillJob(org_id=mem.org_id, agent_id=agent.id, source="upload", status="queued",
                          created_at=now(), options={})
        db.add(job)
        db.flush()
        # The bytes go to the DB, not a disk: the worker and playback run as other services.
        prefix = f"{mem.org_id}/{agent.id}/{job.id}"
        put_blob(db, f"{prefix}/manifest.json", parsed.model_dump_json().encode())
        if has_audio:
            try:
                files = extract_audio(staging / "calls.zip", staging / "audio")
            except UploadError as e:
                raise HTTPException(422, str(e)) from e
            for name, path in files.items():
                put_blob(db, f"{prefix}/audio/{name}", path.read_bytes())
    job.options = {"prefix": prefix, "manifest": True, "bytes": size, "mode": "json" if has_json
                   else "csv", "agent_channel": agent_channel, "language": language,
                   "audio": has_audio, "audio_name": audio.filename if has_audio else None}
    return {"id": job.id, "status": job.status, "calls": len(parsed.calls),
            "params": required, "transcribe": sum(1 for c in parsed.calls if not c.transcript)}
