"""Per-call chat API: a chat thread scoped to one call. One persistent thread per (call, user).

Reuses the global chat machinery — the same agent loop, SSE event protocol, and ChatMessage
persistence — differing only in the SYSTEM PROMPT: instead of the org-wide SQL/pgvector prompt, it
dumps this call's transcript + metrics + judgment and points the agent at the `events` table via
`execute_sql` (see chat/per_call.py). Model is the PER_CALL_CHAT role."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from voiceobs.api.auth import require_csrf
from voiceobs.api.deps import now, session_dep
from voiceobs.api.schemas import ChatMessageIn
from voiceobs.auth import current_membership, get_scoped_call
from voiceobs.config import resolve_llm
from voiceobs.db.models import Call, ChatMessage, Conversation, Membership, Organization
from voiceobs.db.session import get_session, use_org_schema
from voiceobs.llm import LLMRole

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/calls")


def _thread(db: Session, call: Call, mem: Membership) -> Conversation:
    """The caller's single chat thread for this call, created on first use."""
    conv = db.scalar(select(Conversation).where(
        Conversation.call_id == call.id, Conversation.created_by == mem.user_id))
    if conv is None:
        conv = Conversation(call_id=call.id, created_by=mem.user_id,
                            title=f"Call {call.external_call_id[:24]}")
        db.add(conv)
        db.flush()
    return conv


@router.get("/{call_id}/chat")
def get_call_chat(
    call: Call = Depends(get_scoped_call),
    db: Session = Depends(session_dep), mem: Membership = Depends(current_membership),
) -> dict:
    conv = _thread(db, call, mem)
    msgs = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conv.id)
                      .order_by(ChatMessage.seq)).all()
    return {"id": conv.id, "messages": [
        {"role": m.role, "content": m.content, "steps": m.steps or []} for m in msgs]}


@router.post("/{call_id}/chat/stream")
def stream_call_chat(
    body: ChatMessageIn,
    call: Call = Depends(get_scoped_call),
    db: Session = Depends(session_dep), mem: Membership = Depends(current_membership),
    _: None = Depends(require_csrf),
) -> StreamingResponse:
    """Append the user message and stream the per-call agent's reply as SSE. The generator runs
    after the request session closes, so it re-pins the org schema and re-resolves the call."""
    _thread(db, call, mem)  # ensure the thread exists / authorize before streaming
    org_slug = db.scalar(select(Organization.slug))  # one org per schema
    return StreamingResponse(
        _run(call.external_call_id, org_slug, mem.user_id, body.text),
        media_type="text/event-stream")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _run(call_ext_id: str, org_slug: str, user_id: str, text: str) -> Iterator[str]:
    from voiceobs import chat
    from voiceobs.chat.per_call import build_per_call_prompt

    gen = get_session()
    db = next(gen)
    try:
        use_org_schema(db, org_slug)  # this session skipped request auth, so pin the schema
        mem = db.scalar(select(Membership).where(Membership.user_id == user_id))
        call = db.scalar(select(Call).where(Call.external_call_id == call_ext_id))
        resolved = resolve_llm(LLMRole.PER_CALL_CHAT)
        if mem is None or call is None or resolved is None:
            yield _sse({"type": "error", "error": "per-call chat model is not configured"})
            return
        conv = _thread(db, call, mem)

        history = [{"role": m.role, "content": m.content}
                   for m in db.scalars(select(ChatMessage).where(
                       ChatMessage.conversation_id == conv.id).order_by(ChatMessage.seq))]
        nxt = (db.scalar(select(func.max(ChatMessage.seq)).where(
            ChatMessage.conversation_id == conv.id)) or 0) + 1
        db.add(ChatMessage(conversation_id=conv.id, seq=nxt, role="user", content=text))
        db.commit()

        system = build_per_call_prompt(db, call, resolved.prompt)
        content, steps = "", []
        for event in chat.run(db, mem, resolved, history, text, system=system):
            if event["type"] == "done":
                content, steps = event["content"], event["steps"]
            yield _sse(event)

        db.add(ChatMessage(conversation_id=conv.id, seq=nxt + 1, role="assistant",
                           content=content, steps=steps or None))
        conv.updated_at = now()
        db.commit()
    except Exception as e:
        log.exception("per-call chat stream failed")
        yield _sse({"type": "error", "error": str(e)})
    finally:
        db.close()
