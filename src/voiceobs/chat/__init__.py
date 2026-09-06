"""Global-chat agent: an LLM (role=global_chat) that answers questions across an org's calls
using read-only, RBAC-scoped tools, streaming its reply. See agent.run for the event protocol."""

from __future__ import annotations

from voiceobs.chat.agent import run

__all__ = ["run"]
