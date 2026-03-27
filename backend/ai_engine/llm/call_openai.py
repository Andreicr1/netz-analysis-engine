"""Sync LLM wrapper with JSON retry logic.

Extracted from ``vertical_engines.credit.deep_review.helpers`` so that
non-credit callers (e.g. wealth content routes) can use the same
pattern without a cross-vertical import.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from ai_engine.model_config import get_model
from ai_engine.openai_client import _extract_json_from_text

logger = structlog.get_logger()

_MODEL = get_model("structured")


def _parse_json_payload(raw: str) -> dict[str, Any]:
    """Best-effort JSON extraction."""
    extracted = _extract_json_from_text(raw or "")
    parsed = json.loads(extracted)
    if not isinstance(parsed, dict) or not parsed:
        logger.error("LLM_EMPTY_JSON", parsed=parsed)
        raise ValueError("LLM returned empty or non-dict JSON payload.")
    return parsed


def call_openai(
    system_prompt: str,
    user_content: str,
    *,
    max_tokens: int = 4000,
    model: str | None = None,
) -> dict[str, Any]:
    """Call OpenAI, parse JSON response, retry once on parse failure.

    Minimal shared wrapper matching the ``CallOpenAiFn`` protocol used by
    wealth vertical engines.  Does NOT include budget tracking — callers
    that need cost governance should use the full credit helpers or add
    budget support here when needed.
    """
    from ai_engine.openai_client import create_completion
    from app.core.config import settings

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured.")

    effective_model = model or _MODEL

    call_kwargs: dict[str, Any] = {
        "system_prompt": system_prompt,
        "user_prompt": user_content,
        "model": effective_model,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    base_user_content = user_content
    last_exc: Exception | None = None
    raw = ""

    for attempt in range(2):
        if attempt == 1:
            call_kwargs["user_prompt"] = (
                f"{base_user_content}\n\n"
                "IMPORTANT: Return ONLY one strictly valid JSON object. "
                "Do not include markdown, comments, surrounding prose, or truncated strings."
            )

        result = create_completion(**call_kwargs)
        raw = result.text or ""

        try:
            return _parse_json_payload(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            logger.warning(
                "LLM_JSON_PARSE_RETRY",
                attempt=attempt + 1,
                raw_length=len(raw),
                error=str(exc),
            )

    logger.error(
        "LLM_INVALID_JSON",
        raw_length=len(raw),
        error=str(last_exc) if last_exc else "unknown",
    )
    raise ValueError(f"LLM returned invalid JSON: {last_exc}") from last_exc


def call_openai_text(
    system_prompt: str,
    user_content: str,
    *,
    max_tokens: int = 4000,
    model: str | None = None,
) -> str:
    """Call OpenAI returning raw text (no JSON mode).

    Used for DD Report chapters which generate markdown content.
    """
    from ai_engine.openai_client import create_completion
    from app.core.config import settings

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured.")

    effective_model = model or _MODEL

    result = create_completion(
        system_prompt=system_prompt,
        user_prompt=user_content,
        model=effective_model,
        max_tokens=max_tokens,
        temperature=0.2,
    )

    return result.text or ""
