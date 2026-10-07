"""The journey: a script, structured for judging. Converted once per script version.

objective -> an ordered primary funnel of stages (chronology = list order) -> per stage, the side
branches the CUSTOMER can trigger -> anytime branches -> guardrails. Names are the ids: stage names,
branch `if` texts and guardrail rules are what judge outputs refer to and what merging joins on.

Pulse adds three unsaid rules to every journey (non-human answerer, callback, human escalation);
`in_script` says whether the script itself covers them, so a missing rule can be recommended.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

END = "End"
SAME = "Same stage"


class SideBranch(BaseModel):
    """Something the customer does, how the agent should handle it, and where the call goes."""

    model_config = ConfigDict(populate_by_name=True)

    if_: str = Field(alias="if", min_length=1)  # the customer's condition, in plain words
    then: str = Field(min_length=1)             # what the agent should do
    goes_to: str = Field(min_length=1)          # a stage name | "End" | "Same stage"
    script_quote: str | None = None             # exact source text in the script (grounding)


class Bookend(BaseModel):
    """How the call opens or closes. Kept out of the funnel: greeting and goodbye aren't progress
    toward the objective."""

    agent: str = Field(min_length=1)            # what the agent does
    done_when: str = Field(min_length=1)        # observable in a transcript
    script_quote: str | None = None


class Stage(BaseModel):
    stage: str = Field(min_length=1)            # the name is its id
    agent: str = Field(min_length=1)            # what the agent does at this stage
    done_when: str = Field(min_length=1)        # completion, observable in a transcript
    script_quote: str | None = None
    side: list[SideBranch] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_branches(self) -> Stage:
        _no_dupes([b.if_ for b in self.side], f"side branch in stage '{self.stage}'")
        return self


class AnytimeRule(SideBranch):
    """A branch that can happen at any stage. Pulse's built-in rules live here too."""

    standard: bool = False   # True = one of Pulse's unsaid rules
    in_script: bool = True   # False = Pulse added it because the script is silent on it


class Guardrail(BaseModel):
    rule: str = Field(min_length=1)             # the rule text is its id
    script_quote: str | None = None


class Journey(BaseModel):
    format: Literal["pulse.journey.v1"] = "pulse.journey.v1"
    objective: str = Field(min_length=1)
    params: list[str] = Field(default_factory=list)   # the script's {{placeholders}} (regex, not LLM)
    opening: Bookend | None = None                    # how the call opens (not a funnel stage)
    funnel: list[Stage] = Field(min_length=1)
    closing: Bookend | None = None                    # how the call ends (not a funnel stage)
    anytime: list[AnytimeRule] = Field(default_factory=list)
    guardrails: list[Guardrail] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Journey:
        names = [s.stage for s in self.funnel]
        _no_dupes(names, "stage")
        _no_dupes([r.if_ for r in self.anytime], "anytime branch")
        _no_dupes([g.rule for g in self.guardrails], "guardrail")
        targets = {*names, END, SAME}
        for where, branch in self.branches():
            if branch.goes_to not in targets:
                raise ValueError(f"branch '{branch.if_}' ({where or 'anytime'}) goes_to "
                                 f"'{branch.goes_to}', which is not a stage, '{END}' or '{SAME}'")
        return self

    def branches(self) -> list[tuple[str | None, SideBranch]]:
        """Every branch with the stage it belongs to (None = anytime), in journey order."""
        return [(s.stage, b) for s in self.funnel for b in s.side] + [(None, r) for r in self.anytime]


class StandardCoverage(BaseModel):
    """Where the script itself handles Pulse's unsaid rules: the exact quote, or None if it's silent."""

    non_human: str | None = None    # IVR / voicemail / recording / phone assistant
    callback: str | None = None     # customer asks to be called back
    escalation: str | None = None   # customer asks for a human


class JourneyDraft(BaseModel):
    """What the extraction LLM returns. Params and Pulse's standard rules are added by code."""

    objective: str
    opening: Bookend | None = None
    funnel: list[Stage]
    closing: Bookend | None = None
    anytime: list[SideBranch] = Field(default_factory=list)  # script-derived only
    guardrails: list[Guardrail] = Field(default_factory=list)
    standard_coverage: StandardCoverage = Field(default_factory=StandardCoverage)


def _no_dupes(items: list[str], what: str) -> None:
    seen: set[str] = set()
    dup = [i for i in items if i in seen or seen.add(i)]
    if dup:
        raise ValueError(f"duplicate {what}: {dup[0]!r}")
