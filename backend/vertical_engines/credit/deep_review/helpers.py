"""Deep review shared helpers — LLM wrapper, utilities, and constants.

Provides both sync (``_call_openai``) and async (``_async_call_openai``)
wrappers.  The async version is the primary implementation; the sync
version exists for backward compatibility with non-async callers.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import structlog

from ai_engine.governance.token_budget import TokenBudgetTracker
from ai_engine.model_config import get_model
from ai_engine.openai_client import _extract_json_from_text

logger = structlog.get_logger()

_MODEL = get_model("structured")


def _parse_json_payload(raw: str) -> dict[str, Any]:
    """Best-effort JSON extraction for deep review stages."""
    extracted = _extract_json_from_text(raw or "")
    parsed = json.loads(extracted)
    if not isinstance(parsed, dict) or not parsed:
        logger.error("DEEP_REVIEW_EMPTY_JSON", parsed=parsed)
        raise ValueError("LLM returned empty or non-dict JSON payload.")
    return parsed


def _call_openai(
    system_prompt: str,
    user_content: str,
    *,
    max_tokens: int = 16000,
    model: str | None = None,
    budget: TokenBudgetTracker | None = None,
    label: str = "",
    stage: str | None = None,
) -> dict[str, Any]:
    """Call OpenAI and parse the JSON response.

    Pre-V3 Hardening (Task 8): Raises on all error paths instead of
    returning silent ``{}``.  Callers MUST handle exceptions.

    Cost Governance: Accepts an optional ``TokenBudgetTracker`` to
    enforce cumulative and per-call token limits.
    """
    from ai_engine.openai_client import create_completion
    from app.core.config import settings

    has_openai = bool(settings.openai_api_key)
    if not has_openai:
        raise ValueError(
            "No AI provider configured — cannot run AI deep review. "
            "Set OPENAI_API_KEY.",
        )

    effective_model = model or _MODEL

    # Pre-flight budget check — abort BEFORE spending tokens
    if budget is not None:
        budget.check_before_call(label=label)

    # Reasoning models (o-series) skip temperature — handled by create_completion
    call_kwargs: dict = {
        "system_prompt": system_prompt,
        "user_prompt": user_content,
        "model": effective_model,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    if stage:
        call_kwargs["stage"] = stage

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

        # ── Token budget tracking ─────────────────────────────────────
        if budget is not None:
            usage = getattr(result.raw, "usage", None)
            input_tok = getattr(usage, "input_tokens", 0) or 0
            output_tok = getattr(usage, "output_tokens", 0) or 0
            budget.record(
                input_tokens=input_tok,
                output_tokens=output_tok,
                label=label if attempt == 0 else f"{label}_json_retry",
            )

        raw = result.text or ""
        try:
            return _parse_json_payload(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            logger.warning(
                "DEEP_REVIEW_JSON_PARSE_RETRY",
                attempt=attempt + 1,
                raw_length=len(raw),
                error=str(exc),
            )

    logger.error(
        "DEEP_REVIEW_INVALID_JSON",
        raw_length=len(raw),
        error=str(last_exc) if last_exc else "unknown",
    )
    raise ValueError(f"LLM returned invalid JSON: {last_exc}") from last_exc


# ---------------------------------------------------------------------------
# Async LLM wrapper — primary async implementation
# ---------------------------------------------------------------------------

async def _async_call_openai(
    system_prompt: str,
    user_content: str,
    *,
    max_tokens: int = 16000,
    model: str | None = None,
    budget: TokenBudgetTracker | None = None,
    label: str = "",
    stage: str | None = None,
) -> dict[str, Any]:
    """Async primary implementation of ``_call_openai``.

    Uses ``async_create_completion`` for non-blocking I/O.  Same return
    type and error behaviour as the sync version.
    """
    from ai_engine.openai_client import async_create_completion
    from app.core.config import settings

    has_openai = bool(settings.openai_api_key)
    if not has_openai:
        raise ValueError(
            "No AI provider configured — cannot run AI deep review. "
            "Set OPENAI_API_KEY.",
        )

    effective_model = model or _MODEL

    if budget is not None:
        budget.check_before_call(label=label)

    call_kwargs: dict = {
        "system_prompt": system_prompt,
        "user_prompt": user_content,
        "model": effective_model,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    if stage:
        call_kwargs["stage"] = stage

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

        result = await async_create_completion(**call_kwargs)

        if budget is not None:
            usage = getattr(result.raw, "usage", None)
            input_tok = getattr(usage, "input_tokens", 0) or 0
            output_tok = getattr(usage, "output_tokens", 0) or 0
            budget.record(
                input_tokens=input_tok,
                output_tokens=output_tok,
                label=label if attempt == 0 else f"{label}_json_retry",
            )

        raw = result.text or ""
        try:
            return _parse_json_payload(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            logger.warning(
                "ASYNC_DEEP_REVIEW_JSON_PARSE_RETRY",
                attempt=attempt + 1,
                raw_length=len(raw),
                error=str(exc),
            )

    logger.error(
        "ASYNC_DEEP_REVIEW_INVALID_JSON",
        raw_length=len(raw),
        error=str(last_exc) if last_exc else "unknown",
    )
    raise ValueError(f"LLM returned invalid JSON: {last_exc}") from last_exc


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------
def _trunc(value: str | float | None, maxlen: int) -> str | None:
    """Truncate a value to *maxlen* chars (safe for VARCHAR columns).

    Non-string values (e.g. float/int from LLM JSON) are coerced to str first.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value[:maxlen] if len(value) > maxlen else value


def _title_case_strategy(value: str | None) -> str | None:
    """Normalise strategy_type to Title Case (e.g. 'ASSET_BACKED_LENDING' -> 'Asset Backed Lending')."""
    if not value:
        return value
    return " ".join(w.capitalize() for w in value.replace("_", " ").split())


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


__all__ = [
    "_MODEL",
    "_call_openai",
    "_async_call_openai",
    "_parse_json_payload",
    "_trunc",
    "_title_case_strategy",
    "_now_utc",
]
