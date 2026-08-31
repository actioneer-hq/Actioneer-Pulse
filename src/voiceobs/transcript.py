"""Resolve a call's transcript. Two tiers: BYO upload wins; else derive from the
turn content we already persisted. Consumed by the API now and the judge later."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.db.models import Call, Transcript, Turn
from voiceobs.storage import fetch_bytes


def derive_from_turns(turns: list[Turn]) -> list[dict]:
    """Tier 1 — ordered caller/agent lines from stored turn content."""
    lines: list[dict] = []
    for t in sorted(turns, key=lambda t: t.turn_index):
        if t.caller_transcript:
            lines.append({"turn_index": t.turn_index, "role": "caller",
                          "text": t.caller_transcript})
        agent = t.llm_spoken or t.llm_raw
        if agent:
            lines.append({"turn_index": t.turn_index, "role": "agent", "text": agent})
    return lines


def resolve(db: Session, call: Call) -> dict:
    """BYO transcript if one was uploaded, else the derived one."""
    byo = db.scalar(select(Transcript).where(Transcript.call_id == call.id))
    if byo is not None:
        text = byo.content
        if text is None and byo.uri:
            text = fetch_bytes(byo.uri).decode("utf-8", "replace")
        return {"source": byo.source or "byo", "format": byo.format or "text",
                "text": text}

    turns = db.scalars(select(Turn).where(Turn.call_id == call.id)).all()
    return {"source": "derived", "format": "turns", "lines": derive_from_turns(turns)}
