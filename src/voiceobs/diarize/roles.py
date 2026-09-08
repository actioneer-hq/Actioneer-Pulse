"""Assign diarization speaker labels to caller/agent roles, and map segments to Utterances.

Diarization only says "SPEAKER_00 / SPEAKER_01" — not which is the agent. Default heuristic: the
speaker who talks first is the agent (voice agents open the call). This is a guess; a per-call UI flip
overrides it, and Phase 4 will prompt-match when STT is on. Only the two most-talkative speakers are
kept as agent/caller; any extra labels fold into caller (cross-talk / third party)."""

from __future__ import annotations

from voiceobs.core.model import Utterance
from voiceobs.diarize.client import Diarization


def assign_roles(diar: Diarization, agent_speaker: str | None = None) -> dict[str, str]:
    """Map each speaker label → 'caller' | 'agent'.

    `agent_speaker`, when given (a UI override), forces that label to the agent. Otherwise the
    earliest-starting speaker is the agent."""
    speakers = diar.speakers()
    if not speakers:
        return {}
    if agent_speaker is None:
        first = min(diar.segments, key=lambda s: s.start)
        agent_speaker = first.speaker
    return {sp: ("agent" if sp == agent_speaker else "caller") for sp in speakers}


def to_utterances(diar: Diarization, roles: dict[str, str]) -> list[Utterance]:
    """Diarization segments → core Utterances tagged caller/agent, in time order."""
    return [
        Utterance(channel=roles.get(s.speaker, "caller"), t_start=s.start, t_end=s.end)
        for s in sorted(diar.segments, key=lambda s: s.start)
        if s.end > s.start
    ]
