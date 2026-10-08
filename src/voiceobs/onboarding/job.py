"""Run an upload job: ZIP of call audio (+ optional pulse.calls.v1 JSON), or a JSON with transcripts and
no audio -> analysed calls.

Per call: register the audio (upload:// Media), take the transcript from the JSON or produce one
with Sarvam STT, store the prompt parameters, build a Trace and run the shared analysis, then
enqueue the judge when the customer spoke. Driven by the backfill worker (`source="upload"`), so
progress, cancel and the SSE stream are the backfill ones. Per-call failures are counted and
recorded on the job; they never abort it.
"""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.config import get_config
from voiceobs.db.models import Agent, BackfillJob, Call, CallParams, Media
from voiceobs.db.purge import purge_calls
from voiceobs.ingestion import _active_script_prompt
from voiceobs.onboarding.format import ManifestError, UploadCall, Utterance, parse_manifest
from voiceobs.onboarding.stt import (
    SttConfig,
    is_stereo_wav,
    read_wav,
    transcribe_batch,
    transcribe_stereo,
)
from voiceobs.onboarding.trace import build_trace, customer_spoke
from voiceobs.storage.drivers.local import uri_for
from voiceobs.worker.process import ensure_audio_call, process_trace

log = logging.getLogger(__name__)

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".webm", ".amr", ".mp4", ".wma"}
CONTENT_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
                 ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac", ".webm": "audio/webm",
                 ".aac": "audio/aac", ".amr": "audio/amr", ".wma": "audio/x-ms-wma"}


class UploadError(ValueError):
    pass


@dataclass
class PlannedCall:
    call_id: str
    audio: Path | None = None
    spec: UploadCall | None = None
    utterances: list[Utterance] | None = None
    error: str | None = None
    meta: dict = field(default_factory=dict)


def _is_audio(info: zipfile.ZipInfo) -> str | None:
    """The member's flattened file name if it is an audio file worth importing, else None."""
    name = PurePosixPath(info.filename.replace("\\", "/")).name
    if (info.is_dir() or not name or name.startswith(".") or "__MACOSX" in info.filename
            or Path(name).suffix.lower() not in AUDIO_EXTS):
        return None
    return name


def audio_names(zip_path: Path) -> list[str]:
    """Audio file names in the ZIP (flattened, de-duplicated) without extracting anything."""
    if not zipfile.is_zipfile(zip_path):
        raise UploadError("the audio upload is not a valid ZIP file")
    with zipfile.ZipFile(zip_path) as zf:
        names = list(dict.fromkeys(n for i in zf.infolist() if (n := _is_audio(i))))
    if not names:
        raise UploadError("the ZIP contains no audio files (.wav, .mp3, .m4a, …)")
    if len(names) > get_config().max_upload_files:
        raise UploadError("the ZIP has too many audio files")
    return names


def check_upload(names: list[str] | None, calls: list[UploadCall], required: list[str]) -> list[str]:
    """Everything wrong with an upload before it runs: calls with no audio, audio with no row,
    and calls missing a value for a script placeholder. `names` None = no audio ZIP (a JSON with
    transcripts): then every call needs its transcript. Empty list = good to go."""
    def ids(xs: list[str]) -> str:
        return ", ".join(xs[:8]) + (f" … (+{len(xs) - 8})" if len(xs) > 8 else "")

    if names is None:
        errors = [f"{len(v)} call(s) missing `{p}`: {ids(v)}" for p, v in _missing_params(calls, required).items()]
        no_text = [c.call_id for c in calls if not c.transcript]
        if no_text:
            errors.append(f"{len(no_text)} call(s) have no transcript (add it, or upload the audio ZIP): "
                          f"{ids(no_text)}")
        return errors
    audio = set(names)
    by_stem = {Path(n).stem: n for n in names}
    used: set[str] = set()
    no_audio: list[str] = []
    missing: dict[str, list[str]] = {}
    for c in calls:
        name = c.audio_file if c.audio_file in audio else by_stem.get(c.call_id)
        if name:
            used.add(name)
        else:
            no_audio.append(c.call_id)
        for p in required:
            if c.params.get(p) in (None, ""):
                missing.setdefault(p, []).append(c.call_id)
    errors = [f"{len(v)} call(s) missing `{p}`: {ids(v)}" for p, v in missing.items()]
    if no_audio:
        errors.append(f"{len(no_audio)} row(s) have no audio file in the ZIP: {ids(no_audio)}")
    orphan = sorted(n for n in names if n not in used)
    if orphan:
        errors.append(f"{len(orphan)} audio file(s) have no row in the CSV/JSON: {ids(orphan)}")
    return errors


def _missing_params(calls: list[UploadCall], required: list[str]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for c in calls:
        for p in required:
            if c.params.get(p) in (None, ""):
                missing.setdefault(p, []).append(c.call_id)
    return missing


def extract_audio(zip_path: Path, dest: Path) -> dict[str, Path]:
    """Safely extract audio files from the ZIP, flattened to their base names -> {name: path}.
    Skips folders, macOS metadata and non-audio files; refuses oversized or over-full archives."""
    cfg = get_config()
    if not zipfile.is_zipfile(zip_path):
        raise UploadError("the audio upload is not a valid ZIP file")
    dest.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    total = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = _is_audio(info)
            if name is None:
                continue
            if name in out:
                continue  # same file name in two folders — first one wins
            total += info.file_size
            if total > cfg.max_upload_bytes * 4 or len(out) >= cfg.max_upload_files:
                raise UploadError("the ZIP is too large or has too many audio files")
            target = dest / name
            with zf.open(info) as src, open(target, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            out[name] = target
    if not out:
        raise UploadError("the ZIP contains no audio files (.wav, .mp3, .m4a, …)")
    return out


def plan_calls(audio: dict[str, Path], manifest_calls: list[UploadCall]) -> list[PlannedCall]:
    """Pair JSON entries with audio files (by `audio_file`, else by `<call_id>.<ext>`); audio
    files with no JSON entry become calls named after the file."""
    by_stem = {Path(n).stem: n for n in audio}
    used: set[str] = set()
    plans: list[PlannedCall] = []
    for c in manifest_calls:
        name = c.audio_file if c.audio_file in audio else by_stem.get(c.call_id)
        p = PlannedCall(call_id=c.call_id, spec=c, audio=audio.get(name) if name else None)
        if name:
            used.add(name)
        elif c.audio_file:
            p.error = f"audio_file '{c.audio_file}' is not in the ZIP"
        if p.audio is None and not c.transcript and not p.error:
            p.error = "no audio file and no transcript for this call"
        plans.append(p)
    known = {c.call_id for c in manifest_calls}
    for name, path in sorted(audio.items()):
        stem = Path(name).stem
        if name not in used and stem not in known:
            plans.append(PlannedCall(call_id=stem[:128], audio=path))
    return plans


def run_upload(db: Session, job: BackfillJob, org: str,
               enqueue: Callable[[str], None], is_cancelled: Callable[[], bool]) -> None:
    from voiceobs.worker.backfill import _finish, _now  # shared job bookkeeping

    opts = job.options or {}
    job_dir = Path(opts["dir"])
    try:
        # no ZIP = a JSON upload with transcripts only (no playback)
        audio = extract_audio(job_dir / "calls.zip", job_dir / "audio") if opts.get("audio", True) else {}
        manifest = None
        if opts.get("manifest"):
            manifest = parse_manifest((job_dir / "manifest.json").read_bytes())
    except (UploadError, ManifestError, OSError) as e:
        _finish(db, job, status="failed", error=str(e))
        return

    plans = plan_calls(audio, manifest.calls if manifest else [])
    job.total = len(plans)
    job.status, job.phase, job.updated_at = "running", "transcribing", _now()
    db.commit()

    cfg = get_config()
    stt = SttConfig(api_key=cfg.sarvam_api_key or "", model=cfg.sarvam_stt_model,
                    language=opts.get("language") or "hi-IN",
                    agent_channel=opts.get("agent_channel") or "auto",
                    concurrency=cfg.sarvam_stt_concurrency)
    _transcribe_non_stereo(stt, plans)

    job.phase = "analyzing"
    db.commit()
    script_prompt = _active_script_prompt(db, job.agent_id) if job.agent_id else None
    for plan in plans:
        if is_cancelled():
            _finish(db, job, status="cancelled")
            return
        judge = False
        try:
            judge = _analyse(db, job.agent_id, plan, stt, script_prompt)
            job.completed += 1
        except Exception as e:  # noqa: BLE001 — one call never aborts the job
            db.rollback()
            log.warning("upload call %s failed: %s", plan.call_id, e)
            job.failed += 1
            job.error = job.error or f"{plan.call_id}: {e}"
        job.updated_at = _now()
        db.commit()
        if judge:
            enqueue(plan.call_id)


def _needs_stt(p: PlannedCall) -> bool:
    return p.error is None and not (p.spec and p.spec.transcript) and p.audio is not None


def _transcribe_non_stereo(stt: SttConfig, plans: list[PlannedCall]) -> None:
    """Batch-transcribe (diarized) every call that needs STT and is not a stereo WAV."""
    todo = [p for p in plans if _needs_stt(p) and not is_stereo_wav(p.audio.read_bytes())]
    if not todo:
        return
    if not stt.api_key:
        for p in todo:
            p.error = "STT is not configured (VOICEOBS_SARVAM_API_KEY)"
        return
    res = transcribe_batch(stt, [p.audio for p in todo])
    for p in todo:
        r = res.get(p.audio.name, "no transcript returned")
        if isinstance(r, str):
            p.error = r
        else:
            p.utterances = r


def _analyse(db: Session, agent_id: str | None, plan: PlannedCall, stt: SttConfig,
             script_prompt: str | None) -> bool:
    """Persist + analyse one call. Returns True when it should be judged."""
    if plan.error:
        raise UploadError(plan.error)
    existing = db.scalar(select(Call).where(Call.external_call_id == plan.call_id))
    if existing is not None and existing.agent_id != agent_id:
        if existing.agent_id and db.get(Agent, existing.agent_id) is not None:
            raise UploadError("this call_id already belongs to another project")
        purge_calls(db, [existing.id])  # left behind by a deleted project: reclaim the id
        db.flush()

    data = plan.audio.read_bytes() if plan.audio else None
    wav = read_wav(data) if data else None
    utterances = plan.spec.transcript if plan.spec and plan.spec.transcript else plan.utterances
    if utterances is None:  # stereo WAV that still needs STT
        if not stt.api_key:
            raise UploadError("STT is not configured (VOICEOBS_SARVAM_API_KEY)")
        if wav is None or wav[0].shape[1] != 2:
            raise UploadError("could not transcribe this audio")
        utterances = transcribe_stereo(stt, *wav)

    call = ensure_audio_call(db, agent_id, plan.call_id)
    call.source = "upload"
    call.analysis_mode = "transcript"
    call.spans_complete = True
    if script_prompt:
        call.prompt_id = script_prompt
    duration = (len(wav[0]) / wav[1]) if wav else None
    if plan.audio is not None:
        _register_audio(db, call, plan.audio, data, wav)
    if plan.spec and plan.spec.params:
        _upsert_params(db, agent_id, plan.call_id, plan.spec.params)
    trace = build_trace(plan.call_id, utterances or [],
                        started_at=plan.spec.started_at if plan.spec else None,
                        duration_s=duration, labels={"upload": "1"})
    process_trace(db, call, trace, adapter_version=0)
    last = max((u.end or u.start for u in utterances or []), default=None)
    call.duration_s = round(duration, 3) if duration else (round(last, 3) if last else None)
    if plan.spec and plan.spec.started_at:
        call.started_at = plan.spec.started_at
    call.status = "computed"
    return customer_spoke(utterances or [])


def _register_audio(db: Session, call: Call, path: Path, data: bytes, wav) -> None:
    uri = uri_for(path)
    m = db.scalar(select(Media).where(Media.call_id == call.id, Media.kind == "audio"))
    if m is None:
        m = Media(call_id=call.id, kind="audio", uri=uri)
        db.add(m)
    m.uri = uri
    m.bytes = len(data)
    m.content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
    if wav is not None:
        m.channels, m.sample_rate = wav[0].shape[1], wav[1]
    call.media_ready = True
    db.flush()


def _upsert_params(db: Session, agent_id: str | None, call_id: str, params: dict) -> None:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    row = db.scalar(select(CallParams).where(CallParams.agent_id == agent_id,
                                            CallParams.call_key == call_id))
    if row is None:
        db.add(CallParams(agent_id=agent_id, call_key=call_id, params=clean))
    else:
        row.params = clean
