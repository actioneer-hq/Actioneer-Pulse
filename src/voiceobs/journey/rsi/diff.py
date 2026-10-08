"""Structural diff between two script journeys: what was added, changed, removed or moved, with the
`origin` reason the improvement recorded. Items are matched by their ids (stage name, branch `if`,
guardrail rule, fact topic)."""

from __future__ import annotations

from voiceobs.journey.model import Journey


def _items(j: Journey) -> dict[tuple[str, str], tuple[str | None, dict]]:
    """(section, id) -> (location, item JSON)."""
    out: dict[tuple[str, str], tuple[str | None, dict]] = {}
    for n, s in enumerate(j.funnel):
        out[("stage", s.stage)] = (str(n), s.model_dump(mode="json", by_alias=True, exclude={"side"}))
        for b in s.side:
            out[("branch", b.if_)] = (s.stage, b.model_dump(mode="json", by_alias=True))
    for r in j.anytime:
        out[("escalation" if r.standard else "anytime", r.if_)] = (None, r.model_dump(mode="json", by_alias=True))
    for g in j.guardrails:
        out[("guardrail", g.rule)] = (None, g.model_dump(mode="json"))
    for f in j.facts:
        out[("fact", f.topic)] = (None, f.model_dump(mode="json"))
    for key in ("opening", "closing"):
        b = getattr(j, key)
        if b:
            out[(key, key)] = (None, b.model_dump(mode="json"))
    if j.persona:
        out[("persona", "persona")] = (None, j.persona.model_dump(mode="json"))
    return out


_SITUATIONS = ("branch", "anytime", "escalation")  # a situation moved between sections keeps its id


def _resection(a: dict, b: dict) -> None:
    """Key situations by id alone across stage/any-time, so a move shows as moved, not added + removed."""
    for d in (a, b):
        for key in [k for k in d if k[0] in _SITUATIONS]:
            where, item = d.pop(key)
            d[("situation", key[1])] = (where if key[0] == "branch" else key[0], item)


_META = {"origin", "standard", "in_script"}  # bookkeeping, not content


def _content(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in _META}


def diff(old: Journey, new: Journey) -> list[dict]:
    a, b = _items(old), _items(new)
    _resection(a, b)
    changes = []
    for key in b:
        section, ident = key
        where, item = b[key]
        reason = (item.get("origin") or {}).get("reason")
        if key not in a:
            changes.append({"change": "added", "section": section, "id": ident, "at": where, "reason": reason})
        elif _content(a[key][1]) != _content(item):
            changes.append({"change": "changed", "section": section, "id": ident, "at": where, "reason": reason})
        elif a[key][0] != where:
            changes.append({"change": "moved", "section": section, "id": ident, "from": a[key][0], "at": where,
                            "reason": reason})
    for key in a:
        if key not in b:
            changes.append({"change": "removed", "section": key[0], "id": key[1], "at": a[key][0], "reason": None})
    return changes
