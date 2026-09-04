"""The ground-truth reconciliation output: an audio-measured overlay + a list of discrepancies
between what OTLP self-reported and what the audio actually shows.

Design rules (load-bearing):
- Nothing here raises. A check that can't run contributes `unverifiable`, never an error.
- Short mismatches are expected noise: a delta within the tolerance band is `agree` and is NOT
  emitted as a discrepancy. Only material, confident disagreements surface.
- Confidence is gated by capture coverage — bad audio can never read as "the producer lied."
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Verdict(StrEnum):
    AGREE = "agree"              # within the tolerance band — not surfaced as a discrepancy
    MINOR = "minor"             # outside the band but small / low-confidence
    MATERIAL = "material"       # a real, confident disagreement
    UNVERIFIABLE = "unverifiable"  # audio couldn't determine this (missing/short/low-coverage)


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
    delta: float | None = None            # measured - reported (numeric dims only)
    band: float | None = None             # tolerance applied
    confidence: float = 0.0               # 0..1, gated by coverage
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
    """Committed default bands + weights ("open config"). A delta within `*_band_ms` is agreement.
    `min_confidence` is the floor below which even a large delta stays `minor` (untrusted)."""

    model_config = ConfigDict(frozen=True)

    v2v_band_ms: float = 150.0
    endpointing_band_ms: float = 120.0
    interruption_overlap_ms: float = 120.0     # min caller/agent overlap to count a real barge-in
    truncation_tail_ms: float = 120.0          # agent speech active in the last N ms = abrupt cut
    transcript_wer_band: float = 0.15          # ≤15% word error = agree
    dead_air_band_s: float = 1.5
    # confidence: coverage below this makes a channel's checks unverifiable
    min_coverage: float = 0.80
    min_confidence: float = 0.50               # material requires at least this confidence


DEFAULT_POLICY = TolerancePolicy()
