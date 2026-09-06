"""The ground-truth reconciliation output: an audio-measured overlay + a list of discrepancies
between what OTLP self-reported and what the audio actually shows.

Design rules (load-bearing):
- Nothing here raises. A check that can't run contributes `unverifiable`, never an error.
- Short mismatches are expected noise: a delta within the tolerance band is `agree` and is NOT
  emitted as a discrepancy. Only beyond-band disagreements are `material`.
- The comparison is delta-only (no confidence scoring). Coverage still GATES: too little real
  audio → `unverifiable`, never `material` — bad capture can't read as "the producer lied."
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Verdict(StrEnum):
    AGREE = "agree"              # within the tolerance band — not surfaced as a discrepancy
    MATERIAL = "material"       # a real disagreement beyond the band
    UNVERIFIABLE = "unverifiable"  # audio couldn't determine this (missing/short audio)


class Dimension(StrEnum):
    VOICE_TO_VOICE = "voice_to_voice"
    ENDPOINTING = "endpointing"
    INTERRUPTION = "interruption"
    TRUNCATION = "truncation"
    TRANSCRIPT = "transcript"
    DEAD_AIR = "dead_air"


class Discrepancy(BaseModel):
    """One reconciled field: what the producer reported vs what the audio measured."""

    model_config = ConfigDict(frozen=True)

    dimension: Dimension
    field: str
    turn_index: int | None = None
    reported: float | str | None = None   # OTLP self-report
    measured: float | str | None = None   # audio ground truth
    delta: float | None = None            # measured - reported (ms), or WER for transcript
    band: float | None = None             # tolerance applied
    verdict: Verdict = Verdict.UNVERIFIABLE
    note: str | None = None


class GroundTruth(BaseModel):
    """Per-turn audio-measured overlay — the values the audio itself yields, independent of spans.
    Everything optional: a field the audio couldn't measure is simply None."""

    model_config = ConfigDict(frozen=True)

    turn_index: int
    caller_stop_s: float | None = None
    agent_start_s: float | None = None
    v2v_audio_ms: float | None = None
    endpointing_audio_ms: float | None = None
    barge_in_audio: bool | None = None
    transcript_audio: str | None = None


class AudioReport(BaseModel):
    """The reconciliation result. `layers_run` records which stages actually produced output, so
    the caller can tell "no discrepancy" (verified agreement) from "couldn't check" (no audio)."""

    model_config = ConfigDict(frozen=True)

    overlay: list[GroundTruth] = Field(default_factory=list)
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    layers_run: list[str] = Field(default_factory=list)  # e.g. ["decode","vad","v2v","transcript"]

    def material(self) -> list[Discrepancy]:
        return [d for d in self.discrepancies if d.verdict == Verdict.MATERIAL]


class TolerancePolicy(BaseModel):
    """Committed default bands ("open config"). A delta within a band is agreement; beyond it is
    material. Coverage below `min_coverage` gates a channel's checks to unverifiable."""

    model_config = ConfigDict(frozen=True)

    first_audio_band_ms: float = 150.0     # span-reported first agent audio vs audio-measured onset
    transcript_wer_band: float = 0.20      # ≤20% word error = agree (STT has its own ~5-10% error)
    min_coverage: float = 0.80             # below this real-audio fraction → unverifiable


DEFAULT_POLICY = TolerancePolicy()
