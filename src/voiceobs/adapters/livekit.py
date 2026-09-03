"""LiveKit dialect. Span/attr names verified against a real LiveKit Agents trace.

LiveKit splits one exchange into two sibling spans: `user_turn` (the caller side, with
`eou_detection`) and `agent_turn` (the agent side, with `llm_node`/`tts_node`/
`agent_speaking`). VO models a turn as the whole exchange, so we re-attach each
`agent_turn` subtree to the `user_turn` that precedes it.

Latency comes as attributes (`lk.response.ttft` / `lk.response.ttfb`), not first-token/
first-audio events, so it lands in the `*_reported_ms` fields."""

from __future__ import annotations

import json
from typing import ClassVar

from voiceobs.adapters.generic import OTLPAdapter, _propagate_turn_ids
from voiceobs.adapters.otlp import iter_spans
from voiceobs.core.model import Span, Stage, Trace

# LiveKit's authoritative per-request metrics arrive as a JSON *string* under a single
# attribute (lk.llm_metrics on llm_request, lk.tts_metrics on tts_request). Unparsed it
# is dead weight; expanded, it is the richest account of the turn. src key -> VO canonical.
_LLM_METRICS: dict[str, str] = {
    "ttft": "metrics.ttft",                        # seconds
    "completion_tokens": "gen_ai.usage.output_tokens",
    "prompt_tokens": "gen_ai.usage.input_tokens",
    "prompt_cached_tokens": "gen_ai.usage.cached_tokens",
    "total_tokens": "llm.total_tokens",
    "tokens_per_second": "llm.tokens_per_second",
    "duration": "llm.duration_s",
    "cancelled": "llm.cancelled",
}
_TTS_METRICS: dict[str, str] = {
    "ttfb": "metrics.ttfb",                        # seconds
    "characters_count": "tts.chars",
    "audio_duration": "tts.audio_duration_s",
    "duration": "tts.duration_s",
    "input_tokens": "tts.input_tokens",
    "output_tokens": "tts.output_tokens",
    "streamed": "tts.streamed",
    # aborted mid-synthesis — the ground-truth "the agent's speech was cut off" signal,
    # stronger than lk.interrupted (a barge-in attempt that may not have truncated anything).
    "cancelled": "tts.cancelled",
}


class LiveKitAdapter(OTLPAdapter):
    name = "livekit"
    version = 1

    stages: ClassVar[dict[str, Stage]] = {
        "agent_session": Stage.CALL,
        # session lifecycle — the agent joining/leaving, not a pipeline stage
        "start_agent_activity": Stage.CALL,
        "on_enter": Stage.CALL,
        "on_exit": Stage.CALL,
        "drain_agent_activity": Stage.CALL,
        "user_turn": Stage.TURN,
        "agent_turn": Stage.TURN,        # the agent's half; folded into the exchange below
        "user_speaking": Stage.SPEECH,   # caller's speech window; its end = real end of speech
        "agent_speaking": Stage.PLAYOUT,
        "eou_detection": Stage.STT,
        "llm_request": Stage.LLM,
        "llm_request_run": Stage.LLM,    # retry wrapper around llm_request
        "llm_node": Stage.LLM,
        "tts_node": Stage.TTS,
        "tts_request": Stage.TTS,        # carries lk.tts_metrics (chars, audio duration, ttfb)
        "tts_request_run": Stage.TTS,    # retry wrapper around tts_request
        "tts_stream_adapter": Stage.TTS, # pipes LLM output into TTS as it streams
        "function_tool": Stage.TOOL,
    }

    attr_aliases: ClassVar[dict[str, str]] = {
        "lk.interrupted": "turn.interrupted",
        "lk.interruption.probability": "turn.interruption_probability",
        "lk.response.ttft": "metrics.ttft",   # on llm_node (seconds)
        "lk.response.ttfb": "metrics.ttfb",   # on tts_node (seconds)
        "lk.e2e_latency": "metrics.e2e_latency",  # engine's own end-to-end (seconds)
        "lk.end_of_turn_delay": "endpointing.delay",  # endpointing hold (seconds)
        "lk.transcript_confidence": "stt.confidence",
        "gen_ai.request.model": "gen_ai.request.model",
    }

    # LiveKit carries the transcript as attributes, not under voice.content.*
    content_attrs: ClassVar[dict[str, str]] = {
        "lk.pii.user_transcript": "transcript",
        "lk.pii.response.text": "llm_spoken",
    }

    def derive(self, attrs: dict, stage: Stage) -> dict:
        """Expand the lk.llm_metrics / lk.tts_metrics JSON blobs into canonical attrs so
        the waterfall reads them like any other field. The raw string is replaced, not
        kept — the parsed fields carry everything it held."""
        _expand(attrs, "lk.llm_metrics", _LLM_METRICS)
        _expand(attrs, "lk.tts_metrics", _TTS_METRICS)
        return attrs

    def matches(self, payload: dict) -> bool:
        return any(s.get("name") == "agent_session" for _, s in iter_spans(payload))

    def to_trace(self, payload: dict) -> Trace:
        trace = super().to_trace(payload)
        return Trace(header=trace.header, spans=_pair_agent_turns(trace.spans))


def _expand(attrs: dict, key: str, mapping: dict[str, str]) -> None:
    raw = attrs.pop(key, None)
    if not isinstance(raw, str):
        return
    try:
        m = json.loads(raw)
    except (ValueError, TypeError):
        attrs[key] = raw  # unparseable — keep the blob rather than lose it
        return
    for src, dst in mapping.items():
        v = m.get(src)
        if v is not None and attrs.get(dst) is None:
            attrs[dst] = v
    model = (m.get("metadata") or {}).get("model_name")
    if model and attrs.get("gen_ai.request.model") is None:
        attrs["gen_ai.request.model"] = model


def _pair_agent_turns(spans: list[Span]) -> list[Span]:
    """Give each `agent_turn` subtree the turn_id of the preceding `user_turn`, so the
    agent's LLM/TTS spans land in the same exchange as the caller's STT."""
    by_id = {s.span_id: s for s in spans}
    # by name, not stage: agent_turn is also stage TURN, but it is the side we are folding
    # IN — the anchor is the caller's user_turn.
    user_turns = sorted(
        (s for s in spans if s.name == "user_turn"), key=lambda s: s.t_start
    )
    if not user_turns:
        return spans

    def preceding_turn_id(t_start: float) -> str | None:
        prior = [u for u in user_turns if u.t_start <= t_start] or user_turns
        u = prior[-1]
        return u.turn_id or u.span_id

    # span_id -> the agent_turn root it descends from (incl. the agent_turn itself)
    agent_roots = {s.span_id: s for s in spans if s.name == "agent_turn"}

    def agent_turn_of(s: Span) -> Span | None:
        cur: Span | None = s
        seen: set[str] = set()
        while cur is not None and cur.span_id not in seen:
            seen.add(cur.span_id)
            if cur.span_id in agent_roots:
                return cur
            cur = by_id.get(cur.parent_span_id) if cur.parent_span_id else None
        return None

    out: list[Span] = []
    for s in spans:
        root = agent_turn_of(s)
        if root is not None:
            tid = preceding_turn_id(root.t_start)
            if tid is not None:
                s = s.model_copy(update={"turn_id": tid})
        out.append(s)
    return _propagate_turn_ids(out)
