"""Committed default system prompts, one per LLM role — "open config": product behavior the
community reads and PRs, not env or per-deploy. A tenant may override any of these with its own
prompt (LLMConfig.prompt); when null, the default here is used.

POST_CALL_ANALYSIS is live. The two chat prompts are reserved placeholders for the coming chat
interface (not wired yet)."""

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

# Reserved — the chat interface is not built yet.
GLOBAL_CHAT = "You are Pulse's assistant for questions across all of an organization's calls."
PER_CALL_CHAT = "You are Pulse's assistant for questions about a single voice-agent call."

_DEFAULTS: dict[LLMRole, str] = {
    LLMRole.POST_CALL_ANALYSIS: POST_CALL_ANALYSIS,
    LLMRole.GLOBAL_CHAT: GLOBAL_CHAT,
    LLMRole.PER_CALL_CHAT: PER_CALL_CHAT,
}


def default_prompt(role: LLMRole) -> str:
    return _DEFAULTS[role]
