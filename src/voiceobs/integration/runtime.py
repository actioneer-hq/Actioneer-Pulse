"""Execute a Pulse-wizard integration manifest: stored artifacts → canonical Trace → analysis.

The wizard (`register-integration`) stores one manifest per agent (schema `pulse.integration`):
storage path selectors, decoders, and JSONata mappers whose outputs are canonical fragments
(`call` | `trace` | `transcript`) plus audio emit rules. This runtime is the Pulse half of that
contract — it does what the mappers cannot:

  discover   — list the agent's storage, match objects against artifact selectors, group by call
  decode     — bytes → the mapper's declared input shape (json | text | records)
  map        — run each mapper (jsonata) under the `{_pulse, data}` envelope
  assemble   — merge fragments into ONE canonical Trace; transcript turns canonicalize to
               untimed STT/TTS spans with `sequence` (the span stays the single atom)
  persist    — `process_trace` (the same Calculator/persist tail live OTLP uses), gates
               self-ticked: a fully-read file is complete by definition.

Evidence is nullable and nothing is invented (CONTRACTS.md §5); the calculator degrades and the
trust report names what is missing.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import regex
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.core.model import CallHeader, Span, SpanEvent, Stage, Trace
from voiceobs.db.models import AgentIntegrationManifest, Call
from voiceobs.storage import fetch_bytes
from voiceobs.storage.config import ResolvedStorage
from voiceobs.util import safe_search

log = logging.getLogger(__name__)

_SPEAKER_STAGE = {"caller": (Stage.STT, "transcript"), "agent": (Stage.TTS, "llm_spoken")}


def resolve_manifest(db: Session, agent_id: str | None) -> tuple[dict, int] | None:
    """(manifest, version) for the agent, or None — absent means the mode can't run."""
    if not agent_id:
        return None
    row = db.scalar(
        select(AgentIntegrationManifest).where(AgentIntegrationManifest.agent_id == agent_id)
    )
    return (row.manifest, row.version) if row else None


def _manifest_rules(manifest: dict) -> list[tuple[dict, regex.Pattern, int]]:
    """Compile each artifact's path selector → (rule, regex, call_id capture group).

    Only `path_capture` correlation is executable today; mapper-derived multi-call correlation
    is logged and skipped, never silently dropped. Patterns are tenant-authored, so matching goes
    through `safe_search` (ReDoS timeout); they were also length-validated at register time."""
    rules: list[tuple[dict, regex.Pattern, int]] = []
    for rule in manifest.get("artifacts", []):
        pattern = (rule.get("selector") or {}).get("object_path_regex")
        corr = (rule.get("correlation") or {}).get("call_id") or {}
        if not pattern:
            continue
        if corr.get("from") != "path_capture":
            log.info("manifest artifact %s uses %s correlation — not yet executed, skipped",
                     rule.get("id"), corr.get("from"))
            continue
        rules.append((rule, regex.compile(pattern), int(corr.get("group", 1))))
    return rules


def discover_manifest(st: ResolvedStorage, manifest: dict) -> dict[str, list[tuple[dict, str]]]:
    """List the store and group objects by call_id → [(artifact_rule, uri), ...].

    Selectors are bucket-relative regexes from the manifest; call_id comes from the rule's
    `path_capture` correlation group."""
    objects = st.driver.list(st.descriptor, st.creds)
    base = f"{st.driver.scheme}://{st.descriptor['bucket']}/"
    rules = _manifest_rules(manifest)
    out: dict[str, list[tuple[dict, str]]] = {}
    for uri, _modified in objects:
        rel = uri.removeprefix(base)
        for rule, pattern, group in rules:
            m = safe_search(pattern, rel)
            if not m:
                continue
            call_id = m.group(group)
            if call_id:
                out.setdefault(call_id, []).append((rule, uri))
            break  # first matching rule wins, like the validator's path cases
    return out


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def discover_manifest_windowed(
    st: ResolvedStorage, manifest: dict, since: datetime | None, cutoff: datetime
) -> dict[str, tuple[list[tuple[dict, str]], datetime]]:
    """Poll variant of `discover_manifest` that keeps object modified-times.

    Groups ALL of a call's objects together (the mappers need every artifact of a call at once)
    and returns only calls whose newest object is settled and new since the watermark:
    `since < max_mtime <= cutoff`. Each value is `(items, max_mtime)`, so the caller can advance
    its watermark to the highest processed mtime."""
    objects = st.driver.list(st.descriptor, st.creds)
    base = f"{st.driver.scheme}://{st.descriptor['bucket']}/"
    rules = _manifest_rules(manifest)
    since = _aware(since) if since is not None else None  # DB round-trips can drop tzinfo
    grouped: dict[str, tuple[list[tuple[dict, str]], datetime]] = {}
    for uri, modified in objects:
        rel = uri.removeprefix(base)
        for rule, pattern, group in rules:
            m = safe_search(pattern, rel)
            if not m:
                continue
            call_id = m.group(group)
            if call_id:
                mt = _aware(modified)
                items, prev = grouped.get(call_id, ([], mt))
                items.append((rule, uri))
                grouped[call_id] = (items, max(prev, mt))
            break
    return {
        cid: (items, mx)
        for cid, (items, mx) in grouped.items()
        if mx <= cutoff and (since is None or mx > since)
    }


def decode_artifact(rule: dict, raw: bytes) -> object:
    """Bytes → the shape the mapper's `input` expects. Audio never reaches a mapper."""
    kind = (rule.get("decoder") or {}).get("type", "json")
    if kind == "json":
        return json.loads(raw)
    if kind == "text":
        encoding = (rule.get("decoder") or {}).get("encoding", "utf-8")
        return {"text": raw.decode(encoding, "replace")}
    if kind == "records":  # line-delimited JSON
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    raise ValueError(f"decoder {kind!r} is not mappable")


def run_mappers(
    manifest: dict, rule: dict, call_id: str, uri: str, data: object
) -> dict[str, object]:
    """Run every non-audio emit of one artifact → {mapper_output_target: fragment}."""
    import jsonata

    rel = uri.split("://", 1)[-1].split("/", 1)[-1] if "://" in uri else uri
    envelope = {"_pulse": {"call_id": call_id, "object_path": rel, "member_path": None},
                "data": data}
    fragments: dict[str, object] = {}
    for emit in rule.get("emits", []):
        if emit.get("target") == "audio":
            continue
        mapper = (manifest.get("mappers") or {}).get(emit.get("mapper")) or {}
        expr = mapper.get("expression")
        if not expr:
            continue
        result = jsonata.Jsonata(expr).evaluate(envelope)
        if result is not None:
            fragments[mapper.get("output", emit["mapper"])] = result
    return fragments


def assemble_trace(call_id: str, fragments: list[dict[str, object]]) -> Trace:
    """Merge one call's fragments into a single canonical Trace.

    call fragments merge into the header (first non-null value wins — the mapping plan's
    primary-source selection already de-duplicated); trace spans concatenate; transcript
    turns canonicalize to untimed STT/TTS spans carrying `sequence` — one atom."""
    header_fields: dict = {}
    spans: list[Span] = []
    span_seq = 0

    def _merge_header(d: dict) -> None:
        for k, v in d.items():
            if v is not None and header_fields.get(k) is None:
                header_fields[k] = v

    for frag in fragments:
        call_frag = frag.get("call")
        if isinstance(call_frag, dict):
            _merge_header(call_frag)
        trace_frag = frag.get("trace")
        if isinstance(trace_frag, dict):
            if isinstance(trace_frag.get("header"), dict):
                _merge_header(trace_frag["header"])
            for s in trace_frag.get("spans") or []:
                spans.append(Span(
                    span_id=str(s["span_id"]), parent_span_id=s.get("parent_span_id"),
                    name=str(s.get("name") or s["span_id"]),
                    stage=Stage(s.get("stage", "unknown")),
                    t_start=s.get("t_start"), t_end=s.get("t_end"),
                    sequence=s.get("sequence"), turn_id=s.get("turn_id"),
                    error=bool(s.get("error")), attrs=s.get("attrs") or {},
                    content=s.get("content") or {},
                    events=[SpanEvent(name=str(e["name"]), t=e.get("t"),
                                      attrs=e.get("attrs") or {},
                                      content=e.get("content") or {})
                            for e in s.get("events") or []],
                ))
        transcript = frag.get("transcript")
        if isinstance(transcript, dict):
            for t in transcript.get("turns") or []:
                stage, key = _SPEAKER_STAGE.get(t.get("speaker"), (Stage.UNKNOWN, "text"))
                attrs = {"speaker": t["speaker"]} if stage is Stage.UNKNOWN else {}
                spans.append(Span(
                    span_id=f"{call_id}-tr-{span_seq}", parent_span_id=None,
                    name="transcript.line", stage=stage,
                    t_start=t.get("t_start"), t_end=t.get("t_end"),
                    sequence=t.get("sequence"),
                    turn_id=t.get("turn_id") or f"{call_id}:t{t.get('sequence', span_seq)}",
                    attrs=attrs, content={key: t["text"]},
                ))
                span_seq += 1

    def _dt(v):
        try:
            return datetime.fromisoformat(str(v)) if v else None
        except ValueError:
            return None

    header = CallHeader(
        call_id=call_id,
        source=str(header_fields.get("source") or "files"),
        environment=str(header_fields.get("environment") or "prod"),
        started_at=_dt(header_fields.get("started_at")),
        ended_at=_dt(header_fields.get("ended_at")),
        engine=header_fields.get("engine"), carrier=header_fields.get("carrier"),
        stt_provider=header_fields.get("stt_provider"),
        llm_provider=header_fields.get("llm_provider"),
        llm_model=header_fields.get("llm_model"),
        tts_provider=header_fields.get("tts_provider"),
        voice=header_fields.get("voice"),
        template_sha256=header_fields.get("template_sha256"),
        labels=header_fields.get("labels") or {},
        counters=header_fields.get("counters") or {},
    )
    return Trace(header=header, spans=spans)


def process_manifest_call(
    db: Session,
    agent_id: str | None,
    call_id: str,
    items: list[tuple[dict, str]],
    creds: dict | None,
    manifest: dict,
    manifest_version: int = 0,
) -> str:
    """One call end-to-end: fetch → decode → map → assemble → gates → analyse. Returns the
    IngestRun status. Caller owns the transaction (same contract as process())."""
    from voiceobs.worker.backfill import _register_media
    from voiceobs.worker.process import ensure_audio_call, process_trace

    call: Call = ensure_audio_call(db, agent_id, call_id)
    call.source = call.source or "files"

    fragments: list[dict[str, object]] = []
    audio_kinds: dict[str, str] = {}
    for rule, uri in items:
        if (rule.get("decoder") or {}).get("type") == "audio":
            # emit config names the layout; the worker's channel detection covers the rest
            layout = next((e.get("config", {}).get("layout") for e in rule.get("emits", [])
                           if e.get("target") == "audio"), "stereo")
            kind = {"stereo": "audio", "mono": "audio",
                    "dual_mono": "audio_caller"}.get(layout, "audio")
            audio_kinds[kind] = uri
            continue
        raw = fetch_bytes(uri, creds)
        data = decode_artifact(rule, raw)
        fragments.append(run_mappers(manifest, rule, call_id, uri, data))

    if audio_kinds:
        _register_media(db, call, audio_kinds)

    trace = assemble_trace(call_id, fragments)
    # Self-ticking gates: a fully-read file IS complete — there is no stream to wait for.
    call.spans_complete = True
    if not audio_kinds:
        call.media_ready = call.media_ready or False
    db.flush()
    return process_trace(db, call, trace, adapter_version=manifest_version)
