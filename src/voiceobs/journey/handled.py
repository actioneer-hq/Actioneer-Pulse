"""Did the agent handle each unscripted moment well? The decision model decides (not the LLM, which marked
nearly every improvised reply as fine).

Input: the script journey (what the agent is meant to do) + a window of turns around each moment. One
yes/no per moment: the reply addressed what the customer raised, stayed consistent with the script, and
kept the call moving toward its objective.
"""

from __future__ import annotations

import json

from voiceobs.journey.jev import THRESHOLD, JevAnswers, JevQuestion

WINDOW = 3  # turns either side of the moment


def _window(lines: list[dict], turn: int) -> str:
    near = [ln for ln in lines if abs((ln.get("turn_index") or 0) - turn) <= WINDOW]
    return "\n".join(f"[{ln.get('turn_index')}] {'customer' if ln.get('role') == 'caller' else 'agent'}: "
                     f"{ln.get('text', '')}" for ln in near)


def handled_input(journey_json: dict, moments: list, lines: list[dict]) -> str:
    """`moments` = the LLM's unscripted moments (turn, what)."""
    parts = [f"SCRIPT JOURNEY:\n{json.dumps(journey_json, ensure_ascii=False)}"]
    parts += [f"MOMENT {i} (turn {m.turn}): {m.what}\n{_window(lines, m.turn)}" for i, m in enumerate(moments)]
    return "\n\n".join(parts)


def handled_questions(moments: list) -> list[JevQuestion]:
    return [JevQuestion(key=f"handled:{i}", kind="yes_no",
                        text=f"In MOMENT {i}, the agent's reply handled it well: it addressed what the customer "
                             f"raised ({m.what}), stayed consistent with the SCRIPT JOURNEY, and kept the call "
                             f"moving toward its objective.")
            for i, m in enumerate(moments)]


def to_handled(a: JevAnswers, n: int) -> list[bool | None]:
    return [(float(a[f"handled:{i}"]) >= THRESHOLD) if f"handled:{i}" in a else None for i in range(n)]
