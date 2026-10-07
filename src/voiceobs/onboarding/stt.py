"""Sarvam STT for uploaded call audio -> timestamped `Utterance`s (speaker = agent | customer).

Two paths, chosen per file:
- **Stereo WAV** (one speaker per channel — what most dialers record): split the channels, find
  speech segments with an energy VAD, and transcribe each segment with Sarvam's REST API.
  Timestamps come from the audio itself; speakers are exact.
- **Anything else** (mono, mp3, m4a...): Sarvam's batch API with diarization (2 speakers), which
  returns per-utterance start/end + speaker id.

Which side is the agent: `agent_channel` = "left" | "right" | "auto". "auto" picks the side that
speaks more — on an outbound call the agent does most of the talking.
"""

from __future__ import annotations

import io
import json
import logging
import tempfile
import time
import wave
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from voiceobs.onboarding.format import Utterance

log = logging.getLogger(__name__)
REST_URL = "https://api.sarvam.ai/speech-to-text"
BATCH_SIZE = 20  # Sarvam batch API: max files per job


@dataclass(frozen=True)
class SttConfig:
    api_key: str
    model: str = "saarika:v2.5"
    language: str = "hi-IN"
    agent_channel: str = "auto"  # left | right | auto
    concurrency: int = 6


class SttError(RuntimeError):
    pass


# ── stereo path ──────────────────────────────────────────────────────────────────────
def read_wav(data: bytes) -> tuple[np.ndarray, int] | None:
    """(samples[frames, channels] int16, sample_rate), or None if not a 16-bit PCM WAV."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getsampwidth() != 2:
                return None
            a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            return a.reshape(-1, w.getnchannels()), w.getframerate()
    except (wave.Error, EOFError):
        return None


def speech_segments(x: np.ndarray, sr: int, *, win: float = 0.05, thr: float = 400.0,
                    min_gap: float = 0.6, min_len: float = 0.25, pad: float = 0.15,
                    max_len: float = 25.0) -> list[tuple[float, float]]:
    """Energy VAD on one channel -> [(start_s, end_s)], split so no segment exceeds `max_len`."""
    n = max(1, int(sr * win))
    if len(x) < n:
        return []
    rms = np.sqrt((x[: len(x) // n * n].reshape(-1, n).astype(float) ** 2).mean(1))
    segs: list[tuple[float, float]] = []
    start = last = None
    for i, voiced in enumerate(rms > thr):
        t = i * win
        if voiced:
            start = t if start is None else start
            last = t + win
        elif start is not None and t - last > min_gap:
            segs.append((start, last))
            start = None
    if start is not None:
        segs.append((start, last))
    dur, out = len(x) / sr, []
    for s, e in segs:
        if e - s < min_len:
            continue
        s, e = max(0.0, s - pad), min(dur, e + pad)
        while e - s > max_len:
            out.append((s, s + max_len))
            s += max_len
        out.append((s, e))
    return out


def _wav_bytes(x: np.ndarray, sr: int) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(x.astype(np.int16).tobytes())
    return b.getvalue()


def _rest_transcribe(cfg: SttConfig, audio: bytes, client: httpx.Client, tries: int = 4) -> str:
    for i in range(tries):
        r = client.post(REST_URL, headers={"api-subscription-key": cfg.api_key},
                        data={"model": cfg.model, "language_code": cfg.language},
                        files={"file": ("segment.wav", audio, "audio/wav")})
        if r.status_code in (429, 500, 502, 503, 504) and i < tries - 1:
            time.sleep(2 ** i)
            continue
        if r.status_code >= 400:
            raise SttError(f"sarvam {r.status_code}: {r.text[:200]}")
        return (r.json().get("transcript") or "").strip()
    raise SttError("sarvam: retries exhausted")


def _agent_index(speech: dict[int, float], agent_channel: str) -> int:
    if agent_channel == "left":
        return 0
    if agent_channel == "right":
        return 1
    return max(speech, key=speech.get)  # auto: the side that talks more


def transcribe_stereo(cfg: SttConfig, samples: np.ndarray, sr: int) -> list[Utterance]:
    segs = {ch: speech_segments(samples[:, ch], sr) for ch in (0, 1)}
    speech = {ch: sum(e - s for s, e in segs[ch]) for ch in (0, 1)}
    agent = _agent_index(speech, cfg.agent_channel)
    jobs = [(ch, s, e) for ch in (0, 1) for s, e in segs[ch]]
    with httpx.Client(timeout=60) as client, ThreadPoolExecutor(cfg.concurrency) as pool:
        texts = list(pool.map(
            lambda j: _rest_transcribe(cfg, _wav_bytes(samples[int(j[1] * sr): int(j[2] * sr), j[0]], sr),
                                       client), jobs))
    out = [Utterance(speaker="agent" if ch == agent else "customer", text=t,
                     start=round(s, 2), end=round(e, 2))
           for (ch, s, e), t in zip(jobs, texts) if t]
    return sorted(out, key=lambda u: u.start)


# ── batch (diarized) path ────────────────────────────────────────────────────────────
def entries_to_utterances(entries: list[dict]) -> list[Utterance]:
    """Sarvam diarized entries -> utterances; the speaker with the most speech is the agent."""
    talk: dict[str, float] = {}
    for e in entries:
        sid = str(e.get("speaker_id"))
        talk[sid] = talk.get(sid, 0.0) + max(0.0, float(e.get("end_time_seconds") or 0)
                                             - float(e.get("start_time_seconds") or 0))
    agent = max(talk, key=talk.get) if talk else None
    out = []
    for e in entries:
        text = (e.get("transcript") or "").strip()
        if not text:
            continue
        start = float(e.get("start_time_seconds") or 0)
        end = e.get("end_time_seconds")
        out.append(Utterance(speaker="agent" if str(e.get("speaker_id")) == agent else "customer",
                             text=text, start=round(start, 2),
                             end=round(max(float(end), start), 2) if end is not None else None))
    return sorted(out, key=lambda u: u.start)


def transcribe_batch(cfg: SttConfig, paths: Iterable[Path]) -> dict[str, list[Utterance] | str]:
    """Diarized transcription for a set of files -> {file name: utterances | error message}."""
    from sarvamai import SarvamAI  # optional dep: the `stt` extra

    paths = list(paths)
    results: dict[str, list[Utterance] | str] = {}
    client = SarvamAI(api_subscription_key=cfg.api_key)
    for i in range(0, len(paths), BATCH_SIZE):
        chunk = paths[i: i + BATCH_SIZE]
        try:
            job = client.speech_to_text_job.create_job(
                model=cfg.model, language_code=cfg.language, with_diarization=True,
                with_timestamps=True, num_speakers=2)
            job.upload_files(file_paths=[str(p) for p in chunk], timeout=300)
            job.start()
            job.wait_until_complete(poll_interval=5, timeout=3600)
            with tempfile.TemporaryDirectory() as out:
                job.download_outputs(output_dir=out)
                for p in chunk:
                    f = Path(out) / f"{p.name}.json"
                    if not f.exists():
                        results[p.name] = "no transcript returned"
                        continue
                    data = json.loads(f.read_text())
                    entries = (data.get("diarized_transcript") or {}).get("entries") or []
                    results[p.name] = entries_to_utterances(entries)
        except Exception as e:  # noqa: BLE001 — one failed batch fails only its files
            log.warning("sarvam batch failed: %s", e)
            for p in chunk:
                results.setdefault(p.name, f"STT failed: {e}")
    return results


def is_stereo_wav(data: bytes) -> bool:
    w = read_wav(data)
    return w is not None and w[0].shape[1] == 2
