"""Ground-truth audio reconciliation service.

Takes the OTLP-derived analysis + the two mono tracks (caller + agent) and independently
re-derives the truth, emitting a ground-truth overlay + a discrepancy list. It never raises —
short mismatches are expected noise (tolerance bands), and any stage that can't run degrades to
`unverifiable` rather than failing the call.

This module owns everything audio; `core` stays pure and span-only. Transcript verification is
BYO STT (see groundtruth.stt).
"""

from __future__ import annotations

from voiceobs.groundtruth.report import (
    DEFAULT_POLICY,
    AudioReport,
    Dimension,
    Discrepancy,
    GroundTruth,
    TolerancePolicy,
    Verdict,
)
from voiceobs.groundtruth.service import reconcile
from voiceobs.groundtruth.stt import STTConfig, resolve_stt, transcribe

__all__ = [
    "DEFAULT_POLICY",
    "AudioReport",
    "Dimension",
    "Discrepancy",
    "GroundTruth",
    "STTConfig",
    "TolerancePolicy",
    "Verdict",
    "reconcile",
    "resolve_stt",
    "transcribe",
]
