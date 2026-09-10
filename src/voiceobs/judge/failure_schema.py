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


class LLMFaultKind(StrEnum):
    RESPONSE = "response"      # what it said to the caller (text)
    EMOTION = "emotion"        # emotion/style tags handed to TTS
    TOOL_CALL = "tool_call"    # wrong tool / args / timing / missing call
    INTERPRET = "interpret"    # misread the caller's intent/state


class LLMCorrection(BaseModel):
    """One corrected agent turn — the raw material for SFT/DPO training data. Only emitted when
    model_fault is LLM. `observed`/`corrected` are the LITERAL turn content (no narration) so the
    pair is directly usable as (rejected, chosen); the reasoning lives in `rationale`."""

    turn_id: str                          # the turn this applies to (from the transcript)
    kind: LLMFaultKind
    observed: str                         # what the agent actually emitted that turn
    corrected: str                        # what it should have emitted — the SFT target
    corrected_tool: str | None = None     # when kind is tool_call
    corrected_args: dict | None = None    # when kind is tool_call
    rationale: str | None = None          # why the correction is right


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
    # Per-turn corrected actions — training data. Only meaningful when model_fault is LLM.
    llm_corrections: list[LLMCorrection] = []

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
        if self.model_fault != ModelFault.LLM:  # corrections only apply to LLM faults
            self.llm_corrections = []
        return self
