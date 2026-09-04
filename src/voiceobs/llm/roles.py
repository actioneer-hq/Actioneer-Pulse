"""The LLM roles Pulse supports. Each role is an independently-configured model (per-tenant
endpoint/key in the DB) with its own default prompt (committed, in prompts.py).

Only POST_CALL_ANALYSIS is wired today. GLOBAL_CHAT and PER_CALL_CHAT are reserved for the
coming chat interface — the config table and prompt registry already key off role, so adding
them is data + prompt text, not schema."""

from __future__ import annotations

from enum import StrEnum


class LLMRole(StrEnum):
    POST_CALL_ANALYSIS = "post_call_analysis"  # the judge: structured post-call evaluation
    GLOBAL_CHAT = "global_chat"                 # chat across all calls (reserved)
    PER_CALL_CHAT = "per_call_chat"             # chat scoped to one call (reserved)
