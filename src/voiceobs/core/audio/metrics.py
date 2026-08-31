"""Layer-1 metrics. Source of truth per side: the **caller** is observed from audio
(VAD utterances); the **agent** is read from spans (its speaking windows), because we
generate the agent and the engine states its timing exactly. join() supplies both."""

from __future__ import annotations

from voiceobs.core.audio import intervals as iv
from voiceobs.core.model import Utterance


def utts_to_intervals(utts: list[Utterance]) -> list[iv.Interval]:
    return iv.merge([(u.t_start, u.t_end) for u in utts])


def talk_ratio(
    caller_utts: list[Utterance], agent_iv: list[iv.Interval], duration_s: float
) -> dict[str, float]:
    """caller / agent speaking fractions + overlap. Caller from audio, agent from spans."""
    if duration_s <= 0:
        return {}
    caller_iv = utts_to_intervals(caller_utts)
    out = {
        "caller": round(iv.total(caller_iv) / duration_s, 4),
        "agent": round(iv.total(agent_iv) / duration_s, 4),
        "overlap": round(iv.total(iv.intersect(caller_iv, agent_iv)) / duration_s, 4),
    }
    return out


def barge_in_count(caller_utts: list[Utterance], agent_iv: list[iv.Interval]) -> int:
    """Caller utterances that start while an agent span says the agent was speaking."""
    return sum(any(s < u.t_start < e for s, e in agent_iv) for u in caller_utts)


def response_latencies(
    caller_utts: list[Utterance], agent_iv: list[iv.Interval]
) -> list[float]:
    """caller-utterance-end -> next agent-speaking start, when the agent replies before
    the caller speaks again."""
    caller = sorted(caller_utts, key=lambda u: u.t_start)
    starts = sorted(s for s, _ in agent_iv)
    out: list[float] = []
    for i, cu in enumerate(caller):
        next_caller = caller[i + 1].t_start if i + 1 < len(caller) else float("inf")
        for s in starts:
            if cu.t_end <= s < next_caller:
                out.append(round(s - cu.t_end, 4))
                break
    return out


def dead_air_s(
    caller_utts: list[Utterance],
    agent_iv: list[iv.Interval],
    duration_s: float,
    min_gap_s: float,
    padding_intervals: list[iv.Interval] | None = None,
) -> float:
    """Time in gaps >= min_gap_s where neither side speaks (caller audio + agent spans).
    Padding (carrier-absent audio) is excluded — a dropped frame is capture, not silence."""
    if duration_s <= 0:
        return 0.0
    speech = iv.merge(utts_to_intervals(caller_utts) + agent_iv)
    gaps = iv.complement(speech, duration_s)
    if padding_intervals:
        gaps = iv.subtract(gaps, iv.merge(padding_intervals))
    return round(sum(e - s for s, e in gaps if (e - s) >= min_gap_s), 4)


def caller_turn_stats(caller_utts: list[Utterance]) -> dict[str, float]:
    """Caller utterance count, mean and max duration (audio side)."""
    durs = [u.t_end - u.t_start for u in caller_utts]
    return {
        "count": len(durs),
        "mean_s": round(sum(durs) / len(durs), 4) if durs else 0.0,
        "max_s": round(max(durs), 4) if durs else 0.0,
    }


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (pct in [0, 100])."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, min(len(s) - 1, round((pct / 100.0) * (len(s) - 1))))]
