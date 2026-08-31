"""The structured output the judge LLM must return. Fixed enums keep it queryable;
we validate the model's JSON against this and repair/reject anything off-shape."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Sentiment(StrEnum):
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"


class Objective(StrEnum):
    ACHIEVED = "achieved"
    PARTIAL = "partial"
    NOT_ACHIEVED = "not_achieved"


class AnsweredBy(StrEnum):
    HUMAN = "human"
    VOICEMAIL = "voicemail"
    IVR = "ivr"
    UNKNOWN = "unknown"


class ScriptAdherence(StrEnum):
    FOLLOWED = "followed"
    PARTIAL = "partial"
    NOT_FOLLOWED = "not_followed"


class JudgeOutput(BaseModel):
    """What the LLM returns (only produced for connected calls)."""

    sentiment: Sentiment
    objective_achieved: Objective
    answered_by: AnsweredBy
    primary_language: str
    secondary_languages: list[str] = Field(default_factory=list)
    script_adherence: ScriptAdherence
    escalation_requested: bool = False
    callback_requested: bool = False
    callback_time: str | None = None  # only if callback_requested and extractable
    summary: str | None = None  # <= ~30 words, only when someone spoke
