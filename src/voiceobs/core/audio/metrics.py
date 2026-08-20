"""Derived Layer-1 metrics over Utterances. channel_map names decide who is
caller vs agent — never index. join() wraps these into MetricValues."""

from __future__ import annotations

from voiceobs.core.audio import intervals as iv
from voiceobs.core.model import Utterance


def _by_channel(utterances: list[Utterance]) -> dict[str, list[Utterance]]:
    out: dict[str, list[Utterance]] = {}
    for u in utterances:
        out.setdefault(u.channel, []).append(u)
    for v in out.values():
        v.sort(key=lambda u: u.t_start)
    return out


def _spans(utts: list[Utterance]) -> list[iv.Interval]:
    return iv.merge([(u.t_start, u.t_end) for u in utts])


def talk_ratio(utterances: list[Utterance], duration_s: float) -> dict[str, float]:
    """Per-side speaking fraction of the call, plus overlap fraction."""
    if duration_s <= 0:
        return {}
    chans = _by_channel(utterances)
    per_chan = {ch: _spans(utts) for ch, utts in chans.items()}
    out = {ch: round(iv.total(sp) / duration_s, 4) for ch, sp in per_chan.items()}
    if {"caller", "agent"} <= per_chan.keys():
        overlap = iv.intersect(per_chan["caller"], per_chan["agent"])
        out["overlap"] = round(iv.total(overlap) / duration_s, 4)
    return out


def barge_in_count(
    utterances: list[Utterance], caller: str = "caller", agent: str = "agent"
) -> int:
    """Caller utterances that start while the agent is speaking."""
    chans = _by_channel(utterances)
    agent_iv = _spans(chans.get(agent, []))
    return sum(
        any(s < u.t_start < e for s, e in agent_iv) for u in chans.get(caller, [])
    )


def response_latencies(
    utterances: list[Utterance], caller: str = "caller", agent: str = "agent"
) -> list[float]:
    """Caller-end -> next-agent-start gaps, only when the agent replies before the
    caller speaks again."""
    chans = _by_channel(utterances)
    caller_utts, agent_utts = chans.get(caller, []), chans.get(agent, [])
    out: list[float] = []
    for i, cu in enumerate(caller_utts):
        next_caller = caller_utts[i + 1].t_start if i + 1 < len(caller_utts) else float("inf")
        for au in agent_utts:
            if cu.t_end <= au.t_start < next_caller:
                out.append(round(au.t_start - cu.t_end, 4))
                break
    return out


def dead_air_s(
    utterances: list[Utterance],
    duration_s: float,
    min_gap_s: float,
    padding_intervals: list[iv.Interval] | None = None,
) -> float:
    """Time in gaps >= min_gap_s where neither channel speaks. Padding (carrier-
    absent audio) is excluded — a dropped frame is capture, not silence."""
    if duration_s <= 0:
        return 0.0
    gaps = iv.complement([(u.t_start, u.t_end) for u in utterances], duration_s)
    if padding_intervals:
        gaps = iv.subtract(gaps, iv.merge(padding_intervals))
    return round(sum(e - s for s, e in gaps if (e - s) >= min_gap_s), 4)


def turn_stats(utterances: list[Utterance]) -> dict[str, dict[str, float]]:
    """Per-channel utterance count, mean and max duration."""
    out: dict[str, dict[str, float]] = {}
    for ch, utts in _by_channel(utterances).items():
        durs = [u.t_end - u.t_start for u in utts]
        out[ch] = {
            "count": len(durs),
            "mean_s": round(sum(durs) / len(durs), 4) if durs else 0.0,
            "max_s": round(max(durs), 4) if durs else 0.0,
        }
    return out


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (pct in [0, 100])."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, min(len(s) - 1, round((pct / 100.0) * (len(s) - 1))))]
