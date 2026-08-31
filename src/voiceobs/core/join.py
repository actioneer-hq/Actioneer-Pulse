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
) -> Analysis:
    """Join spans to audio and compute turns, metrics, and the trust report."""
    cfg = cfg or MetricConfig()
    offset = t0_offset_s or 0.0

    turn_spans = [s for s in trace.spans if s.stage is Stage.TURN]
    turn_spans.sort(key=lambda s: (_turn_index(s), s.t_start))
    has_spans = bool(trace.spans)

    utterances = audio.utterances if audio else []

    turns = [
        _build_turn(ts, trace.spans, utterances, offset)
        for ts in turn_spans
    ]

    agent_iv = _agent_intervals(trace, offset)  # agent-side truth: spans, not VAD

    metrics: list[MetricValue] = []
    if audio is not None:
        metrics.extend(_audio_metrics(audio, agent_iv, cfg))
    if has_spans and turn_spans:
        metrics.extend(_layer2_metrics(turns))

    trust = _trust_report(trace, audio, turns, offset, cfg)

    return Analysis(
        turns=turns,
        metrics=metrics,
        trust=trust,
        metric_version=METRIC_VERSION,
        adapter_version=ADAPTER_VERSION,
    )


def _turn_index(span: Span) -> int:
    v = span.attrs.get("turn.index")
    try:
        return int(v)
    except (TypeError, ValueError):
        return 10**9


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


def _build_turn(
    turn_span: Span, spans: list[Span], utterances: list[Utterance], offset: float
) -> Turn:
    tid = turn_span.turn_id or f"{turn_span.span_id}"
    trigger = str(turn_span.attrs.get("turn.trigger", "endpoint"))

    speech = _children(spans, tid, Stage.SPEECH)
    stt = _children(spans, tid, Stage.STT)
    llm = _children(spans, tid, Stage.LLM)
    tts = _children(spans, tid, Stage.TTS)

    # The caller stopped talking here. Backdated by the producer to the real instant,
    # not the moment its VAD noticed — that gap IS the endpointing hold below.
    speech_end = _to_audio(speech[0].t_end, offset) if speech and speech[0].t_end else None
    stt_start = _to_audio(stt[0].t_start, offset) if stt else None
    stt_final = _to_audio(stt[0].t_end, offset) if stt else None
    llm_start = llm[0].t_start if llm else None
    llm_first_token = _to_audio(_first_event_t(spans, "llm.first_token", tid), offset)
    tts_start = _to_audio(tts[0].t_start, offset) if tts else None
    tts_first_audio = _to_audio(_first_event_t(spans, "tts.first_audio", tid), offset)
    committed = _to_audio(_first_event_t(spans, "turn.committed", tid), offset)
    if committed is None:  # fall back to the turn span start
        committed = _to_audio(turn_span.t_start, offset)

    # caller side comes from the isolated caller channel (VAD); agent onset (VAD) is
    # kept only for the clock-residual trust check, never for the latency numbers.
    win_start = _to_audio(turn_span.t_start, offset) or 0.0
    win_end = _to_audio(turn_span.t_end, offset)
    caller_end, agent_vad_start = _audio_endpoints(utterances, win_start, win_end)

    # agent response = when the engine sent first audio (span). caller stop = the end
    # of speech per spans. response_latency is span-side, per the OTLP-for-agent rule.
    agent_out = tts_first_audio if tts_first_audio is not None else tts_start
    caller_stop = speech_end if speech_end is not None else stt_final

    # the waterfall (ms); each segment is None unless both endpoints exist.
    # endpointing is the VAD silence hold — how long we waited to be sure the caller
    # was done. See docs/vas-telemetry-semantics.md §3 "Endpointing".
    endpointing = _ms(speech_end, stt_start)
    stt_lag = _ms(stt_start, stt_final)
    llm_ttft = _ms(_to_audio(llm_start, offset), llm_first_token)
    assembly = _ms(llm_first_token, tts_start)
    tts_ttfb = _ms(tts_start, tts_first_audio)
    # playout = sent -> heard (span vs caller-recording); the network tail, reported
    # but not summed into response_latency, which ends when the engine sent audio.
    playout = _ms(tts_first_audio, agent_vad_start)
    response_latency = _ms(caller_stop, agent_out)

    parts = [p for p in (endpointing, stt_lag, llm_ttft, assembly, tts_ttfb) if p]
    total = response_latency
    unattributed = round(total - sum(parts), 1) if total is not None else None

    return Turn(
        turn_index=_turn_index(turn_span),
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
        tts_ttfb_ms=tts_ttfb,
        playout_ms=playout,
        unattributed_ms=unattributed,
        language=stt[0].attrs.get("stt.language") if stt else None,
        stt_confidence=_f(stt[0].attrs.get("stt.confidence")) if stt else None,
        tokens_in=_i(llm[0].attrs.get("gen_ai.usage.input_tokens")) if llm else None,
        tokens_out=_i(llm[0].attrs.get("gen_ai.usage.output_tokens")) if llm else None,
        finish_reason=llm[0].attrs.get("llm.finish_reason") if llm else None,
        tts_chars=_i(tts[0].attrs.get("tts.chars")) if tts else None,
        tts_chars_cut=_i(tts[0].attrs.get("tts.chars_cut")) if tts else None,
        cut_reason=tts[0].attrs.get("tts.cut_reason") if tts else None,
        interrupted=bool(turn_span.attrs.get("turn.interrupted", False)),
        abandoned=bool(turn_span.attrs.get("turn.abandoned", False)),
        transcript=_transcript(stt),
        llm_raw=llm[0].content.get("llm_raw") if llm else None,
        llm_spoken=tts[0].content.get("llm_spoken") if tts else None,
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
                     "tts_ttfb_ms", "unattributed_ms")
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
) -> TrustReport:
    reasons: list[TrustReason] = []
    layers_run: list[str] = []

    if audio is not None:
        layers_run.append("audio")
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


def _f(v: object) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _i(v: object) -> int | None:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
