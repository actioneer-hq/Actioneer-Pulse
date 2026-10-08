"""The journey: a script, structured for judging. Converted once per script version.

objective -> an ordered primary funnel of stages (chronology = list order) -> per stage, the side
branches the CUSTOMER can trigger -> anytime branches -> guardrails. Names are the ids: stage names,
branch `if` texts and guardrail rules are what judge outputs refer to and what merging joins on.

Pulse adds three unsaid rules to every journey (non-human answerer, callback, human escalation);
`in_script` says whether the script itself covers them, so a missing rule can be recommended.

It also carries what the script needs to be rendered back as text (persona, facts, sample `say` lines),
so script improvement (journey/rsi) edits this JSON and renders the new script from it. Items an
improvement added or changed carry `origin` — the version diff.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

END = "End"
SAME = "Same stage"


class Origin(BaseModel):
    """Why an item is new or changed (script improvement) — the version diff marker."""

    change: Literal["added", "revised", "merged", "moved"] = "added"
    run: str | None = None        # the improvement run
    reason: str | None = None     # one line: the evidence behind it
    source: list[str] = Field(default_factory=list)  # cluster / failure / item ids it came from


class SideBranch(BaseModel):
    """Something the customer does, how the agent should handle it, and where the call goes."""

    model_config = ConfigDict(populate_by_name=True)

    if_: str = Field(alias="if", min_length=1)  # the customer's condition, in plain words
    then: str = Field(min_length=1)             # what the agent should do
    goes_to: str = Field(min_length=1)          # a stage name | "End" | "Same stage"
    script_quote: str | None = None             # exact source text in the script (grounding)
    say: list[str] = Field(default_factory=list)  # 1-2 sample lines in the script's language
    origin: Origin | None = None


class Bookend(BaseModel):
    """How the call opens or closes. Kept out of the funnel: greeting and goodbye aren't progress
    toward the objective."""

    agent: str = Field(min_length=1)            # what the agent does
    done_when: str = Field(min_length=1)        # observable in a transcript
    script_quote: str | None = None
    say: list[str] = Field(default_factory=list)
    origin: Origin | None = None


class Stage(BaseModel):
    stage: str = Field(min_length=1)            # the name is its id
    agent: str = Field(min_length=1)            # what the agent does at this stage
    done_when: str = Field(min_length=1)        # completion, observable in a transcript
    script_quote: str | None = None
    say: list[str] = Field(default_factory=list)  # 1-2 sample lines in the script's language
    side: list[SideBranch] = Field(default_factory=list)
    origin: Origin | None = None

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
    origin: Origin | None = None


class Persona(BaseModel):
    """Who the agent is and how it speaks — rendered as Role and Personality & Tone."""

    name: str | None = None                       # the agent's name
    company: str | None = None
    tone: list[str] = Field(default_factory=list)       # tone / pacing / length rules
    language: list[str] = Field(default_factory=list)   # language rules (which, when to switch)


class Fact(BaseModel):
    """Reference information the agent uses (prices, plans, numbers, steps) — rendered in <facts>."""

    topic: str = Field(min_length=1)              # short label ("Pricing", "Payment steps")
    text: str = Field(min_length=1)               # compact, exact facts
    script_quote: str | None = None
    needs_input: bool = False                     # added by improvement; the business must supply it
    origin: Origin | None = None


class Journey(BaseModel):
    format: Literal["pulse.journey.v1"] = "pulse.journey.v1"
    objective: str = Field(min_length=1)
    params: list[str] = Field(default_factory=list)   # the script's {{placeholders}} (regex, not LLM)
    persona: Persona | None = None
    facts: list[Fact] = Field(default_factory=list)
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


# The extraction LLM's output: the same shape without improvement-only fields (origin, needs_input) — a
# lean schema keeps provider-native structured output within its grammar limits.
class DraftBranch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    if_: str = Field(alias="if")
    then: str
    goes_to: str
    script_quote: str | None = None
    say: list[str] = Field(default_factory=list)


class DraftBookend(BaseModel):
    agent: str
    done_when: str
    script_quote: str | None = None
    say: list[str] = Field(default_factory=list)


class DraftStage(BaseModel):
    stage: str
    agent: str
    done_when: str
    script_quote: str | None = None
    say: list[str] = Field(default_factory=list)
    side: list[DraftBranch] = Field(default_factory=list)


class DraftGuardrail(BaseModel):
    rule: str
    script_quote: str | None = None


class DraftFact(BaseModel):
    topic: str
    text: str
    script_quote: str | None = None


class JourneyDraft(BaseModel):
    """What the extraction LLM returns. Params and Pulse's standard rules are added by code."""

    objective: str
    persona: Persona | None = None
    facts: list[DraftFact] = Field(default_factory=list)
    opening: DraftBookend | None = None
    funnel: list[DraftStage]
    closing: DraftBookend | None = None
    anytime: list[DraftBranch] = Field(default_factory=list)  # script-derived only
    guardrails: list[DraftGuardrail] = Field(default_factory=list)
    standard_coverage: StandardCoverage = Field(default_factory=StandardCoverage)


def _no_dupes(items: list[str], what: str) -> None:
    seen: set[str] = set()
    dup = [i for i in items if i in seen or seen.add(i)]
    if dup:
        raise ValueError(f"duplicate {what}: {dup[0]!r}")
