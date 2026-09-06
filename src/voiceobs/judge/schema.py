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


class ModelFault(StrEnum):
    NONE = "none"
    ASR = "asr"   # the speech-to-text mis-heard the caller
    LLM = "llm"   # ASR was fine but the LLM reasoned/replied wrongly
    TTS = "tts"   # the spoken output was wrong/garbled/cut
    OTHER = "other"


_ENUM_FALLBACK = {
    "sentiment": Sentiment.NEUTRAL,
    "objective_achieved": Objective.NOT_ACHIEVED,
    "answered_by": AnsweredBy.UNKNOWN,
    "script_adherence": ScriptAdherence.NOT_FOLLOWED,
    "model_fault": ModelFault.OTHER,
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
                 "answered_by": AnsweredBy, "script_adherence": ScriptAdherence,
                 "model_fault": ModelFault}
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
    guardrail_violation: bool = False  # did the call break any of the agent's guardrails
    # which guardrails were broken (short, specific); empty unless guardrail_violation
    guardrail_violation_points: list[str] = Field(default_factory=list)

    # --- failure analysis (root cause) — only populated when is_failure ---
    is_failure: bool = False  # did the call fail to serve its purpose
    root_cause: str | None = None  # the behaviour/bottleneck that caused the failure
    model_fault: ModelFault = ModelFault.NONE  # which model, if any, caused it
    model_fault_detail: str | None = None  # how it faulted (e.g. ASR fine but LLM replied wrongly)
    hallucination: bool = False  # agent asserted something not grounded in context/tools
    hallucination_detail: str | None = None
    suggested_fix: str | None = None  # a concrete remediation (prompt/script/guardrail/infra)

    summary: str | None = None  # <= ~30 words, only when someone spoke

    @model_validator(mode="after")
    def _clean_conditionals(self):
        """Keep conditional keys clean: derived detail only survives when its flag is set."""
        if not self.guardrail_violation:
            self.guardrail_violation_points = []
        if not self.is_failure:  # no failure → no root-cause block
            self.root_cause = self.model_fault_detail = self.hallucination_detail = None
            self.suggested_fix = None
            self.model_fault = ModelFault.NONE
            self.hallucination = False
        if self.model_fault == ModelFault.NONE:
            self.model_fault_detail = None
        if not self.hallucination:
            self.hallucination_detail = None
        return self
