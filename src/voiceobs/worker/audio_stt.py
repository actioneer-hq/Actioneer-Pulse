"""Tier B: reconstruct a transcript for an audio-only call with the BYO STT, and fold it into Turns.

Separated stereo → transcribe each channel independently (clean caller/agent attribution). Diarized
mixed/mono → transcribe the single track once, then attribute each word to caller/agent by which
diarization segment (role) contains its midpoint. Turns are built by walking the audio utterances in
time order and gathering the words that fall inside each — a caller utterance opens a turn, the next
agent utterance closes it. The result populates Turn.caller_transcript / llm_spoken, which is exactly
what the transcript resolver + judge already read (voiceobs/transcript.py)."""

from __future__ import annotations

import io
import logging
import wave

import numpy as np

from voiceobs.core.audio.decode import decode_wav
from voiceobs.core.model import Turn, Utterance
from voiceobs.diarize.client import Diarization
from voiceobs.groundtruth.stt import STTConfig, Word, transcribe

log = logging.getLogger(__name__)


def transcribe_sides(
    stt: STTConfig, wav: bytes, layout: str, diar: Diarization | None,
    channel_map: dict[int, str],
) -> dict[str, list[Word]]:
    """Words per role ('caller'/'agent'). Empty dict on total STT failure."""
    if layout == "separated":
        decoded = decode_wav(wav, channel_map)
        chans, sr = decoded.channels, decoded.sample_rate
        out: dict[str, list[Word]] = {}
        for role in ("caller", "agent"):
            if role in chans:
                tr = transcribe(stt, _mono_wav(chans[role], sr))
                if tr:
                    out[role] = tr.words
        return out

    # mixed / mono — one track. Transcribe once; attribute by diarization role if we have it.
    tr = transcribe(stt, wav)
    if tr is None:
        return {}
    if diar is None or not diar.segments:
        return {"caller": tr.words}  # can't attribute → all caller
    from voiceobs.diarize.roles import assign_roles

    roles = assign_roles(diar)
    caller, agent = [], []
    for w in tr.words:
        (agent if _role_at(diar, roles, (w.start + w.end) / 2) == "agent" else caller).append(w)
    return {"caller": caller, "agent": agent}


def build_turns(utterances: list[Utterance], words: dict[str, list[Word]]) -> list[Turn]:
    """Walk utterances in time order; a caller utterance opens a turn, the next agent utterance
    closes it. Each side's text is the words falling inside that utterance's window."""
    turns: list[Turn] = []
    idx = 0
    pending_caller: tuple[str, float] | None = None  # (text, end_s)
    for u in sorted(utterances, key=lambda u: u.t_start):
        text = _words_in(words.get(u.channel, []), u.t_start, u.t_end)
        if not text:
            continue
        if u.channel == "caller":
            pending_caller = (text, u.t_end)
        elif u.channel == "agent":
            turns.append(Turn(
                turn_index=idx, turn_id=f"t{idx}",
                trigger="endpoint" if pending_caller else "opening",
                transcript=pending_caller[0] if pending_caller else None,
                audio_start_s=pending_caller[1] if pending_caller else None,
                llm_spoken=text, audio_out_start_s=u.t_start,
            ))
            idx += 1
            pending_caller = None
    if pending_caller:  # a trailing caller turn with no agent reply
        turns.append(Turn(turn_index=idx, turn_id=f"t{idx}", trigger="endpoint",
                          transcript=pending_caller[0], audio_start_s=pending_caller[1]))
    return turns


def _words_in(words: list[Word], t0: float, t1: float) -> str:
    return " ".join(w.text.strip() for w in words if t0 <= (w.start + w.end) / 2 <= t1).strip()


def _role_at(diar: Diarization, roles: dict[str, str], t: float) -> str:
    for s in diar.segments:
        if s.start <= t <= s.end:
            return roles.get(s.speaker, "caller")
    return "caller"


def _mono_wav(samples: np.ndarray, sr: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.astype("<i2").tobytes())
    return out.getvalue()
