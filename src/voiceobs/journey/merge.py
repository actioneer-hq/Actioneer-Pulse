"""Combine the stages into what is stored and shown. Plain code, no model calls.

`merge_decision`: the decision model's answers -> CallJudgment, with every cause derived here (a failed
journey item was `not_followed` — it came from the script; only what the script never covered is a
`script_gap`), the stage of every agent turn (timeline) and the failures listed without spans.
`apply_llm`: the LLM's words (summary, callback time, unscripted moments, wrong values) plus the turn
of each failure (decision model, asked once the failures are known), which give failures their spans.
"""

from __future__ import annotations

import difflib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from voiceobs.journey.build import STANDARD_RULES
from voiceobs.journey.jev import (
    BranchResult,
    Cause,
    GuardrailResult,
    JevJudgment,
    StageReached,
    StandardRules,
    TimelineEntry,
)
from voiceobs.journey.llm import LLMJudgment, Unscripted, WrongValue
from voiceobs.journey.model import Journey
from voiceobs.journey.spans import Failure, failures, locate
from voiceobs.judge.schema import AnsweredBy, Objective, Sentiment


class Language(BaseModel):
    primary: str
    secondary: list[str] = Field(default_factory=list)


class BranchOut(BranchResult):
    model_config = ConfigDict(populate_by_name=True)

    in_script: bool = True

    @computed_field  # stored with the judgment, derived from the cause
    @property
    def script_gap(self) -> bool:
        return self.cause == "script_gap"


class UnscriptedOut(Unscripted):
    cause: Cause = "script_gap"   # the journey has no branch for it, by definition


class StandardOut(StandardRules):
    callback_time: str | None = None
    callback_in_script: bool = True
    escalation_in_script: bool = True
    non_human_in_script: bool = True


class CallJudgment(BaseModel):
    format: Literal["full"] = "full"
    journey_version: str
    answered_by: AnsweredBy
    language: Language
    opening_done: bool | None = None
    furthest_stage: str | None
    stages: list[StageReached]
    closing_done: bool | None = None
    branches: list[BranchOut]
    unscripted: list[UnscriptedOut] = Field(default_factory=list)
    guardrails_broken: list[GuardrailResult]
    standard: StandardOut
    ended_by: str
    objective_achieved: Objective
    sentiment: Sentiment
    summary: str | None = None
    wrong_values: list[WrongValue] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    failures: list[Failure] = Field(default_factory=list)


def merge_decision(j: Journey, version: str, jev: JevJudgment,
                   timeline: list[TimelineEntry] | None = None) -> CallJudgment:
    """The decision model's answers, causes derived, failures listed (no spans yet)."""
    if jev.answered_by != AnsweredBy.HUMAN:
        # A machine answered (screener, recording, voicemail, IVR): what "the customer" did and which
        # conversation rules held don't apply — keep only the non-human rule and the outcome.
        jev = jev.model_copy(update={
            "branches": [], "guardrails": [],
            "standard": jev.standard.model_copy(update={
                "callback_requested": False, "callback_handled": None,
                "escalation_requested": False, "escalation_handled": None})})

    in_script = {(st, b.if_): getattr(b, "in_script", True) for st, b in j.branches()}
    branches = []
    for b in jev.branches:
        cov = in_script.get((b.stage, b.if_), True)
        out = BranchOut(**b.model_dump(by_alias=True), in_script=cov)
        if b.happened and b.handled is False:
            out.cause = "not_followed" if cov else "script_gap"
        branches.append(out)

    std_cov = {r.if_: r.in_script for r in j.anytime if r.standard}

    def covered(key: str) -> bool:
        return std_cov.get(STANDARD_RULES[key]["if"], True)

    standard = StandardOut(
        **jev.standard.model_dump(),
        callback_in_script=covered("callback"), escalation_in_script=covered("escalation"),
        non_human_in_script=covered("non_human"),
    )
    for key in ("callback", "escalation"):
        if getattr(standard, f"{key}_handled") is False:
            setattr(standard, f"{key}_cause",
                    "not_followed" if getattr(standard, f"{key}_in_script") else "script_gap")
    cj = CallJudgment(
        journey_version=version, answered_by=jev.answered_by,
        language=Language(primary=jev.primary_language, secondary=jev.secondary_languages),
        opening_done=jev.opening_done, closing_done=jev.closing_done,
        furthest_stage=jev.furthest_stage, stages=jev.stages, branches=branches,
        guardrails_broken=[g.model_copy(update={"cause": "not_followed"}) for g in jev.guardrails if g.broken],
        standard=standard, ended_by=jev.ended_by, objective_achieved=jev.objective_achieved,
        sentiment=jev.sentiment, timeline=timeline or [],
    )
    if cj.answered_by == AnsweredBy.HUMAN:
        cj.failures = failures(j, cj)
    return cj


def apply_llm(cj: CallJudgment, j: Journey, llm: LLMJudgment, at: dict[int, int | None],
              lines: list[dict]) -> CallJudgment:
    """Add the LLM's fields and give every failure its span. `at` = the turn of each failure (ids =
    positions in the failure list, from the decision model); `lines` = the resolved transcript lines."""
    cj = cj.model_copy(deep=True)
    cj.summary = llm.summary
    if cj.answered_by != AnsweredBy.HUMAN:
        return cj
    cj.wrong_values = llm.wrong_values
    cj.unscripted = [UnscriptedOut(**u.model_dump()) for u in llm.unscripted]
    if cj.standard.callback_requested:
        cj.standard.callback_time = llm.callback_time
    base = [f for f in cj.failures if f.kind != "unscripted"]
    cj.failures = locate(j, base, at, cj.timeline, lines, cj.unscripted)
    return cj


def merge(j: Journey, version: str, jev: JevJudgment, llm: LLMJudgment, lines: list[dict] | None = None,
          timeline: list[TimelineEntry] | None = None, at: dict[int, int | None] | None = None) -> CallJudgment:
    """Everything at once (offline eval and tests)."""
    return apply_llm(merge_decision(j, version, jev, timeline), j, llm, at or {}, lines or [])


def journey_items(j: Journey) -> dict[str, str]:
    """Every journey item a correction can point at -> what the script says for it."""
    items = {s.stage: f"In the stage '{s.stage}' the agent does this: {s.agent}" for s in j.funnel}
    items.update({b.if_: f"When this happens ({b.if_}), the agent does this: {b.then}" for _, b in j.branches()})
    items.update({g.rule: f"The agent follows this rule: {g.rule}" for g in j.guardrails})
    return items


def resolve_ref(ref: str | None, keys: list[str]) -> str | None:
    """The journey item an LLM-written `ref` names. LLMs paraphrase slightly (an extra word or a trailing period), so
    match case-insensitively by prefix either way, then by close similarity; None if nothing is close."""
    if not ref:
        return None
    norm = lambda x: re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()
    r = norm(ref)
    for k in keys:
        nk = norm(k)
        if nk and (r.startswith(nk) or nk.startswith(r)):
            return k
    close = difflib.get_close_matches(r, [norm(k) for k in keys], n=1, cutoff=0.8)
    return next((k for k in keys if close and norm(k) == close[0]), None)
