"""The structured output the judge LLM must return. Fixed enums keep it queryable;
we validate the model's JSON against this and repair/reject anything off-shape."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


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


_ENUM_FALLBACK = {
    "sentiment": Sentiment.NEUTRAL,
    "objective_achieved": Objective.NOT_ACHIEVED,
    "answered_by": AnsweredBy.UNKNOWN,
    "script_adherence": ScriptAdherence.NOT_FOLLOWED,
}


class JudgeOutput(BaseModel):
    """What the LLM returns (only produced for connected calls)."""

    @model_validator(mode="before")
    @classmethod
    def _coerce_enums(cls, data):
        """Best-effort tolerance: lowercase enum strings, and map an out-of-vocabulary value to a
        safe fallback rather than failing the whole judgment (models occasionally emit 'AGENT'
        or 'POOR')."""
        if not isinstance(data, dict):
            return data
        enums = {"sentiment": Sentiment, "objective_achieved": Objective,
                 "answered_by": AnsweredBy, "script_adherence": ScriptAdherence}
        for key, enum in enums.items():
            v = data.get(key)
            if isinstance(v, str):
                low = v.strip().lower()
                valid = {e.value for e in enum}
                data[key] = low if low in valid else _ENUM_FALLBACK[key].value
        return data

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
