"""Interval math over (start, end) tuples, seconds. Used by the audio metrics."""

from __future__ import annotations

Interval = tuple[float, float]


def merge(intervals: list[Interval]) -> list[Interval]:
    """Union of overlapping/adjacent intervals, sorted."""
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for s, e in ordered[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def intersect(a: list[Interval], b: list[Interval]) -> list[Interval]:
    """Overlap between two sorted interval lists."""
    out: list[Interval] = []
    i = j = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if lo < hi:
            out.append((lo, hi))
        i, j = (i + 1, j) if a[i][1] < b[j][1] else (i, j + 1)
    return out


def subtract(base: list[Interval], cut: list[Interval]) -> list[Interval]:
    """base minus cut."""
    out: list[Interval] = []
    for s, e in base:
        segments = [(s, e)]
        for cs, ce in cut:
            nxt: list[Interval] = []
            for bs, be in segments:
                if ce <= bs or cs >= be:
                    nxt.append((bs, be))
                    continue
                if cs > bs:
                    nxt.append((bs, cs))
                if ce < be:
                    nxt.append((ce, be))
            segments = nxt
        out.extend(segments)
    return out


def total(intervals: list[Interval]) -> float:
    return sum(e - s for s, e in intervals)


def complement(intervals: list[Interval], duration: float) -> list[Interval]:
    """Gaps between merged intervals over [0, duration]."""
    gaps: list[Interval] = []
    cursor = 0.0
    for s, e in merge(intervals):
        if s > cursor:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < duration:
        gaps.append((cursor, duration))
    return gaps
