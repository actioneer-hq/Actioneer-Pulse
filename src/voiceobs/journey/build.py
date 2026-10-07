"""Draft (from the extraction LLM) -> Journey: grounding checks, params, Pulse's standard rules."""

from __future__ import annotations

import re

from voiceobs.journey.model import END, AnytimeRule, Journey, JourneyDraft, Stage
from voiceobs.onboarding.format import placeholders

# Pulse's unsaid rules — apply to every voice agent whether or not its script mentions them.
STANDARD_RULES: dict[str, dict[str, str]] = {
    "non_human": {
        "if": "An IVR, voicemail, recording or the phone's own assistant (iPhone/Android "
              "call screening) answers",
        "then": "Don't carry on a conversation: identify once if asked, never pitch, end if no "
                "person comes on",
    },
    "callback": {
        "if": "Customer asks to be called back",
        "then": "Confirm a specific time, then end politely",
    },
    "escalation": {
        "if": "Customer asks to speak to a human",
        "then": "Acknowledge it, hand over or arrange a callback, then end politely",
    },
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _grounded(quote: str | None, script_norm: str) -> bool:
    """A quote counts only if it really appears in the script (whitespace/case-insensitive)."""
    return bool(quote) and _norm(quote) in script_norm


def build_journey(script: str, draft: JourneyDraft) -> Journey:
    """Assemble the journey: drop branches/guardrails whose quote isn't in the script (invented),
    take params from the script's {{placeholders}}, and append the standard rules."""
    s = _norm(script)
    funnel = [
        Stage(stage=st.stage, agent=st.agent, done_when=st.done_when, script_quote=st.script_quote,
              side=[b for b in st.side if _grounded(b.script_quote, s)])
        for st in draft.funnel
    ]
    anytime = [AnytimeRule(**b.model_dump(by_alias=True)) for b in draft.anytime
               if _grounded(b.script_quote, s)]
    guardrails = [g for g in draft.guardrails if _grounded(g.script_quote, s)]

    cov = draft.standard_coverage
    for key, rule in STANDARD_RULES.items():
        quote = getattr(cov, key)
        in_script = _grounded(quote, s)
        anytime.append(AnytimeRule(**{"if": rule["if"]}, then=rule["then"], goes_to=END,
                                   standard=True, in_script=in_script,
                                   script_quote=quote if in_script else None))
    return Journey(objective=draft.objective, params=placeholders(script), funnel=funnel,
                   opening=draft.opening, closing=draft.closing,
                   anytime=_dedupe(anytime), guardrails=guardrails)


def _dedupe(rules: list[AnytimeRule]) -> list[AnytimeRule]:
    out: dict[str, AnytimeRule] = {}
    for r in rules:
        out.setdefault(r.if_, r)
    return list(out.values())

