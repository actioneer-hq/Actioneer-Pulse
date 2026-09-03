"""Layer 2 — join spans to audio on one clock, compute the per-turn waterfall.

Reads VO's canonical attribute names only (`turn.index`, `stt.language`, …), never a
producer's. Adapters map their dialect onto them — see `adapters/generic.py`.

Anchoring: spans are on the call clock, utterances on the audio clock;
audio_time = call_time - t0_offset_s places spans onto audio. t0_offset_s lives
on AudioRef, so it is passed as a kwarg (None = already co-clocked).

Degradation is first-class — nothing hard-fails; every gap is a TrustReason.
"""

from __future__ import annotations

from voiceobs.core.audio import intervals as iv
from voiceobs.core.audio.metrics import (
    barge_in_count,
    caller_turn_stats,
    dead_air_s,
    percentile,
    talk_ratio,
)
from voiceobs.core.config import METRIC_VERSION, MetricConfig
from voiceobs.core.model import (
    Analysis,
    AudioAnalysis,
    MetricValue,
    Span,
    Stage,
    Trace,
    TrustReason,
    TrustReport,
    Turn,
    Utterance,
)

ADAPTER_VERSION = 1


def join(
    trace: Trace,
    audio: AudioAnalysis | None,
    cfg: MetricConfig | None = None,
    t0_offset_s: float | None = None,
    audio_enabled: bool = True,
) -> Analysis:
    """Join spans to audio and compute turns, metrics, and the trust report.

    `audio_enabled` distinguishes "audio overlay is off for this tenant" (a choice) from
    "audio never arrived" (an outage) in the trust report — the numbers are identical, the
    reason is not."""
    cfg = cfg or MetricConfig()
    offset = t0_offset_s or 0.0

    turn_spans = _turn_spans(trace.spans)
    has_spans = bool(trace.spans)

    utterances = audio.utterances if audio else []

    turns = [
        _build_turn(ts, trace.spans, utterances, offset, position)
        for position, ts in enumerate(turn_spans)
    ]

    agent_iv = _agent_intervals(trace, offset)  # agent-side truth: spans, not VAD

    metrics: list[MetricValue] = []
    if audio is not None:
        metrics.extend(_audio_metrics(audio, agent_iv, cfg))
    if has_spans and turn_spans:
        metrics.extend(_layer2_metrics(turns))

    trust = _trust_report(trace, audio, turns, offset, cfg, audio_enabled)

    return Analysis(
        turns=turns,
        metrics=metrics,
        trust=trust,
        metric_version=METRIC_VERSION,
        adapter_version=ADAPTER_VERSION,
    )


def _turn_spans(spans: list[Span]) -> list[Span]:
    """One turn span per exchange. A producer may emit several TURN-stage spans for the
    same exchange (LiveKit's user_turn + agent_turn); they share a turn_id once paired.
    Keep the caller-side one — the TURN span that parents an STT/SPEECH span — so the turn
    is anchored on the caller, and the others still render, just not as separate turns."""
    caller_side = {
        s.parent_span_id for s in spans if s.stage in (Stage.STT, Stage.SPEECH)
    }
    best: dict[str, Span] = {}
    for s in (t for t in spans if t.stage is Stage.TURN):
        key = s.turn_id or s.span_id
        cur = best.get(key)
        primary = s.span_id in caller_side
        if (
            cur is None
            or (primary and cur.span_id not in caller_side)
            or (primary == (cur.span_id in caller_side) and s.t_start < cur.t_start)
        ):
            best[key] = s
    return sorted(best.values(), key=lambda s: (_turn_index(s), s.t_start))


def _turn_index(span: Span, default: int = 10**9) -> int:
    """The producer's turn.index, or `default`. Producers that don't emit it (Pipecat,
    LiveKit) fall back to positional order so turns don't all collide on one index."""
    v = span.attrs.get("turn.index")
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _children(spans: list[Span], turn_id: str | None, stage: Stage) -> list[Span]:
    return [s for s in spans if s.turn_id == turn_id and s.stage is stage]


def _first_event_t(spans: list[Span], name: str, turn_id: str | None) -> float | None:
    """Earliest `name` event for this turn. Producers park call-scoped events on the
    root span, which has no turn_id — those name the turn in their own attrs instead,
    so match on either or the whole root timeline is invisible."""
    ts = [
        e.t
        for s in spans
        for e in s.events
        if e.name == name
        and (s.turn_id == turn_id or e.attrs.get("turn.id") == turn_id)
    ]
    return min(ts) if ts else None


def _to_audio(call_t: float | None, offset: float) -> float | None:
    return None if call_t is None else round(call_t - offset, 4)


def _agent_intervals(trace: Trace, offset: float) -> list[iv.Interval]:
    """When the agent was speaking, from spans — the agent-side source of truth.

    Union of TTS/PLAYOUT span windows on the audio clock. Empty when a call has no
    spans (trace_missing) → agent-side metrics then read unavailable, never guessed."""
    windows = [
        (_to_audio(s.t_start, offset), _to_audio(s.t_end, offset))
        for s in trace.spans
        if s.stage in (Stage.TTS, Stage.PLAYOUT) and s.t_end is not None
    ]
    return iv.merge([(a, b) for a, b in windows if a is not None and b is not None])


def _uncovered(
    caller_stop: float | None,
    agent_out: float | None,
    speech_end: float | None,
    stt_start: float | None,
    spans: list[Span],
    offset: float,
) -> float | None:
    """Milliseconds inside [caller_stop, agent_out] that no span (nor the endpointing hold)
    covered — the genuinely unexplained gap. Overlap-safe: it unions the intervals, so
    stages that run concurrently in a streaming pipeline are counted once, never negative."""
    if caller_stop is None or agent_out is None or agent_out <= caller_stop:
        return None
    lo, hi = caller_stop, agent_out
    segs: list[iv.Interval] = []
    if speech_end is not None and stt_start is not None:  # the endpointing hold (no span)
        segs.append((speech_end, stt_start))
    for s in spans:
        a, b = _to_audio(s.t_start, offset), _to_audio(s.t_end, offset)
        if a is not None and b is not None:
            segs.append((a, b))
    clipped = [(max(lo, a), min(hi, b)) for a, b in segs if min(hi, b) > max(lo, a)]
    covered = iv.total(iv.merge(clipped))
    return round(max(0.0, (hi - lo) - covered) * 1000.0, 1)


def _build_turn(
    turn_span: Span, spans: list[Span], utterances: list[Utterance], offset: float,
    position: int = 0,
) -> Turn:
    tid = turn_span.turn_id or f"{turn_span.span_id}"
    trigger = str(turn_span.attrs.get("turn.trigger", "endpoint"))

    speech = _children(spans, tid, Stage.SPEECH)
    stt = _children(spans, tid, Stage.STT)
    llm = _children(spans, tid, Stage.LLM)
    tts = _children(spans, tid, Stage.TTS)
    # Every span of this exchange. LiveKit parks interruption/endpointing/confidence and
    # the PII transcript on the turn spans (user_turn/agent_turn), not on the stage spans,
    # so stage-scoped reads miss them — search the whole exchange for those.
    related = [s for s in spans if s.turn_id == tid]

    # The caller stopped talking here — the last end across their speech segments (a turn
    # may hold several). This is the real instant; the gap to STT IS the endpointing hold.
    speech_ends = [s.t_end for s in speech if s.t_end is not None]
    speech_end = _to_audio(max(speech_ends), offset) if speech_ends else None
    stt_start = _to_audio(stt[0].t_start, offset) if stt else None
    stt_final = _to_audio(stt[0].t_end, offset) if stt else None
    llm_start = llm[0].t_start if llm else None
    llm_first_token = _to_audio(_first_event_t(spans, "llm.first_token", tid), offset)
    # TTS "start" = the earliest TTS span opening (the pipeline node accepts text, ~first
    # token). The provider *request* is the sub-span that carries the synthesis metrics
    # (characters count) — it fires a little later; the gap between them is the dispatch.
    tts_starts = [s.t_start for s in tts]
    tts_start = _to_audio(min(tts_starts), offset) if tts_starts else None
    tts_req_starts = [s.t_start for s in tts if s.attrs.get("tts.chars") is not None]
    tts_req_start = _to_audio(min(tts_req_starts), offset) if tts_req_starts else None
    tts_first_audio = _to_audio(_first_event_t(spans, "tts.first_audio", tid), offset)
    committed = _to_audio(_first_event_t(spans, "turn.committed", tid), offset)
    if committed is None:  # fall back to the turn span start
        committed = _to_audio(turn_span.t_start, offset)

    # caller side comes from the isolated caller channel (VAD); agent onset (VAD) is
    # kept only for the clock-residual trust check, never for the latency numbers.
    win_start = _to_audio(turn_span.t_start, offset) or 0.0
    win_end = _to_audio(turn_span.t_end, offset)
    caller_end, agent_vad_start = _audio_endpoints(utterances, win_start, win_end)

    # the waterfall pieces (ms). endpointing is the silence hold — how long we waited to
    # be sure the caller had finished. See docs/vas-telemetry-semantics.md §3.
    stt_lag = _ms(stt_start, stt_final)
    # producer-reported latency (seconds -> ms): LiveKit hands ttft/ttfb as span
    # attributes instead of first-token/first-audio events. Store them, and bridge them
    # into the waterfall when the event is absent, so the timeline reads complete from
    # OTLP alone. `*_reported_ms` keeps the provenance.
    llm_ttft_reported = _sec_to_ms(_attr(llm, "metrics.ttft"))
    tts_ttfb_reported = _sec_to_ms(_attr(tts, "metrics.ttfb"))
    endpointing = _ms(speech_end, stt_start)
    if endpointing is None:  # LiveKit reports the endpointing hold as an attribute
        endpointing = _sec_to_ms(_attr(related, "endpointing.delay"))
    llm_ttft = _ms(_to_audio(llm_start, offset), llm_first_token)
    if llm_ttft is None:
        llm_ttft = llm_ttft_reported
    tts_ttfb = _ms(tts_start, tts_first_audio)
    if tts_ttfb is None:
        tts_ttfb = tts_ttfb_reported

    # assembly = first token -> TTS start. When the first-token event is absent, place it
    # at llm_start + reported ttft (the same first token, reconstructed), so the column
    # fills instead of dashing out.
    first_token = llm_first_token
    if first_token is None and llm_start is not None and llm_ttft_reported is not None:
        first_token = round(_to_audio(llm_start, offset) + llm_ttft_reported / 1000.0, 4)
    assembly = _ms(first_token, tts_start)          # first token -> TTS node opens (~0)
    dispatch = _ms(first_token, tts_req_start)      # first token -> provider request fires

    # v2v runs the caller's end of speech -> first agent audio, and MUST share the pieces'
    # anchors or the residual goes negative. Both anchors can be missing as events, so:
    #   start: the caller's real end of speech (SPEECH span), not the STT-final fallback.
    #   end:   first audio = tts start + reported ttfb, when no first-audio event exists.
    caller_stop = speech_end if speech_end is not None else stt_final
    if tts_first_audio is not None:
        agent_out = tts_first_audio
    elif tts_start is not None and tts_ttfb is not None:
        agent_out = round(tts_start + tts_ttfb / 1000.0, 4)
    else:
        agent_out = tts_start

    # playout = sent -> heard (span vs caller-recording); the network tail, reported
    # but not summed into response_latency, which ends when the engine sent audio.
    playout = _ms(tts_first_audio, agent_vad_start)
    response_latency = _ms(caller_stop, agent_out)

    interrupted = bool(_attr(related, "turn.interrupted"))
    # any TTS segment aborted mid-synthesis => the agent's speech was truncated. The turn
    # streams sentence-by-sentence, so the cut lands on a late segment, not the first.
    tts_cancelled = any(bool(s.attrs.get("tts.cancelled")) for s in tts)
    cut_reason = _attr(tts, "tts.cut_reason")
    if cut_reason is None and tts_cancelled:
        cut_reason = "barge_in" if interrupted else "hangup"

    # Unattributed = wall-clock inside the v2v window that NO stage covered — computed from
    # the actual span intervals (their union), NOT by subtracting reported durations. In a
    # streaming pipeline stages overlap (the LLM still emits while TTS speaks), so summing
    # durations double-counts and would go negative; a union counts overlap once and is
    # non-negative by construction. The endpointing hold is a real gap with no span of its
    # own, so it is added as attributed time.
    unattributed = _uncovered(
        caller_stop, agent_out, speech_end, stt_start, stt + llm + tts, offset
    )

    return Turn(
        turn_index=_turn_index(turn_span, default=position),
        turn_id=tid,
        trigger=trigger,
        audio_start_s=caller_end,
        audio_end_s=agent_vad_start,
        stt_final_at=stt_final,
        committed_at=committed,
        llm_first_token_at=llm_first_token,
        tts_start_at=tts_start,
        tts_first_audio_at=tts_first_audio,
        audio_out_start_s=agent_vad_start,
        tts_span_present=bool(tts),
        response_latency_ms=response_latency,
        stt_lag_ms=stt_lag,
        endpointing_ms=endpointing,
        llm_ttft_ms=llm_ttft,
        assembly_ms=assembly,
        dispatch_ms=dispatch,
        tts_ttfb_ms=tts_ttfb,
        playout_ms=playout,
        unattributed_ms=unattributed,
        llm_ttft_reported_ms=llm_ttft_reported,
        tts_ttfb_reported_ms=tts_ttfb_reported,
        language=_attr(stt, "stt.language"),
        stt_confidence=_f(_attr(stt, "stt.confidence") or _attr(related, "stt.confidence")),
        tokens_in=_i(_attr(llm, "gen_ai.usage.input_tokens")),
        tokens_out=_i(_attr(llm, "gen_ai.usage.output_tokens")),
        tokens_cached=_i(
            _attr(llm, "gen_ai.usage.cached_tokens")
            or _attr(llm, "gen_ai.usage.cache_read.input_tokens")
        ),
        finish_reason=_attr(llm, "llm.finish_reason"),
        tts_chars=_i(_attr(tts, "tts.chars")),
        tts_chars_cut=_i(_attr(tts, "tts.chars_cut")),
        tts_cancelled=tts_cancelled,
        cut_reason=cut_reason,
        interrupted=interrupted,
        interruption_probability=_f(_attr(related, "turn.interruption_probability")),
        e2e_latency_ms=_sec_to_ms(_attr(related, "metrics.e2e_latency")),
        abandoned=bool(_attr(related, "turn.abandoned")),
        transcript=_transcript(stt) or _content(related, "transcript"),
        llm_raw=(llm[0].content.get("llm_raw") if llm else None) or _content(related, "llm_raw"),
        llm_spoken=(tts[0].content.get("llm_spoken") if tts else None)
        or _content(related, "llm_spoken"),
    )


def _transcript(stt: list[Span]) -> str | None:
    """Carried text is the caller's words too — it just landed on an earlier segment."""
    return (stt[0].content.get("transcript") or stt[0].content.get("carried")) if stt else None


def _audio_endpoints(
    utterances: list[Utterance], win_start: float, win_end: float | None
) -> tuple[float | None, float | None]:
    """Caller-utterance end and agent-utterance start bracketing this turn window."""
    hi = win_end if win_end is not None else float("inf")
    agent_start = None
    for u in sorted(utterances, key=lambda u: u.t_start):
        if u.channel == "agent" and win_start <= u.t_start <= hi:
            agent_start = u.t_start
            break
    bound = agent_start if agent_start is not None else hi
    caller_end = None
    for u in sorted(utterances, key=lambda u: u.t_end):
        if u.channel == "caller" and u.t_end <= bound:
            caller_end = u.t_end
    return caller_end, agent_start


def _ms(a: float | None, b: float | None) -> float | None:
    """(b - a) in ms, only if both present and non-negative; else None."""
    if a is None or b is None:
        return None
    d = (b - a) * 1000.0
    return round(d, 1) if d >= 0 else None


def _mv(
    name: str, ok: bool, value, samples: list[float] | None = None, reason: str = ""
) -> MetricValue:
    """A MetricValue that is present when ``ok``, else unavailable with ``reason``."""
    return MetricValue(
        name=name, value=value if ok else None, samples=samples,
        available=ok, reason=None if ok else reason,
    )


def _audio_metrics(
    audio: AudioAnalysis, agent_iv: list[iv.Interval], cfg: MetricConfig
) -> list[MetricValue]:
    """Caller side from the isolated caller channel; agent side from span windows."""
    caller = [u for u in audio.utterances if u.channel == "caller"]
    duration = max([u.t_end for u in audio.utterances] + [e for _, e in agent_iv], default=0.0)
    cov = audio.coverage
    ok = bool(agent_iv)  # agent-side metrics need the agent's span windows

    out = [
        _mv("capture_coverage", bool(cov), round(min(cov.values()), 4) if cov else None,
            samples=[round(v, 4) for v in cov.values()], reason="no audio"),
        _mv("barge_in", ok, barge_in_count(caller, agent_iv), reason="no agent spans"),
        _mv("dead_air_s", ok,
            dead_air_s(caller, agent_iv, duration, cfg.dead_air_min_s), reason="no agent spans"),
    ]

    tr = talk_ratio(caller, agent_iv, duration)
    out.append(_mv("talk_ratio_caller", bool(tr), tr.get("caller"), reason="no audio"))
    out.append(_mv("talk_ratio_agent", ok, tr.get("agent"), reason="no agent spans"))
    out.append(_mv("overlap_ratio", ok, tr.get("overlap"), reason="no agent spans"))
    out.append(_mv("turn_count_caller", True, caller_turn_stats(caller)["count"]))
    out.append(_mv("turn_count_agent", ok, len(agent_iv), reason="no agent spans"))
    return out


def _layer2_metrics(turns: list[Turn]) -> list[MetricValue]:
    def series(attr: str) -> list[float]:
        return [getattr(t, attr) for t in turns if getattr(t, attr) is not None]

    out = [
        _mv(name, bool(s := series(name)), round(percentile(s, 90), 1) if s else None,
            samples=s, reason="no spans carried this segment")
        for name in ("response_latency_ms", "llm_ttft_ms", "assembly_ms",
                     "tts_ttfb_ms", "unattributed_ms",
                     "llm_ttft_reported_ms", "tts_ttfb_reported_ms")
    ]

    toks = [t.tokens_out for t in turns if t.tokens_out is not None]
    out.append(_mv("tokens_per_turn", bool(toks),
                   round(sum(toks) / len(toks), 1) if toks else None,
                   samples=[float(x) for x in toks], reason="vendor sent no usage"))

    chars = sum(t.tts_chars for t in turns if t.tts_chars)
    cut = sum(t.tts_chars_cut for t in turns if t.tts_chars_cut)
    out.append(_mv("truncation_rate", bool(chars),
                   round(cut / chars, 4) if chars else None, reason="no tts chars"))

    reasons = sorted({t.cut_reason for t in turns if t.cut_reason})
    out.append(_mv("cut_reason", bool(reasons), ",".join(reasons), reason="no truncated turns"))
    return out




def _trust_report(
    trace: Trace,
    audio: AudioAnalysis | None,
    turns: list[Turn],
    offset: float,
    cfg: MetricConfig,
    audio_enabled: bool = True,
) -> TrustReport:
    reasons: list[TrustReason] = []
    layers_run: list[str] = []

    if audio is not None:
        layers_run.append("audio")
    elif not audio_enabled:
        reasons.append(TrustReason.AUDIO_DISABLED)  # OTLP-only by choice, not an outage
    else:
        reasons.append(TrustReason.AUDIO_MISSING)

    has_spans = bool(trace.spans)
    engine = (trace.header.engine or "").lower()
    if has_spans:
        layers_run.append("events")
    elif engine == "s2s":
        reasons.append(TrustReason.TRACE_NOT_APPLICABLE)  # not an outage
    else:
        reasons.append(TrustReason.TRACE_MISSING)  # cascade with no spans = VO was down

    coverage = dict(audio.coverage) if audio else {}
    if coverage and min(coverage.values()) < cfg.partial_coverage_threshold:
        reasons.append(TrustReason.AUDIO_PARTIAL)

    dropped = int(trace.header.counters.get("span_dropped_events", 0) or 0)
    if dropped > 0:
        reasons.append(TrustReason.TELEMETRY_TRUNCATED)

    unattributed_spans = sum(1 for s in trace.spans if s.turn_id is None and s.stage is not Stage.CALL)

    residuals = _clock_residuals(turns)

    return TrustReport(
        reasons=reasons,
        capture_coverage=coverage,
        clock_offset_s=offset if audio is not None else None,
        clock_residual_ms=round(sum(residuals) / len(residuals), 1) if residuals else None,
        clock_residual_per_turn_ms=residuals or None,
        barge_in_agreement=_barge_in_agreement(trace, audio, offset),
        layers_run=layers_run,
        span_dropped_events=dropped,
        unattributed_spans=unattributed_spans,
    )


def _clock_residuals(turns: list[Turn]) -> list[float]:
    """SIGNED per-turn disagreement: anchored span audio-out vs audio utterance start.

    A monotonic positive trend across turns is the ahead-drift signature; never
    average it away — the series is the signal.
    """
    out: list[float] = []
    for t in turns:
        if t.tts_first_audio_at is not None and t.audio_out_start_s is not None:
            out.append(round((t.tts_first_audio_at - t.audio_out_start_s) * 1000.0, 1))
    return out


def _barge_in_agreement(
    trace: Trace, audio: AudioAnalysis | None, offset: float
) -> float | None:
    """Audio-measured barge-ins (caller onset in an agent span window) vs span
    `bargein` events. Agreement is a trust signal, not one fact."""
    if audio is None:
        return None
    caller = [u for u in audio.utterances if u.channel == "caller"]
    agent_iv = _agent_intervals(trace, offset)
    if not caller or not agent_iv:
        return None
    audio_bi = barge_in_count(caller, agent_iv)
    span_bi = sum(1 for s in trace.spans for e in s.events if e.name == "bargein")
    if audio_bi == 0 and span_bi == 0:
        return 1.0
    return round(min(audio_bi, span_bi) / max(audio_bi, span_bi), 4)


def _attr(spans: list[Span], key: str):
    """First non-None value of `key` across spans of a stage. A stage can span several
    OTLP spans (LiveKit puts ttft on llm_node, tokens on llm_request)."""
    for s in spans:
        v = s.attrs.get(key)
        if v is not None:
            return v
    return None


def _content(spans: list[Span], kind: str) -> str | None:
    """First non-empty `kind` content across spans. Producers that carry the transcript
    as an attribute (LiveKit's lk.pii.*) land it here via the adapter's content_attrs."""
    for s in spans:
        v = s.content.get(kind)
        if v:
            return " ".join(map(str, v)) if isinstance(v, list) else str(v)
    return None


def _f(v: object) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _sec_to_ms(v: object) -> float | None:
    f = _f(v)
    return round(f * 1000.0, 1) if f is not None else None


def _i(v: object) -> int | None:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
