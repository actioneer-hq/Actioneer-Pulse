"""LLM roles + their committed default prompts. Per-tenant model/endpoint/key live in the DB
(LLMConfig); the prompts here are open config."""

from __future__ import annotations

from voiceobs.llm.prompts import default_prompt
from voiceobs.llm.roles import LLMRole

__all__ = ["LLMRole", "default_prompt"]
