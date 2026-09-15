"""Training-data export — turn each call's `llm_corrections` (per-turn corrected agent actions,
produced by the failure-analysis LLM when model_fault == llm) into downloadable JSONL:

- **sft**  — chat `messages[]` ending in the corrected assistant turn (the single training target).
- **dpo**  — same prompt context; `chosen` = corrected, `rejected` = observed (offline preference RL).

Scoped exactly like the Clusters/boards reads (schema = tenant, RBAC visible_agent_ids, optional
agent_id + range). Streamed so a large agent doesn't buffer in memory. Every row carries a `meta`
block with `gt_source: "judge_unverified"` and a `recoverable` flag — these are the judge's claims,
not human-verified ground truth.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from voiceobs.api.deps import session_dep
from voiceobs.auth import current_membership, visible_agent_ids
from voiceobs.db.models import Call, Judgment, Membership, Prompt, Turn

router = APIRouter(prefix="/v1/export")

_RANGES = {"24h": timedelta(hours=24), "7d": timedelta(days=7),
           "30d": timedelta(days=30), "90d": timedelta(days=90)}
_FORMATS = ("sft", "dpo")
_DIALECTS = ("trl", "openai")


def _scope(stmt: Select, db: Session, mem: Membership, agent_id: str | None,
           range_key: str | None) -> Select:
    ids = visible_agent_ids(db, mem)
    if ids is not None:
        stmt = stmt.where(Call.agent_id.in_(ids))
    if agent_id:
        stmt = stmt.where(Call.agent_id == agent_id)
    if range_key and range_key in _RANGES:
        since = datetime.now(UTC) - _RANGES[range_key]
        stmt = stmt.where(func.coalesce(Call.started_at, Call.created_at) >= since)
    return stmt


def _outcome(objective_achieved: str | None) -> str:
    """Terminal-objective label: the call's final outcome, for downstream filtering/weighting.
    `yes` → achieved (good), `no` → failed (bad), anything else → uncertain."""
    return {"yes": "achieved", "no": "failed"}.get(objective_achieved or "", "uncertain")


def _corrected_message(c: dict) -> dict:
    """The corrected assistant turn as an OpenAI-style message. A structured tool target whenever the
    correction carries `corrected_tool` (the judge tags `kind` loosely, so key off the tool, not the
    kind); otherwise a plain-text target."""
    if c.get("corrected_tool"):
        return {
            "role": "assistant", "content": None,
            "tool_calls": [{
                "type": "function",
                "function": {"name": c["corrected_tool"],
                             "arguments": json.dumps(c.get("corrected_args") or {})},
            }],
        }
    return {"role": "assistant", "content": c.get("corrected") or ""}


def _conversation(turns: list[Turn]) -> list[dict]:
    """Flatten Turn rows into an alternating message list. A Turn is one exchange (caller side +
    agent side); either may be absent (opening turn has no caller). Ordered by turn_index."""
    convo: list[dict] = []
    for t in turns:
        if t.caller_transcript:
            convo.append({"role": "user", "content": t.caller_transcript})
        if t.llm_spoken:
            convo.append({"role": "assistant", "content": t.llm_spoken})
    return convo


def _fault_pos(convo: list[dict], observed: str | None) -> int:
    """Index in `convo` of the faulty ASSISTANT message the correction replaces. A correction is
    always an agent action, so match `observed` against assistant turns (turn_id from the judge is
    unreliable). Returns len(convo) when it can't be located (→ full context, target appended)."""
    obs = (observed or "").strip()
    if obs:
        needle = obs[:60]
        for i, m in enumerate(convo):
            if m["role"] == "assistant" and (needle in m["content"] or m["content"][:60] in obs):
                return i
    return len(convo)


def _context(script: str | None, convo: list[dict], pos: int) -> list[dict]:
    """system(script) + the conversation up to (not including) the faulty assistant turn. The model
    must produce the corrected assistant turn as the next message."""
    return [{"role": "system", "content": script or ""}, *convo[:pos]]


def _sft_row(ctx: list[dict], c: dict, meta: dict | None) -> dict:
    # Universal chat format — identical across OpenAI / Fireworks / Baseten / Together / Tinker.
    row = {"messages": ctx + [_corrected_message(c)]}
    return {**row, "meta": meta} if meta else row


def _dpo_row(ctx: list[dict], c: dict, observed: str, dialect: str, meta: dict | None) -> dict:
    chosen = _corrected_message(c)
    rejected = {"role": "assistant", "content": observed}
    if dialect == "openai":
        # OpenAI/Azure preference format: preferred/non_preferred are the last-assistant arrays.
        row = {"input": {"messages": ctx}, "preferred_output": [chosen],
               "non_preferred_output": [rejected]}
    else:  # trl — HF TRL / axolotl / Tinker cookbook / Together
        row = {"prompt": ctx, "chosen": [chosen], "rejected": [rejected]}
    return {**row, "meta": meta} if meta else row


def _rows(db: Session, mem: Membership, fmt: str, dialect: str, include_meta: bool,
          agent_id: str | None, range_key: str | None) -> Iterator[str]:
    stmt = _scope(
        select(Call, Judgment).join(Judgment, Judgment.call_id == Call.id)
        .where(Judgment.model_fault == "llm"),
        db, mem, agent_id, range_key,
    )
    for call, j in db.execute(stmt).all():
        corrections = j.llm_corrections or []
        if not corrections:
            continue
        script = db.scalar(select(Prompt.text).where(Prompt.id == call.prompt_id)) if call.prompt_id else None
        turns = list(db.scalars(
            select(Turn).where(Turn.call_id == call.id).order_by(Turn.turn_index)))
        convo = _conversation(turns)
        recoverable = j.objective_achieved != "yes"  # controllable failure with a produced fix
        outcome = _outcome(j.objective_achieved)  # terminal label for filtering/weighting downstream
        for c in corrections:
            if not (c.get("corrected") or c.get("corrected_tool")):
                continue  # nothing to train toward
            ctx = _context(script, convo, _fault_pos(convo, c.get("observed")))
            meta = {
                "call_id": call.external_call_id, "agent_id": call.agent_id,
                "turn_id": c.get("turn_id"), "kind": c.get("kind"),
                "fault_dim": j.model_fault, "recoverable": recoverable,
                "outcome": outcome, "gt_source": "judge_unverified",
            } if include_meta else None
            row = (_sft_row(ctx, c, meta) if fmt == "sft"
                   else _dpo_row(ctx, c, c.get("observed") or "", dialect, meta))
            yield json.dumps(row)


@router.get("/training")
def export_training(
    mem: Membership = Depends(current_membership),
    db: Session = Depends(session_dep),
    format: str = Query("sft"),
    dialect: str = Query("trl"),
    meta: bool = Query(False),
    agent_id: str | None = None,
    range: str | None = None,
) -> StreamingResponse:
    """`format`=sft|dpo, `dialect`=trl|openai (only DPO differs; SFT is universal). `meta` adds a
    provenance block (off by default so rows are drop-in for OpenAI's strict validator)."""
    if format not in _FORMATS:
        raise HTTPException(400, f"format must be one of {_FORMATS}")
    if dialect not in _DIALECTS:
        raise HTTPException(400, f"dialect must be one of {_DIALECTS}")

    def stream() -> Iterator[str]:
        for line in _rows(db, mem, format, dialect, meta, agent_id, range):
            yield line + "\n"

    fname = f"pulse-{format}-{dialect}-{agent_id or 'all'}.jsonl"
    return StreamingResponse(
        stream(), media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
