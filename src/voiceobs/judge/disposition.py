"""Programmatic disposition — a telephony outcome, not an LLM guess. The fine carrier
tags (busy/invalid/provider) fill in later from the carrier status webhook; for now we
distinguish connected from not-answered by whether the caller side actually spoke."""

from __future__ import annotations

from voiceobs.db.models import Call

CONNECTED = "connected"
NO_ANSWER = "no_answer"
UNKNOWN = "unknown"


def programmatic_disposition(call: Call, transcript: dict) -> str:
    """connected when the caller produced content; else no_answer. The LLM runs only
    when connected."""
    if _caller_spoke(transcript):
        return CONNECTED
    # a carrier terminal reason we recognise as never-connected can refine this later
    if (call.hangup_by == "remote" and not call.duration_s) or call.status == "failed":
        return NO_ANSWER
    return NO_ANSWER if not call.duration_s else UNKNOWN


def is_connected(disposition: str) -> bool:
    return disposition == CONNECTED


def _caller_spoke(transcript: dict) -> bool:
    lines = transcript.get("lines") or []
    if any(ln.get("role") == "caller" and ln.get("text") for ln in lines):
        return True
    return bool(transcript.get("text"))  # BYO transcript with any content
