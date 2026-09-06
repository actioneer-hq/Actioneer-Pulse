"""LLM roles + their committed default prompts. Provider/model per role live in config.py
(config.LLM_ROLES) with the key in env; the prompts here are open config."""

from __future__ import annotations

from voiceobs.llm.prompts import default_prompt
from voiceobs.llm.roles import LLMRole

__all__ = ["LLMRole", "default_prompt"]
