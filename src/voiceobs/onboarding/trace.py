"""Timestamped utterances -> a canonical Trace the shared Calculator turns into Turn rows.

Each speaker's consecutive utterances are merged into one block. A customer block emits
`stt.final` at its end (the customer stopped talking); the agent block that follows emits
`llm.spoken` + `tts.first_audio` at its start (the agent started talking). The Calculator derives
turns from those events, so response latency = agent start - customer stop: a broad, honest
gap from the recording, not a pipeline-internal TTFB.
"""

from __future__ import annotations

from datetime import datetime

from voiceobs.core.model import CallHeader, Span, SpanEvent, Stage, Trace
from voiceobs.onboarding.format import Utterance


def merge_blocks(utterances: list[Utterance]) -> list[Utterance]:
    blocks: list[Utterance] = []
    for u in sorted(utterances, key=lambda x: x.start):
        if blocks and blocks[-1].speaker == u.speaker:
            prev = blocks[-1]
            end = max(filter(None, (prev.end, u.end, u.start)), default=None)
            blocks[-1] = Utterance(speaker=u.speaker, text=f"{prev.text} {u.text}",
                                   start=prev.start, end=end)
        else:
            blocks.append(u)
    return blocks


def build_trace(call_id: str, utterances: list[Utterance], *, started_at: datetime | None,
                duration_s: float | None, labels: dict | None = None) -> Trace:
    events: list[SpanEvent] = []
    for b in merge_blocks(utterances):
        if b.speaker == "customer":
            events.append(SpanEvent(name="stt.final", t=b.end if b.end is not None else b.start,
                                    content={"transcript": b.text}))
        else:
            events.append(SpanEvent(name="llm.spoken", t=b.start, content={"llm_spoken": b.text}))
            events.append(SpanEvent(name="tts.first_audio", t=b.start))
    last = max((u.end or u.start for u in utterances), default=0.0)
    span = Span(span_id=f"{call_id}-call", parent_span_id=None, name="call", stage=Stage.CALL,
                t_start=0.0, t_end=duration_s or last or None, sequence=0, events=events)
    header = CallHeader(call_id=call_id, source="upload", environment="prod",
                        started_at=started_at, labels=labels or {})
    return Trace(header=header, spans=[span])


def customer_spoke(utterances: list[Utterance]) -> bool:
    return any(u.speaker == "customer" and u.text.strip() for u in utterances)
