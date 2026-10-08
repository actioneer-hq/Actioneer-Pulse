"""Shared pieces of script improvement: the LLM port, evidence types, item lookup and insertion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from voiceobs.journey.model import END, SAME, AnytimeRule, Journey

# The LLM port: (task instructions, input text, output schema) -> parsed output. The worker binds it to
# the SCRIPT_RSI role (its system prompt + the task); tests pass a fake.
LLM = Callable[[str, str, type[BaseModel]], BaseModel]


@dataclass
class Gap:
    """A recurring unscripted moment (a leaf cluster) the script doesn't cover yet."""

    id: str
    description: str
    category: str                 # branch | anytime | guardrail | fact | escalation
    stage: str | None
    worked: bool                  # did the agent's improvised replies work
    calls: int
    windows: list[str] = field(default_factory=list)  # transcript snippets around the moment


@dataclass
class Failure:
    """A script item the agent didn't follow (a not-followed failure group)."""

    kind: str                     # stage | branch | guardrail | standard | opening | closing
    item: str                     # the journey item's exact name
    calls: int
    windows: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)   # the stage of each failed turn (from the timeline)


def evidence(windows: list[str], worked: bool | None = None) -> str:
    head = {True: "the agent's reply WORKED", False: "the agent's reply did NOT work", None: ""}[worked]
    return "\n\n".join(f"CALL SNIPPET{f' ({head})' if head else ''}:\n{w}" for w in windows[:3])


def valid_goto(j: Journey, goes_to: str) -> str:
    return goes_to if goes_to in {*(s.stage for s in j.funnel), END, SAME} else SAME


def insert_anytime(j: Journey, rule: AnytimeRule) -> None:
    """New anytime situations go before Pulse's standard rules."""
    i = next((n for n, r in enumerate(j.anytime) if r.standard), len(j.anytime))
    j.anytime.insert(i, rule)
