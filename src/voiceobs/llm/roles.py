"""The LLM roles Pulse supports. Each role is an independently-configured model (provider +
model in config.py, key in env) with its own default prompt (committed, in prompts.py).

POST_CALL_ANALYSIS (the judge) and GLOBAL_CHAT are wired. PER_CALL_CHAT and FAILURE_ANALYSIS
are reserved — the config table (config.LLM_ROLES) and prompt registry already key off role,
so activating them is data + prompt text, not schema."""

from __future__ import annotations

from enum import StrEnum


class LLMRole(StrEnum):
    POST_CALL_ANALYSIS = "post_call_analysis"  # the judge: structured post-call evaluation
    GLOBAL_CHAT = "global_chat"                 # chat across all calls
    PER_CALL_CHAT = "per_call_chat"             # chat scoped to one call (reserved)
    FAILURE_ANALYSIS = "failure_analysis"       # failure-board analysis (reserved)


# Interactive roles are user-facing and latency-sensitive: they bypass the gateway's rate-limit
# backoff so a batch backfill (judge/embeddings) can never make a live chat wait behind it.
INTERACTIVE_ROLES = frozenset({LLMRole.GLOBAL_CHAT, LLMRole.PER_CALL_CHAT})
