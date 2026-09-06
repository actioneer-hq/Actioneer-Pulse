"""Committed default system prompts, one per LLM role — "open config": product behavior the
community reads and PRs, not env or per-deploy. `default_prompt(role)` returns the text used for
that role's model (configured in config.LLM_ROLES).

POST_CALL_ANALYSIS (judge) and GLOBAL_CHAT are live. PER_CALL_CHAT and FAILURE_ANALYSIS are
reserved placeholders."""

from __future__ import annotations

from voiceobs.llm.roles import LLMRole

# The post-call judge. `{schema}` is filled with the JudgeOutput schema at send time.
POST_CALL_ANALYSIS = (
    "You are a call-quality judge for outbound voice-agent calls. You are given the "
    "agent's script and the call transcript. Return ONLY a JSON object matching this "
    "schema, no prose:\n"
    "{schema}\n\n"
    "Rules:\n"
    "- primary_language is the most-spoken language; secondary_languages lists the rest.\n"
    "- callback_time is filled only if callback_requested and a time is stated, else null.\n"
    "- summary is at most 30 words, and only when a human or voicemail actually spoke; "
    "otherwise null.\n"
    "- Use only the allowed enum values."
)

GLOBAL_CHAT = "You are Pulse's assistant for questions across all of an organization's calls."
PER_CALL_CHAT = "You are Pulse's assistant for questions about a single voice-agent call."
# Reserved — the failure-analysis flow is not built yet.
FAILURE_ANALYSIS = "You analyse voice-agent calls for failures and their likely causes."

_DEFAULTS: dict[LLMRole, str] = {
    LLMRole.POST_CALL_ANALYSIS: POST_CALL_ANALYSIS,
    LLMRole.GLOBAL_CHAT: GLOBAL_CHAT,
    LLMRole.PER_CALL_CHAT: PER_CALL_CHAT,
    LLMRole.FAILURE_ANALYSIS: FAILURE_ANALYSIS,
}


def default_prompt(role: LLMRole) -> str:
    return _DEFAULTS[role]
