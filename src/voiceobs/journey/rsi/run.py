"""One script-improvement run on a script journey: additions -> meta clubbing -> not-followed RCA ->
script A (revisions) and script B (restructure) -> each fitted under the limit, rendered and diffed
against the original. Pure orchestration: the LLM and the decision model are passed in."""

from __future__ import annotations

from voiceobs.journey.model import Journey
from voiceobs.journey.rsi import restructure
from voiceobs.journey.rsi.additions import add_gaps
from voiceobs.journey.rsi.budget import fit
from voiceobs.journey.rsi.club import club
from voiceobs.journey.rsi.common import LLM, Failure, Gap
from voiceobs.journey.rsi.diff import diff
from voiceobs.journey.rsi.rca import rca
from voiceobs.journey.rsi.render import render
from voiceobs.journey.rsi.revise import revise


def improve(j: Journey, gaps: list[Gap], failures: list[Failure], reach: list[dict], decision, llm: LLM,
            run: str) -> dict:
    added = club(add_gaps(j, gaps, llm, run), decision, llm, run)
    findings = rca(added, failures, decision)
    script_a = revise(added, findings, failures, llm, run)
    plan = llm(restructure.TASK, restructure.plan_input(added, reach, findings, diff(j, added)), restructure.Plan)
    script_b, ops = restructure.apply(added, plan, run)
    variants = {}
    for name, v in (("additions", added), ("A", script_a), ("B", script_b)):
        fitted = fit(v, llm)
        text = render(fitted)
        variants[name] = {"journey": fitted.model_dump(mode="json", by_alias=True), "text": text,
                          "chars": len(text), "changes": diff(j, fitted), **({"ops": ops} if name == "B" else {})}
    return {"findings": findings, "training": [f for f in findings if f["fix"] == "training"],
            "variants": variants}
