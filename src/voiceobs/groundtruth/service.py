"""Reconcile OTLP self-report against audio ground truth → a discrepancy list.

Delta-only (no confidence scoring): a field is a discrepancy iff its delta exceeds the band.
Two checks today:
- timing: span-reported first agent audio (`tts_first_audio_at`) vs audio-measured onset
  (`audio_out_start_s`) — both already derived per turn, so this is subtraction.
- transcript: WER of the producer transcript vs a BYO-STT transcription of each channel.

Never raises: every check is wrapped; a failure contributes nothing (or `unverifiable`), never
an error. Short mismatches within a band are agreement and are not emitted."""

from __future__ import annotations

import logging

from voiceobs.core.model import Turn
from voiceobs.groundtruth.report import (
    DEFAULT_POLICY,
    AudioReport,
    Dimension,
    Discrepancy,
    TolerancePolicy,
    Verdict,
)
from voiceobs.groundtruth.stt import STTConfig, transcribe
from voiceobs.groundtruth.text import wer

log = logging.getLogger(__name__)


def reconcile(
    turns: list[Turn],
    caller_wav: bytes | None = None,
    agent_wav: bytes | None = None,
    stt: STTConfig | None = None,
    policy: TolerancePolicy = DEFAULT_POLICY,
) -> AudioReport:
    discrepancies: list[Discrepancy] = []
    layers: list[str] = []
    try:
        d = _timing(turns, policy)
        if d is not None:
            layers.append("timing")
            discrepancies += d
    except Exception:
        log.exception("groundtruth timing check failed")
    try:
        d = _transcript(turns, caller_wav, agent_wav, stt, policy)
        if d is not None:
            layers.append("transcript")
            discrepancies += d
    except Exception:
        log.exception("groundtruth transcript check failed")
    return AudioReport(discrepancies=discrepancies, layers_run=layers)


def _timing(turns: list[Turn], policy: TolerancePolicy) -> list[Discrepancy]:
    """Per-turn: audio-measured agent onset vs span-reported first audio. delta = measured -
    reported (ms); material beyond the band. Turns missing either value contribute nothing."""
    out: list[Discrepancy] = []
    for t in turns:
        reported, measured = t.tts_first_audio_at, t.audio_out_start_s
        if reported is None or measured is None:
            continue
        delta_ms = round((measured - reported) * 1000, 1)
        beyond = abs(delta_ms) > policy.first_audio_band_ms
        out.append(Discrepancy(
            dimension=Dimension.VOICE_TO_VOICE, field="first_audio_ms", turn_index=t.turn_index,
            reported=round(reported * 1000, 1), measured=round(measured * 1000, 1),
            delta=delta_ms, band=policy.first_audio_band_ms,
            verdict=Verdict.MATERIAL if beyond else Verdict.AGREE,
            note=("audio shows the agent spoke later than reported"
                  if delta_ms > 0 else "audio shows the agent spoke earlier than reported")
            if beyond else None,
        ))
    return out


def _transcript(
    turns: list[Turn], caller_wav: bytes | None, agent_wav: bytes | None,
    stt: STTConfig | None, policy: TolerancePolicy,
) -> list[Discrepancy] | None:
    """Call-level WER per channel: producer transcript (reference) vs BYO-STT of the audio.
    None when no STT is configured (transcript check simply doesn't run)."""
    if stt is None:
        return None
    out: list[Discrepancy] = []
    caller_ref = " ".join(t.transcript for t in turns if t.transcript)
    agent_ref = " ".join((t.llm_spoken or t.llm_raw or "") for t in turns).strip()
    for field, ref, wav in (("caller_wer", caller_ref, caller_wav),
                            ("agent_wer", agent_ref, agent_wav)):
        if not ref or not wav:
            continue
        tr = transcribe(stt, wav)
        if tr is None:  # STT down / unusable → unverifiable, never an error
            out.append(Discrepancy(dimension=Dimension.TRANSCRIPT, field=field,
                                   verdict=Verdict.UNVERIFIABLE, note="STT unavailable"))
            continue
        w = round(wer(ref, tr.text), 3)
        beyond = w > policy.transcript_wer_band
        out.append(Discrepancy(
            dimension=Dimension.TRANSCRIPT, field=field,
            reported=ref[:120], measured=tr.text[:120], delta=w,
            band=policy.transcript_wer_band,
            verdict=Verdict.MATERIAL if beyond else Verdict.AGREE,
            note="producer transcript diverges from the audio" if beyond else None,
        ))
    return out or None
