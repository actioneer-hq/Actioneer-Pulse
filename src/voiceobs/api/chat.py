"""Global-chat API: conversation CRUD + a streaming (SSE) agent endpoint. The agent answers
over the org's calls with RBAC-scoped tools; replies stream token-by-token with visible
tool-call activity. Conversations are per-user, per-org."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from voiceobs.api.auth import require_csrf
from voiceobs.api.deps import now, session_dep
from voiceobs.api.schemas import ChatMessageIn
from voiceobs.auth import current_membership
from voiceobs.config import resolve_llm
from voiceobs.db.models import ChatMessage, Conversation, Membership
from voiceobs.db.session import get_session
from voiceobs.llm import LLMRole

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/chat")


def _conv(db: Session, cid: str, mem: Membership) -> Conversation:
    c = db.scalar(select(Conversation).where(
        Conversation.id == cid, Conversation.tenant_id == mem.org_id,
        Conversation.created_by == mem.user_id))
    if c is None:
        raise HTTPException(404, "conversation not found")
    return c


@router.get("/conversations")
def list_conversations(
    db: Session = Depends(session_dep), mem: Membership = Depends(current_membership)
) -> dict:
    rows = db.scalars(select(Conversation).where(
        Conversation.tenant_id == mem.org_id, Conversation.created_by == mem.user_id)
        .order_by(Conversation.updated_at.desc())).all()
    return {"items": [{"id": c.id, "title": c.title, "updated_at": c.updated_at} for c in rows]}


@router.post("/conversations")
def create_conversation(
    db: Session = Depends(session_dep), mem: Membership = Depends(current_membership),
    _: None = Depends(require_csrf),
) -> dict:
    c = Conversation(tenant_id=mem.org_id, created_by=mem.user_id, title="New chat")
    db.add(c)
    db.flush()
    return {"id": c.id, "title": c.title}


@router.get("/conversations/{cid}")
def get_conversation(
    cid: str, db: Session = Depends(session_dep),
    mem: Membership = Depends(current_membership),
) -> dict:
    c = _conv(db, cid, mem)
    msgs = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == cid)
                      .order_by(ChatMessage.seq)).all()
    return {"id": c.id, "title": c.title, "messages": [
        {"role": m.role, "content": m.content, "steps": m.steps or []} for m in msgs]}


@router.delete("/conversations/{cid}")
def delete_conversation(
    cid: str, db: Session = Depends(session_dep),
    mem: Membership = Depends(current_membership), _: None = Depends(require_csrf),
) -> dict:
    c = _conv(db, cid, mem)
    db.execute(ChatMessage.__table__.delete().where(ChatMessage.conversation_id == cid))
    db.delete(c)
    return {"status": "ok"}


@router.post("/conversations/{cid}/stream")
def stream_message(
    cid: str, body: ChatMessageIn,
    db: Session = Depends(session_dep), mem: Membership = Depends(current_membership),
    _: None = Depends(require_csrf),
) -> StreamingResponse:
    """Append the user message and stream the agent's reply as SSE. The generator runs after the
    request session closes, so it opens its own session (org_id/user_id captured here)."""
    _conv(db, cid, mem)  # authorize before streaming
    org_id, user_id, text = mem.org_id, mem.user_id, body.text
    return StreamingResponse(_run(cid, org_id, user_id, text),
                             media_type="text/event-stream")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _run(cid: str, org_id: str, user_id: str, text: str) -> Iterator[str]:
    from voiceobs import chat  # local import: keeps api import-time light

    gen = get_session()
    db = next(gen)
    try:
        mem = db.scalar(select(Membership).where(
            Membership.org_id == org_id, Membership.user_id == user_id))
        resolved = resolve_llm(LLMRole.GLOBAL_CHAT)
        if mem is None or resolved is None:
            yield _sse({"type": "error",
                        "error": "global chat model is not configured"})
            return

        history = [{"role": m.role, "content": m.content}
                   for m in db.scalars(select(ChatMessage).where(
                       ChatMessage.conversation_id == cid).order_by(ChatMessage.seq))]
        nxt = (db.scalar(select(func.max(ChatMessage.seq)).where(
            ChatMessage.conversation_id == cid)) or 0) + 1
        db.add(ChatMessage(conversation_id=cid, tenant_id=org_id, seq=nxt,
                           role="user", content=text))
        db.commit()

        content, steps = "", []
        for event in chat.run(db, mem, resolved, history, text):
            if event["type"] == "done":
                content, steps = event["content"], event["steps"]
            yield _sse(event)

        db.add(ChatMessage(conversation_id=cid, tenant_id=org_id, seq=nxt + 1,
                           role="assistant", content=content, steps=steps or None))
        conv = db.get(Conversation, cid)
        if conv is not None:
            if conv.title == "New chat":
                conv.title = text[:60]
            conv.updated_at = now()
        db.commit()
    except Exception as e:
        log.exception("chat stream failed")
        yield _sse({"type": "error", "error": str(e)})
    finally:
        db.close()
