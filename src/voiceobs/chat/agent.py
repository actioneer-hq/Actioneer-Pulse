"""The global-chat agent loop. Emits a stream of events the API relays to the browser as SSE:

    {"type":"tool_call","name":...,"args":...}   the agent decided to use a tool
    {"type":"tool_result","name":...,"summary":...}
    {"type":"token","text":...}                   a piece of the final answer
    {"type":"done","content":...,"steps":[...]}   final answer + the activity to persist
    {"type":"error","error":...}

Tool rounds run non-streaming (so we can act on tool_calls); the final answer is streamed. Never
raises — any failure becomes an `error` event. RBAC comes from the passed-in membership."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from sqlalchemy.orm import Session

from voiceobs.chat import client, tools
from voiceobs.chat.schema_doc import build_system_prompt
from voiceobs.config import ResolvedLLM
from voiceobs.db.models import Membership

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


def run(
    db: Session, mem: Membership, resolved: ResolvedLLM, history: list[dict], user_text: str,
) -> Iterator[dict]:
    system = build_system_prompt(resolved.prompt)
    messages: list[dict] = [{"role": "system", "content": system}, *history,
                            {"role": "user", "content": user_text}]
    steps: list[dict] = []
    try:
        # Tool-calling rounds (non-streaming) until the model wants to answer.
        for _ in range(MAX_TOOL_ROUNDS):
            comp = client.complete(resolved, messages, tools.schemas())
            if not comp.tool_calls:
                break
            messages.append({"role": "assistant", "content": comp.content or None,
                             "tool_calls": [_as_tc(tc) for tc in comp.tool_calls]})
            for tc in comp.tool_calls:
                yield {"type": "tool_call", "name": tc.name, "args": tc.args}
                result = tools.run(db, mem, tc.name, tc.args)
                summary = _summarize(tc.name, result)
                steps.append({"name": tc.name, "args": tc.args, "summary": summary})
                yield {"type": "tool_result", "name": tc.name, "summary": summary}
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result)[:4000]})
        # Final answer, streamed.
        parts: list[str] = []
        for piece in client.stream(resolved, messages):
            parts.append(piece)
            yield {"type": "token", "text": piece}
        yield {"type": "done", "content": "".join(parts), "steps": steps}
    except Exception as e:
        log.exception("chat agent failed")
        yield {"type": "error", "error": str(e)}


def _as_tc(tc: client.ToolCall) -> dict:
    return {"id": tc.id, "type": "function",
            "function": {"name": tc.name, "arguments": json.dumps(tc.args)}}


def _summarize(name: str, result: dict) -> str:
    if "error" in result:
        return result["error"]
    if name == "execute_sql":
        n = result.get("row_count", 0)
        return f"{n} row{'' if n == 1 else 's'}" + (" (truncated)" if result.get("truncated") else "")
    return "done"
