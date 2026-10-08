"""Script improvement runs: gather the evidence for a script version from the DB and run journey/rsi.

Evidence:
- gaps: unscripted leaf clusters the decision model placed as "none of these" (not off-topic), with
  transcript snippets around their moments; `worked` = the pool where the agent's reply worked
- failures: not-followed failure groups of the version's judged calls, with snippets around them
- reach: how many judged calls reached each stage
Called from the backfill worker loop (like journey extraction); one pending run at a time.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.db.models import Call, Judgment, Moment, MomentCluster, ScriptProposal

log = logging.getLogger(__name__)
_WINDOW = 3          # turns either side of a moment
_SNIPPETS = 3        # snippets per gap / failure


def _now() -> datetime:
    return datetime.now(UTC)


def _snippet(db: Session, m: Moment) -> str:
    from voiceobs.journey.decide import render_input
    from voiceobs.transcript import resolve

    lines = resolve(db, db.get(Call, m.call_id)).get("lines") or []
    near = [ln for ln in lines if abs((ln.get("turn_index") or 0) - m.turn) <= _WINDOW]
    return render_input(None, {"lines": near}).split("TRANSCRIPT:\n", 1)[-1]


def evidence(db: Session, agent_id: str, prompt_id: str):
    """(gaps, failures, reach) for one script version."""
    from voiceobs.journey.rsi.common import Failure, Gap

    moments = list(db.scalars(select(Moment).where(Moment.agent_id == agent_id, Moment.prompt_id == prompt_id)))
    gaps = []
    for c in db.scalars(select(MomentCluster).where(
            MomentCluster.agent_id == agent_id, MomentCluster.prompt_id == prompt_id,
            MomentCluster.kind == "unscripted", MomentCluster.is_leaf.is_(True))):
        p = c.placement or {}
        if not p.get("category") or p["category"] == "off_topic" or p.get("match"):
            continue
        members = [m for m in moments if m.kind == "unscripted" and m.cluster_key == c.cluster_key
                   and bool(m.handled) == (c.item == "handled")]
        gaps.append(Gap(id=f"{c.item}:{c.cluster_key}", description=c.description or c.name or "",
                        category=p["category"], stage=p.get("stage"), worked=c.item == "handled", calls=c.size,
                        windows=[_snippet(db, m) for m in members[:_SNIPPETS]]))

    rows = db.execute(select(Judgment.journey).join(Call, Call.id == Judgment.call_id).where(
        Call.agent_id == agent_id, Call.prompt_id == prompt_id, Judgment.journey.isnot(None))).scalars().all()
    calls: dict[tuple[str, str], int] = defaultdict(int)
    stages: dict[tuple[str, str], list[str]] = defaultdict(list)  # stage of each failed turn
    reach: dict[str, int] = defaultdict(int)
    order: list[str] = []
    for r in rows:
        for s in r.get("stages") or []:
            if s["stage"] not in order:
                order.append(s["stage"])
            reach[s["stage"]] += bool(s.get("reached"))
        at = {e["turn"]: e["item"] for e in r.get("timeline") or []}
        for f in r.get("failures") or []:
            if f.get("cause") == "not_followed" and f.get("kind") != "unscripted":
                calls[(f["kind"], f["item"])] += 1
                turn = f.get("target_turn") if f.get("target_turn") is not None else (f.get("turns") or [None])[0]
                if turn in at:
                    stages[(f["kind"], f["item"])].append(at[turn])
    failures = [Failure(kind=k, item=i, calls=n, stages=stages[(k, i)], windows=[
        _snippet(db, m) for m in [m for m in moments if m.kind == k and m.item == i][:_SNIPPETS]])
        for (k, i), n in sorted(calls.items(), key=lambda kv: -kv[1])]
    return gaps, failures, [{"stage": s, "reached": reach[s]} for s in order]


def bound_llm():
    """The SCRIPT_RSI role as the journey/rsi LLM port: system prompt + task + schema."""
    from voiceobs.config import resolve_llm
    from voiceobs.journey.llm import structured
    from voiceobs.llm import LLMRole

    resolved = resolve_llm(LLMRole.SCRIPT_RSI)
    if resolved is None:
        return None

    def call(task: str, text: str, schema):
        system = f"{resolved.prompt}\n\n{task}\n\nSchema:\n{json.dumps(schema.model_json_schema())}"
        return structured(resolved, [{"role": "system", "content": system}, {"role": "user", "content": text}],
                          schema)

    return call


def run_one(db: Session, row: ScriptProposal, llm=None, decision=None) -> None:
    from voiceobs.journey.decide import resolve_decision
    from voiceobs.journey.model import Journey
    from voiceobs.journey.rsi.run import improve
    from voiceobs.worker.journey import ready_journey

    try:
        found = ready_journey(db, row.prompt_id)
        llm, decision = llm or bound_llm(), decision or resolve_decision()
        if not found or llm is None or decision is None:
            raise RuntimeError("needs a ready script journey, the SCRIPT_RSI LLM and the decision model")
        gaps, failures, reach = evidence(db, row.agent_id, row.prompt_id)
        result = improve(Journey.model_validate(found[1]), gaps, failures, reach, decision, llm, row.id)
        row.result = {**result, "gaps": len(gaps), "failures": len(failures)}
        row.status, row.error = "ready", None
    except Exception as e:  # noqa: BLE001 — record, never crash the worker loop
        log.warning("script improvement %s failed: %s", row.id, e)
        row.status, row.error = "failed", str(e)[:2000]
    row.updated_at = _now()


def run_pending(db: Session) -> int:
    row = db.scalar(select(ScriptProposal).where(ScriptProposal.status == "pending")
                    .order_by(ScriptProposal.created_at))
    if row is None:
        return 0
    row.status, row.updated_at = "running", _now()
    db.commit()
    run_one(db, row)
    db.commit()
    return 1

