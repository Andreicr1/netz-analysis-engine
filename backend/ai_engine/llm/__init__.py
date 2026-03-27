"""Shared LLM call wrappers — vertical-agnostic."""

from ai_engine.llm.call_openai import call_openai, call_openai_text

__all__ = ["call_openai", "call_openai_text"]
