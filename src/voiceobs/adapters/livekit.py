"""LiveKit dialect. Span/attr names verified against a real LiveKit Agents trace.

LiveKit splits one exchange into two sibling spans: `user_turn` (the caller side, with
`eou_detection`) and `agent_turn` (the agent side, with `llm_node`/`tts_node`/
`agent_speaking`). VO models a turn as the whole exchange, so we re-attach each
`agent_turn` subtree to the `user_turn` that precedes it.

Latency comes as attributes (`lk.response.ttft` / `lk.response.ttfb`), not first-token/
first-audio events, so it lands in the `*_reported_ms` fields."""

from __future__ import annotations

from typing import ClassVar

from voiceobs.adapters.generic import OTLPAdapter, _propagate_turn_ids
from voiceobs.adapters.otlp import iter_spans
from voiceobs.core.model import Span, Stage, Trace


class LiveKitAdapter(OTLPAdapter):
    name = "livekit"
    version = 1

    stages: ClassVar[dict[str, Stage]] = {
        "agent_session": Stage.CALL,
        "user_turn": Stage.TURN,
        "agent_speaking": Stage.PLAYOUT,
        "eou_detection": Stage.STT,
        "llm_request": Stage.LLM,
        "llm_node": Stage.LLM,
        "tts_node": Stage.TTS,
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

    def matches(self, payload: dict) -> bool:
        return any(s.get("name") == "agent_session" for _, s in iter_spans(payload))

    def to_trace(self, payload: dict) -> Trace:
        trace = super().to_trace(payload)
        return Trace(header=trace.header, spans=_pair_agent_turns(trace.spans))


def _pair_agent_turns(spans: list[Span]) -> list[Span]:
    """Give each `agent_turn` subtree the turn_id of the preceding `user_turn`, so the
    agent's LLM/TTS spans land in the same exchange as the caller's STT."""
    by_id = {s.span_id: s for s in spans}
    user_turns = sorted(
        (s for s in spans if s.stage is Stage.TURN), key=lambda s: s.t_start
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
