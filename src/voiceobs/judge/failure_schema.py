"""Structured output for the failure-analysis LLM — a second, small model run alongside the
judge to root-cause a call. Kept compact so provider-native structured output accepts it."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, model_validator


class ModelFault(StrEnum):
    NONE = "none"
    ASR = "asr"   # the speech-to-text mis-heard the caller
    LLM = "llm"   # ASR was fine but the LLM reasoned/replied wrongly
    TTS = "tts"   # the spoken output was wrong/garbled/cut
    OTHER = "other"


class FailureAnalysis(BaseModel):
    """Root-cause analysis of one call. The block is only meaningful when is_failure."""

    @model_validator(mode="before")
    @classmethod
    def _coerce_fault(cls, data):
        if isinstance(data, dict):
            v = data.get("model_fault")
            if isinstance(v, str):
                low = v.strip().lower()
                data["model_fault"] = low if low in {e.value for e in ModelFault} else "other"
        return data

    is_failure: bool = False  # did the call fail to serve its purpose
    root_cause: str | None = None  # the behaviour/bottleneck that caused the failure
    model_fault: ModelFault = ModelFault.NONE  # which model, if any, was at fault
    model_fault_detail: str | None = None  # how it faulted (e.g. ASR fine but LLM replied wrongly)
    hallucination: bool = False  # agent asserted something not grounded in context/tools
    hallucination_detail: str | None = None
    suggested_fix: str | None = None  # a concrete remediation (prompt/script/guardrail/infra)

    @model_validator(mode="after")
    def _clean_conditionals(self):
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
