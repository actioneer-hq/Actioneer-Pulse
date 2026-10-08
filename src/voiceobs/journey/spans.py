"""Failures of one call, each with its span (the transcript turns where it happened). Plain code.

The decision model says WHAT failed, which part of the call every agent turn is in (timeline), and at
which turn each failure happened. Joining them gives every failure a span — what clustering embeds and
curation corrects.

Turn numbers are the transcript's `turn_index`; one turn may hold a customer line and the agent's reply
(Turn-based transcripts) or one line each — `_next_agent` handles both.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from voiceobs.journey.jev import COMPLETED, Cause, TimelineEntry
from voiceobs.journey.model import Journey
from voiceobs.judge.schema import Objective

FailureKind = Literal["stage", "branch", "guardrail", "standard", "opening", "closing", "unscripted"]
_STAGE_SPAN = 4  # agent turns looked at after the furthest stage, for a missed next stage


class Failure(BaseModel):
    kind: FailureKind
    item: str                     # the journey item's exact name (or the unscripted moment)
    cause: Cause
    turns: list[int] = Field(default_factory=list)   # the span; empty until enrichment
    target_turn: int | None = None                    # the agent turn to correct (curation)
    located: bool | None = None   # stage 2 found where it happened (None = not asked / not applicable)


LOCATE = ("branch", "guardrail", "standard", "stage")  # failures stage 2 is asked to place


def _agent_turns(lines: list[dict]) -> list[int]:
    return [ln["turn_index"] for ln in lines if ln.get("role") != "caller" and "turn_index" in ln]


def _next_agent(lines: list[dict], turn: int) -> int | None:
    """The first agent line at or after `turn` (the agent's reply to what happened at `turn`)."""
    return next((t for t in _agent_turns(lines) if t >= turn), None)


def _span(*turns: int | None) -> list[int]:
    return sorted({t for t in turns if t is not None})


def failures(j: Journey, cj) -> list[Failure]:
    """Stage 1: what failed, from the decision model's answers (no spans yet). `cj` is a CallJudgment
    (merge) — read duck-typed to avoid a circular import."""
    out = [Failure(kind="branch", item=b.if_, cause=b.cause)
           for b in cj.branches if b.happened and b.handled is False and b.cause]
    out += [Failure(kind="guardrail", item=g.rule, cause=g.cause or "not_followed")
            for g in cj.guardrails_broken]
    std = cj.standard
    for key in ("callback", "escalation"):
        if getattr(std, f"{key}_requested") and getattr(std, f"{key}_handled") is False:
            rule = next((r.if_ for r in j.anytime if r.standard and key in r.if_.lower()), key)
            out.append(Failure(kind="standard", item=rule, cause=getattr(std, f"{key}_cause") or "not_followed"))
    if cj.opening_done is False and j.opening:
        out.append(Failure(kind="opening", item="Opening", cause="not_followed"))
    if nxt := _next_stage(j, cj):
        out.append(Failure(kind="stage", item=nxt, cause="not_followed"))
    if cj.closing_done is False and j.closing and cj.ended_by == COMPLETED:
        out.append(Failure(kind="closing", item="Closing", cause="not_followed"))
    return out


def to_locate(fs: list[Failure]) -> list[tuple[int, str]]:
    """(id, what went wrong) for the failures the decision model places (ids = positions in `fs`)."""
    what = {"branch": "the customer did this and the agent didn't handle it as the script says",
            "guardrail": "an agent line went against this rule",
            "standard": "the customer did this and the agent didn't handle it",
            "stage": "the agent should have moved the call into this stage but didn't"}
    return [(i, f"{what[f.kind]}: {f.item}") for i, f in enumerate(fs) if f.kind in LOCATE]


def locate(j: Journey, fs: list[Failure], at: dict[int, int | None], timeline: list[TimelineEntry],
           lines: list[dict], unscripted=()) -> list[Failure]:
    """Give each failure its span. `at` = the decision model's turn per failure id (None = not found);
    `timeline` = the stage of each agent turn; `unscripted` = the LLM's unscripted moments."""
    starts: dict[str, int] = {}
    for e in sorted(timeline, key=lambda e: e.turn):
        starts.setdefault(e.item, e.turn)
    agents = _agent_turns(lines)
    out = []
    for i, f in enumerate(fs):
        f = f.model_copy()
        if f.kind in LOCATE:
            t = at.get(i)
            if t is None and f.kind == "stage":  # fall back: the agent turns after the furthest stage
                start = max((t for item, t in starts.items() if item in _before(j, f.item)), default=-1)
                t = next((a for a in agents if a > start), None)
            reply = _next_agent(lines, t) if t is not None else None
            f.turns, f.target_turn, f.located = _span(t, reply), reply, t is not None
            if f.kind == "stage" and reply is not None:
                f.turns = [a for a in agents if a >= reply][:_STAGE_SPAN]
        elif f.kind == "opening":
            f.turns, f.target_turn = agents[:2], (agents[0] if agents else None)
        elif f.kind == "closing":
            f.turns, f.target_turn = agents[-1:], (agents[-1] if agents else None)
        out.append(f)
    out += [Failure(kind="unscripted", item=u.what, cause="script_gap", turns=[u.turn]) for u in unscripted]
    return out


def _before(j: Journey, stage: str) -> set[str]:
    names = [s.stage for s in j.funnel]
    return set(names[: names.index(stage)]) | {"Opening"} if stage in names else {"Opening"}


def _next_stage(j: Journey, cj) -> str | None:
    """The stage the agent failed to move the call into: the one after the furthest reached — unless the
    objective was met, or the customer left through a branch the agent handled (busy, not interested…)."""
    if cj.objective_achieved == Objective.ACHIEVED:
        return None
    names = [s.stage for s in j.funnel]
    i = names.index(cj.furthest_stage) + 1 if cj.furthest_stage in names else 0
    if i >= len(names):
        return None
    exit_ = next((b for b in cj.branches if b.if_ == cj.ended_by), None)
    if exit_ is not None and exit_.handled:
        return None
    if exit_ is None and cj.ended_by != COMPLETED:
        return None  # ended through a standard rule (callback, human, machine) — judged on its own
    return names[i]


_CUSTOMER_LED = ("branch", "standard", "unscripted")  # failures the customer's words set off


def moment_text(f: Failure, lines: list[dict]) -> tuple[int, str] | None:
    """The line that caused a failure, for clustering: the customer's line for what the customer did, the
    agent's line for what the agent did. (turn, text), or None when the failure has no span."""
    if not f.turns:
        return None
    role_is_caller = f.kind in _CUSTOMER_LED
    for turn in f.turns:
        text = " ".join(ln.get("text") or "" for ln in lines if ln.get("turn_index") == turn
                        and (ln.get("role") == "caller") == role_is_caller).strip()
        if text:
            return turn, text
    return None
