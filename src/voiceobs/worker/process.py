"""One call: fragments -> Trace -> Analysis -> rows."""

from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from voiceobs.adapters import UnsupportedSchema, adapter_for
from voiceobs.core import analyze_audio
from voiceobs.core.audio.decode import combine_stereo
from voiceobs.core.config import METRIC_VERSION, price_call
from voiceobs.core.join import join
from voiceobs.core.model import Analysis, AudioAnalysis, AudioRef, CallHeader, Stage, Trace
from voiceobs.db.models import (
    Call,
    Event,
    IngestRun,
    Media,
    Metric,
    RawFragment,
    TenantSettings,
    Utterance,
)
from voiceobs.db.models import Turn as DBTurn
from voiceobs.storage import fetch_bytes

log = logging.getLogger(__name__)

APP_VERSION = "0.0.1"

# core.Turn -> db.Turn where the names differ. Everything else maps by name.
_TURN_RENAMES = {
    "transcript": "caller_transcript",
    "audio_start_s": "caller_utt_end_s",
    "audio_out_start_s": "agent_utt_start_s",
}

# ponytail: one content kind per span row. `clauses` (per-sentence TTS) and `carried`
# are dropped here — join() already folds `carried` into the turn transcript. Give
# Event a kind+text child table if the viewer ever needs per-clause timing.
_PRIMARY_CONTENT = ("transcript", "llm_raw", "llm_spoken")


def assemble(payloads: list[bytes]) -> dict:
    """Gzipped fragments -> one OTLP payload.

    Deduped by spanId: OTLP retries resend spans, and a doubled root would be counted
    twice. Last write wins — a retry carries the more complete span."""
    resource: dict = {}
    spans: dict[str, dict] = {}
    for blob in payloads:
        for rs in json.loads(gzip.decompress(blob)).get("resourceSpans", []):
            resource = resource or rs.get("resource", {})
            for scope in rs.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    spans[span["spanId"]] = span
    return {"resourceSpans": [{"resource": resource,
                               "scopeSpans": [{"spans": list(spans.values())}]}]}


def process(db: Session, call: Call) -> str:
    """Analyse one call and persist the result. Returns the IngestRun status.

    Caller owns the transaction: everything here is one unit, so a crash halfway
    cannot leave a call half-analysed."""
    run = IngestRun(
        call_id=call.id, tenant_id=call.tenant_id, app_version=APP_VERSION,
        metric_version=METRIC_VERSION, status="running", started_at=_now(),
    )
    db.add(run)

    payloads = db.scalars(
        select(RawFragment.payload_gz)
        .where(RawFragment.call_id == call.id)
        .order_by(RawFragment.seq)
    ).all()
    payload = assemble(list(payloads))

    adapter = adapter_for(payload)
    if adapter is None:  # only reachable if the generic adapter is unregistered
        raise UnsupportedSchema("no adapter matched")
    trace = adapter.to_trace(payload)

    # Audio analysis is the opt-in overlay: OTLP is the engine's account, audio is our own
    # independent one. Off by default and per-tenant — when off we never fetch the WAV.
    audio_enabled = _audio_enabled(db, call.tenant_id)
    audio = _load_audio(db, call) if audio_enabled else None
    analysis = join(
        trace, audio, t0_offset_s=call.audio_t0_offset_s, audio_enabled=audio_enabled
    )

    _persist(db, call, trace, analysis, adapter.version, audio)

    reasons = [r.value for r in analysis.trust.reasons]
    run.status = "partial" if reasons else "ok"
    run.error = ", ".join(reasons) or None
    run.finished_at = _now()
    return run.status


def _env_default() -> bool:
    return os.getenv("VOICEOBS_AUDIO_ANALYSIS", "0").strip().lower() in ("1", "true", "on", "yes")


def _audio_enabled(db: Session, tenant_id: str) -> bool:
    """Is the audio overlay on for this tenant? Per-tenant setting wins; a null (unset)
    setting falls back to the global VOICEOBS_AUDIO_ANALYSIS default (off)."""
    s = db.scalar(select(TenantSettings).where(TenantSettings.tenant_id == tenant_id))
    if s is not None and s.audio_analysis_enabled is not None:
        return s.audio_analysis_enabled
    return _env_default()


def _load_audio(db: Session, call: Call) -> AudioAnalysis | None:
    """Fetch the audio and run Layer 1. Accepts either one stereo `audio` artifact or
    two mono ones (`audio_caller` + `audio_agent`, e.g. LiveKit track egress), which we
    combine into a caller/agent stereo stream. None if no audio was registered."""
    kinds = {m.kind: m for m in db.scalars(select(Media).where(Media.call_id == call.id))}
    wav, sr = _audio_bytes(kinds)
    if wav is None:
        return None
    ref = AudioRef(
        uri="", sha256="", channels=2, sample_rate=sr,
        duration_s=call.duration_s or 0.0,
        channel_map={int(k): v for k, v in (call.channel_map or {"0": "caller", "1": "agent"}).items()},
        t0_offset_s=call.audio_t0_offset_s,
    )
    return analyze_audio(wav, ref)


def _audio_bytes(kinds: dict[str, Media]) -> tuple[bytes | None, int]:
    stereo = kinds.get("audio")
    if stereo is not None and stereo.uri:
        return fetch_bytes(stereo.uri), stereo.sample_rate or 8000
    caller, agent = kinds.get("audio_caller"), kinds.get("audio_agent")
    if caller and caller.uri and agent and agent.uri:
        return combine_stereo(fetch_bytes(caller.uri), fetch_bytes(agent.uri)), \
            caller.sample_rate or 8000
    return None, 8000


def _persist(
    db: Session, call: Call, trace: Trace, analysis: Analysis, adapter_version: int,
    audio: AudioAnalysis | None,
) -> None:
    # Delete-then-insert: reprocessing must not double rows, and the unique
    # constraints on turn/metric would reject the second run otherwise.
    for model in (DBTurn, Metric, Event, Utterance):
        db.execute(delete(model).where(model.call_id == call.id))
    db.execute(delete(Media).where(Media.call_id == call.id, Media.kind.like("peaks_%")))

    _apply_header(call, trace.header)
    _rollup(call, trace, analysis)
    call.unattributed_spans = sum(
        1 for s in trace.spans
        if s.turn_id is None and s.parent_span_id is not None and s.stage is not Stage.CALL
    )
    # 0 once analysed (a known "none dropped"), not null — null reads as "unknown".
    call.span_dropped_events = analysis.trust.span_dropped_events
    call.metric_version = analysis.metric_version
    call.adapter_version = adapter_version
    call.app_version = APP_VERSION

    db.add_all(
        [_turn_row(t, call, analysis.metric_version) for t in analysis.turns]
        + [_metric_row(m, call, analysis.metric_version) for m in analysis.metrics]
        + list(_event_rows(trace, call))
    )
    if audio is not None:
        db.add_all(_utterance_rows(audio, call, analysis.metric_version))
        db.add_all(_peaks_rows(audio, call))


def _rollup(call: Call, trace: Trace, analysis: Analysis) -> None:
    """Call-level facts the OTLP already carries per span/turn: which models ran, and the
    token totals. The header has the call's identity; this is its composition. Left null
    when the producer never said (LiveKit, e.g., names no STT model) — never guessed."""
    spans = trace.spans

    def model(stage: Stage) -> str | None:
        return next(
            (s.attrs.get("gen_ai.request.model") for s in spans
             if s.stage is stage and s.attrs.get("gen_ai.request.model")),
            None,
        )

    stages = {s.stage for s in spans}
    # STT: LiveKit names the transcription model on the user-turn span (with the transcript
    # and confidence), not on the endpointing STT span — so fall back to the turn span.
    call.stt_provider = model(Stage.STT) or model(Stage.TURN) or call.stt_provider
    call.llm_provider = model(Stage.LLM) or call.llm_provider
    call.tts_provider = model(Stage.TTS) or call.tts_provider
    if call.engine is None and Stage.LLM in stages:
        # distinct STT/LLM/TTS spans => a cascade; a single realtime span => s2s.
        call.engine = "cascade" if {Stage.STT, Stage.TTS} & stages else "s2s"

    def total(attr: str) -> int | None:
        return sum(getattr(t, attr) or 0 for t in analysis.turns) or None

    call.tokens_in = total("tokens_in")
    call.tokens_out = total("tokens_out")
    call.tokens_cached = total("tokens_cached")
    call.tts_chars = total("tts_chars")

    # cost from the configured per-model pricing (MODEL_PRICING). Stays null for any
    # model with no registered price — a call is never billed on a guess.
    cost = price_call(
        llm_model=call.llm_provider, stt_model=call.stt_provider, tts_model=call.tts_provider,
        tokens_in=call.tokens_in, tokens_out=call.tokens_out, tokens_cached=call.tokens_cached,
        tts_chars=call.tts_chars, stt_seconds=call.stt_seconds,
    )
    call.cost_llm, call.cost_stt, call.cost_tts = cost.llm, cost.stt, cost.tts
    call.cost_total = cost.total
    call.cost_currency = cost.currency if cost.total is not None else None


def _utterance_rows(audio: AudioAnalysis, call: Call, metric_version: int):
    return [
        Utterance(
            call_id=call.id, tenant_id=call.tenant_id, channel=u.channel,
            t_start_s=u.t_start, t_end_s=u.t_end, metric_version=metric_version,
        )
        for u in audio.utterances
    ]


def _peaks_rows(audio: AudioAnalysis, call: Call):
    return [
        Media(call_id=call.id, tenant_id=call.tenant_id, kind=f"peaks_{channel}", peaks=data)
        for channel, data in audio.peaks.items()
    ]


def _cols(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


def _apply_header(call: Call, h: CallHeader) -> None:
    """Copy the adapter's view onto the row. Identity columns are ingest's, not ours:
    renaming a call here would orphan every artifact already posted against it."""
    fields = h.model_dump() | (h.counters or {})
    fields.pop("labels", None)
    for name in _cols(Call) & set(fields):
        if name not in ("id", "tenant_id", "source", "environment"):
            setattr(call, name, fields[name])
    call.labels = h.labels or {}
    call.campaign_id = (h.labels or {}).get("campaign_id")
    if h.started_at and h.ended_at:
        call.duration_s = round((h.ended_at - h.started_at).total_seconds(), 3)


def _turn_row(turn, call: Call, metric_version: int) -> DBTurn:
    d = {_TURN_RENAMES.get(k, k): v for k, v in turn.model_dump().items()}
    return DBTurn(
        call_id=call.id, tenant_id=call.tenant_id, metric_version=metric_version,
        **{k: v for k, v in d.items() if k in _cols(DBTurn)},
    )


def _metric_row(m, call: Call, metric_version: int) -> Metric:
    return Metric(
        call_id=call.id, tenant_id=call.tenant_id, name=m.name,
        value_num=m.value if isinstance(m.value, int | float) else None,
        value_text=m.value if isinstance(m.value, str) else None,
        samples=m.samples, available=m.available, reason=m.reason,
        metric_version=metric_version,
    )


def _event_rows(trace: Trace, call: Call):
    """One row per span, plus one per span event — the timeline the viewer scrubs."""
    for s in trace.spans:
        kind = next((k for k in _PRIMARY_CONTENT if s.content.get(k)), None)
        yield Event(
            call_id=call.id, tenant_id=call.tenant_id, span_id=s.span_id,
            parent_span_id=s.parent_span_id, turn_id=s.turn_id, t_offset_s=s.t_start,
            kind="span", type=s.stage.value, name=s.name, attrs=s.attrs,
            duration_s=None if s.t_end is None else round(s.t_end - s.t_start, 6),
            content_text=s.content.get(kind) if kind else None, content_kind=kind,
        )
        for e in s.events:
            ekind = next(iter(e.content), None)
            yield Event(
                call_id=call.id, tenant_id=call.tenant_id, span_id=s.span_id,
                parent_span_id=s.parent_span_id, turn_id=s.turn_id, t_offset_s=e.t,
                kind="event", type=e.name[:48], name=e.name, attrs=e.attrs,
                content_text=_text(e.content.get(ekind)) if ekind else None,
                content_kind=ekind,
            )


def _text(v) -> str | None:
    """Content is usually a string; a producer may send a list (clause splits)."""
    return " ".join(map(str, v)) if isinstance(v, list) else v


def _now() -> datetime:
    return datetime.now(UTC)
