"""Word Error Rate — the classic ASR comparison metric. Word-level Levenshtein (insertions +
deletions + substitutions) over the reference length, on normalized text."""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> list[str]:
    """Lowercase, strip punctuation → word tokens. Casing/commas must not count as errors."""
    return _WORD.findall((text or "").lower())


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate of `hypothesis` against `reference` (the producer transcript is the
    reference). 0.0 = identical. Empty reference → 0.0 if hypothesis also empty, else 1.0."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    # Levenshtein distance over word lists (classic DP).
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cost = 0 if r == h else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1] / len(ref)
