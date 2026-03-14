"""
OpenAI Provider Layer — direct OpenAI API client with Azure OpenAI fallback.

Centralises all OpenAI SDK usage behind two thin helpers:
  • ``create_completion()``  — Responses API (``client.responses.create``)
  • ``create_embedding()``   — text-embedding-3-large (3 072 dims)

**Provider strategy — OpenAI first, Azure OpenAI fallback:**
  When ``OPENAI_API_KEY`` is set, all calls go to OpenAI direct API.
  If a call fails (auth error, rate limits, server errors) and
  ``AZURE_OPENAI_ENDPOINT`` + ``AZURE_OPENAI_KEY`` are configured,
  the request is automatically retried against Azure OpenAI.

Uses the **Responses API** (``/v1/responses``) instead of the legacy
Chat Completions endpoint.  Model routing: gpt-5.1 for memo/narrative
(IC-grade inference); gpt-4.1 for structured/JSON stages; o4-mini for
critic escalation.  Reasoning models (o-series) automatically skip
temperature and accept reasoning_effort.  gpt-5.x models support
both temperature and optional reasoning_effort.

Includes exponential-backoff retry (max 5 attempts) with jitter for
rate-limit (429) and transient server errors (>=500).

Environment:
  OPENAI_API_KEY              — primary provider (direct OpenAI)
  AZURE_OPENAI_ENDPOINT       — fallback provider (Azure OpenAI)
  AZURE_OPENAI_KEY            — fallback provider (Azure OpenAI)
  OPENAI_MODEL_INTELLIGENCE   — default ``gpt-4.1``
  OPENAI_EMBEDDING_MODEL      — default ``text-embedding-3-large``
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from httpx import TimeoutException as HttpxTimeout
from openai import APIStatusError, AsyncAzureOpenAI, AsyncOpenAI, AzureOpenAI, OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton clients — both may be active for provider-level fallback
# ---------------------------------------------------------------------------
_client: OpenAI | None = None
_fallback_client: OpenAI | None = None
_foundry_client: OpenAI | None = None

_use_azure_openai: bool = False
_fallback_checked: bool = False


def _get_client() -> OpenAI:
    """Return the **primary** module-level ``OpenAI`` or ``AzureOpenAI`` client.

    Provider priority:
      1. Direct OpenAI (``OPENAI_API_KEY`` set)
      2. Azure OpenAI (``AZURE_OPENAI_ENDPOINT`` + ``AZURE_OPENAI_KEY`` set)

    The module-level flag ``_use_azure_openai`` is set so that downstream
    code can branch on provider when necessary (e.g. Responses API
    differences).
    """
    global _client, _use_azure_openai
    if _client is not None:
        return _client

    # ── Priority 1: Direct OpenAI ─────────────────────────────────────
    api_key = settings.OPENAI_API_KEY
    if api_key:
        _use_azure_openai = False
        _client = OpenAI(api_key=api_key, timeout=600.0)
        logger.info("AI_PROVIDER=openai (direct API key)")
        return _client

    # ── Priority 2: Azure OpenAI ──────────────────────────────────────
    azure_endpoint = settings.AZURE_OPENAI_ENDPOINT
    azure_key = settings.AZURE_OPENAI_KEY
    if azure_endpoint and azure_key:
        _use_azure_openai = True
        _client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_key,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            timeout=600.0,
        )
        logger.info("AI_PROVIDER=azure_openai endpoint=%s", azure_endpoint)
        return _client

    raise ValueError(
        "No AI provider configured. Set OPENAI_API_KEY (direct) "
        "or AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_KEY (Azure OpenAI)."
    )


def _get_fallback_client() -> OpenAI | None:
    """Return the **fallback** provider client, or ``None`` if unavailable.

    When the primary is direct OpenAI, the fallback is Azure OpenAI
    (if ``AZURE_OPENAI_ENDPOINT`` and ``AZURE_OPENAI_KEY`` are set).
    When the primary is already Azure OpenAI (direct key missing),
    no fallback is offered.
    """
    global _fallback_client, _fallback_checked
    if _fallback_checked:
        return _fallback_client
    _fallback_checked = True

    # Fallback only meaningful when primary is direct OpenAI
    if _use_azure_openai:
        return None

    azure_endpoint = settings.AZURE_OPENAI_ENDPOINT
    azure_key = settings.AZURE_OPENAI_KEY
    if azure_endpoint and azure_key:
        _fallback_client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_key,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            timeout=600.0,
        )
        logger.info("AI_FALLBACK_READY=azure_openai endpoint=%s", azure_endpoint)
        return _fallback_client

    logger.info("AI_FALLBACK_NONE — Azure OpenAI not configured")
    return None


def _get_foundry_client() -> OpenAI:
    """Return an ``OpenAI``-compatible client pointing to Azure AI Foundry.

    Used for serverless MaaS models (DeepSeek-R1, Mistral, etc.)
    via the Chat Completions endpoint.
    """
    global _foundry_client
    if _foundry_client is not None:
        return _foundry_client

    endpoint = settings.AZURE_AI_FOUNDRY_ENDPOINT
    key = settings.AZURE_AI_FOUNDRY_KEY
    if not endpoint or not key:
        raise ValueError(
            "AZURE_AI_FOUNDRY_ENDPOINT and AZURE_AI_FOUNDRY_KEY must be set "
            "to use Azure AI Foundry models (DeepSeek, Mistral, etc.)."
        )

    # Strip trailing /chat/completions* — the SDK appends it automatically.
    base_url = re.sub(r"/chat/completions.*$", "", endpoint.rstrip("/"))
    _foundry_client = OpenAI(
        api_key=key,
        base_url=base_url,
        timeout=600.0,
        max_retries=0,  # we handle retries ourselves; prevent SDK 429 compounding
    )
    return _foundry_client


# ---------------------------------------------------------------------------
# Async singleton clients — lazy initialisation (no module-level asyncio primitives)
# ---------------------------------------------------------------------------
_async_client: AsyncOpenAI | None = None
_async_fallback_client: AsyncOpenAI | None = None
_async_foundry_client: AsyncOpenAI | None = None


def _get_async_client() -> AsyncOpenAI:
    """Return lazy singleton ``AsyncOpenAI`` or ``AsyncAzureOpenAI`` client.

    Safe in single-threaded asyncio — no lock needed.
    """
    global _async_client
    if _async_client is not None:
        return _async_client

    api_key = settings.OPENAI_API_KEY
    if api_key:
        _async_client = AsyncOpenAI(api_key=api_key, timeout=600.0, max_retries=0)
        logger.info("ASYNC_AI_PROVIDER=openai (direct API key)")
        return _async_client

    azure_endpoint = settings.AZURE_OPENAI_ENDPOINT
    azure_key = settings.AZURE_OPENAI_KEY
    if azure_endpoint and azure_key:
        _async_client = AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_key,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            timeout=600.0,
            max_retries=0,
        )
        logger.info("ASYNC_AI_PROVIDER=azure_openai endpoint=%s", azure_endpoint)
        return _async_client

    raise ValueError(
        "No AI provider configured. Set OPENAI_API_KEY (direct) "
        "or AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_KEY (Azure OpenAI)."
    )


def _is_primary_azure() -> bool:
    """Check if the primary AI provider is Azure OpenAI (no direct API key)."""
    return not bool(settings.OPENAI_API_KEY) and bool(
        settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_KEY
    )


def _get_async_fallback_client() -> AsyncOpenAI | None:
    """Return async fallback provider client, or ``None``.

    Computes provider from settings directly — does NOT depend on
    ``_use_azure_openai`` (which is only set by the sync initializer).
    """
    global _async_fallback_client
    if _async_fallback_client is not None:
        return _async_fallback_client

    # Fallback only meaningful when primary is direct OpenAI
    if _is_primary_azure():
        return None

    azure_endpoint = settings.AZURE_OPENAI_ENDPOINT
    azure_key = settings.AZURE_OPENAI_KEY
    if azure_endpoint and azure_key:
        _async_fallback_client = AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_key,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            timeout=600.0,
            max_retries=0,
        )
        return _async_fallback_client
    return None


def _get_async_foundry_client() -> AsyncOpenAI:
    """Return async ``AsyncOpenAI`` client pointing to Azure AI Foundry."""
    global _async_foundry_client
    if _async_foundry_client is not None:
        return _async_foundry_client

    endpoint = settings.AZURE_AI_FOUNDRY_ENDPOINT
    key = settings.AZURE_AI_FOUNDRY_KEY
    if not endpoint or not key:
        raise ValueError(
            "AZURE_AI_FOUNDRY_ENDPOINT and AZURE_AI_FOUNDRY_KEY must be set "
            "to use Azure AI Foundry models (DeepSeek, Mistral, etc.)."
        )
    base_url = re.sub(r"/chat/completions.*$", "", endpoint.rstrip("/"))
    _async_foundry_client = AsyncOpenAI(
        api_key=key, base_url=base_url, timeout=600.0, max_retries=0,
    )
    return _async_foundry_client


# ---------------------------------------------------------------------------
# Model-family / provider helpers
# ---------------------------------------------------------------------------
# Prefixes that identify Azure AI Foundry models (routed via Chat Completions)
_FOUNDRY_MODEL_PREFIXES: tuple[str, ...] = (
    "deepseek",     # DeepSeek-R1, DeepSeek-V3
    "mistral",      # Mistral-large, Mistral-small (if deployed)
)

_FOUNDRY_RE = re.compile(
    r"^(?:" + "|".join(re.escape(p) for p in _FOUNDRY_MODEL_PREFIXES) + r")",
    re.IGNORECASE,
)


def _is_foundry_model(model_id: str) -> bool:
    """Return ``True`` if *model_id* should be routed via Azure AI Foundry."""
    return bool(_FOUNDRY_RE.match(model_id))


def _strip_think_tags(text: str) -> str:
    """Remove ``<think>...</think>`` reasoning traces from DeepSeek-R1 output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json_from_text(text: str) -> str:
    """Extract JSON object from free-form text (e.g. DeepSeek-R1 output).

    Handles common patterns:
      1. Pure JSON (already valid)
      2. JSON inside ```json ... ``` fenced blocks
      3. JSON object embedded in surrounding prose
    """
    # Try parsing as-is first
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped

    # Try extracting from fenced code block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if m:
        return m.group(1)

    # Try finding the first { ... } block
    m = re.search(r"(\{.*\})", stripped, re.DOTALL)
    if m:
        return m.group(1)

    return stripped


# Prefix-based detection for reasoning-class models that do NOT support
# the ``temperature`` parameter.  On Azure OpenAI, gpt-5.x models also
# reject temperature (unlike the direct OpenAI API), so they are included.
_REASONING_MODEL_PREFIXES: tuple[str, ...] = (
    "o1",           # o1, o1-pro, o1-mini, o1-preview
    "o3",           # o3, o3-mini, o3-pro, o3-deep-research
    "o4",           # o4-mini, o4-mini-deep-research
    "gpt-5",        # gpt-5.x — no temperature support on Azure OpenAI
)

_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(re.escape(p) for p in _REASONING_MODEL_PREFIXES) + r")(?:[^a-zA-Z]|$)",
    re.IGNORECASE,
)


def _is_reasoning_model(model_id: str) -> bool:
    """Return ``True`` if *model_id* is an o-series reasoning model that
    does NOT accept the temperature parameter."""
    return bool(_PREFIX_RE.match(model_id))


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------
_MAX_RETRIES = 5
_BACKOFF_BASE = 2.0  # seconds


def _retry(fn, *args, **kwargs):
    """Call *fn* with exponential backoff on 429 / 5xx / timeout errors."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except HttpxTimeout as exc:
            if attempt == _MAX_RETRIES:
                raise
            wait = _BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                "OpenAI TIMEOUT (attempt %d/%d) — retrying in %.1fs: %s",
                attempt,
                _MAX_RETRIES,
                wait,
                exc,
            )
            time.sleep(wait)
        except APIStatusError as exc:
            retryable = exc.status_code == 429 or exc.status_code >= 500
            if not retryable or attempt == _MAX_RETRIES:
                raise
            wait = _BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            if exc.status_code == 429:
                # Azure Foundry rate-limit: exponential base-3 gives
                # ~3s, ~7s, ~20s, ~60s, ~180s — respect Retry-After if longer.
                wait = _BACKOFF_BASE * (3 ** (attempt - 1)) + random.uniform(1, 5)
                retry_after = getattr(exc.response, "headers", {}).get("retry-after")
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after) + random.uniform(0.5, 2))
                    except (ValueError, TypeError):
                        pass
            logger.warning(
                "OpenAI %s (attempt %d/%d) — retrying in %.1fs",
                exc.status_code,
                attempt,
                _MAX_RETRIES,
                wait,
            )
            time.sleep(wait)
    # unreachable, but keeps mypy happy
    raise RuntimeError("retry loop exited unexpectedly")


async def _async_retry(coro_factory, *args, **kwargs):
    """Async equivalent of ``_retry`` — uses ``asyncio.sleep`` for backoff."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return await coro_factory(*args, **kwargs)
        except HttpxTimeout as exc:
            if attempt == _MAX_RETRIES:
                raise
            wait = _BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                "ASYNC_OPENAI TIMEOUT (attempt %d/%d) — retrying in %.1fs: %s",
                attempt, _MAX_RETRIES, wait, exc,
            )
            await asyncio.sleep(wait)
        except APIStatusError as exc:
            retryable = exc.status_code == 429 or exc.status_code >= 500
            if not retryable or attempt == _MAX_RETRIES:
                raise
            wait = _BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            if exc.status_code == 429:
                wait = _BACKOFF_BASE * (3 ** (attempt - 1)) + random.uniform(1, 5)
                retry_after = getattr(exc.response, "headers", {}).get("retry-after")
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after) + random.uniform(0.5, 2))
                    except (ValueError, TypeError):
                        pass
            logger.warning(
                "ASYNC_OPENAI %s (attempt %d/%d) — retrying in %.1fs",
                exc.status_code, attempt, _MAX_RETRIES, wait,
            )
            await asyncio.sleep(wait)
    raise RuntimeError("async retry loop exited unexpectedly")


# ---------------------------------------------------------------------------
# Completion (Responses API)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CompletionResult:
    text: str
    model: str
    raw: Any = field(repr=False)


# ---------------------------------------------------------------------------
# Per-stage reasoning effort overrides (o-series / gpt-5.x models)
# ---------------------------------------------------------------------------
_REASONING_EFFORT: dict[str, str] = {
    "critic_escalation": "high",  # o4-mini reasoning for critic escalation
}


def create_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    response_format: dict[str, str] | None = None,
    schema: type | None = None,
    stage: str | None = None,
    reasoning_effort: str | None = None,
) -> CompletionResult:
    """Send a request to the OpenAI **Responses API** or Azure AI Foundry
    **Chat Completions API** (for DeepSeek/Mistral models).

    Parameters
    ----------
    model : str | None
        Defaults to ``settings.OPENAI_MODEL_INTELLIGENCE`` (``gpt-4.1``).
        Models prefixed with ``deepseek`` or ``mistral`` are routed to
        Azure AI Foundry via Chat Completions API.
    temperature : float
        Ignored for reasoning-class models (prefix-detected) that do not
        support the ``temperature`` parameter.
    response_format : dict | None
        E.g. ``{"type": "json_object"}`` to force JSON output.
        Mapped to the ``text.format`` parameter of the Responses API.
        For Foundry models, JSON mode is enforced via prompt instruction.
    schema : type | None
        **Optional — institutional parse path.**  When provided, the
        request is dispatched via ``client.responses.parse()`` and the
        response is deserialised against the given Pydantic model.
        Not supported for Foundry models.
    stage : str | None
        Pipeline stage name (e.g. ``"critic_escalation"``).  Used to
        look up per-stage ``reasoning_effort`` overrides.
    reasoning_effort : str | None
        Explicit reasoning effort.  Overrides the per-stage default.
        Valid values: ``"low"``, ``"medium"``, ``"high"``.
    """
    mdl = model or settings.OPENAI_MODEL_INTELLIGENCE

    # ── Route: Azure AI Foundry (Chat Completions) vs OpenAI (Responses)
    if _is_foundry_model(mdl):
        return _create_completion_foundry(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=mdl,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            stage=stage,
        )

    return _create_completion_openai(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=mdl,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        schema=schema,
        stage=stage,
        reasoning_effort=reasoning_effort,
    )


# ---------------------------------------------------------------------------
# Foundry inter-call throttle  (prevents 429 on Azure AI S0 tier)
# ---------------------------------------------------------------------------
_foundry_last_call: float = 0.0
_foundry_lock = threading.Lock()
_FOUNDRY_MIN_INTERVAL: float = 6.0  # seconds between Foundry calls (S0 tier: ~10 TPM limit)


def _throttle_foundry() -> None:
    """Sleep if necessary so that consecutive Foundry calls are spaced."""
    global _foundry_last_call
    with _foundry_lock:
        elapsed = time.time() - _foundry_last_call
        if elapsed < _FOUNDRY_MIN_INTERVAL:
            wait = _FOUNDRY_MIN_INTERVAL - elapsed
            logger.debug("FOUNDRY_THROTTLE sleeping %.1fs", wait)
            time.sleep(wait)
        _foundry_last_call = time.time()


# ---------------------------------------------------------------------------
# Async Foundry throttle (asyncio.Lock + asyncio.sleep — never blocks event loop)
# ---------------------------------------------------------------------------
_async_foundry_last_call: float = 0.0
_async_foundry_lock: asyncio.Lock | None = None  # created lazily


async def _async_throttle_foundry() -> None:
    """Async equivalent of ``_throttle_foundry`` — uses ``asyncio.sleep``."""
    global _async_foundry_last_call, _async_foundry_lock
    if _async_foundry_lock is None:
        _async_foundry_lock = asyncio.Lock()
    async with _async_foundry_lock:
        elapsed = time.time() - _async_foundry_last_call
        if elapsed < _FOUNDRY_MIN_INTERVAL:
            wait = _FOUNDRY_MIN_INTERVAL - elapsed
            logger.debug("ASYNC_FOUNDRY_THROTTLE sleeping %.1fs", wait)
            await asyncio.sleep(wait)
        _async_foundry_last_call = time.time()


async def _async_create_completion_foundry(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    response_format: dict[str, str] | None = None,
    stage: str | None = None,
) -> CompletionResult:
    """Async Azure AI Foundry path — Chat Completions API for DeepSeek/Mistral."""
    await _async_throttle_foundry()

    client = _get_async_foundry_client()

    json_mode = bool(response_format and response_format.get("type") == "json_object")
    is_r1 = "r1" in model.lower()

    effective_system = system_prompt
    if json_mode and "json" not in system_prompt.lower():
        effective_system = (
            "You must respond with strictly valid JSON (no markdown fences, "
            "no explanation outside the JSON object).\n\n" + system_prompt
        )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": effective_system},
        {"role": "user", "content": user_prompt},
    ]

    logger.info(
        "ASYNC_FOUNDRY_CHAT_REQUEST model=%s json_mode=%s temperature=%s stage=%s is_r1=%s",
        model, json_mode, temperature, stage or "n/a", is_r1,
    )

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if not is_r1:
        kwargs["temperature"] = temperature

    resp = await _async_retry(client.chat.completions.create, **kwargs)

    text = resp.choices[0].message.content or "" if resp.choices else ""
    if is_r1 and "<think>" in text:
        text = _strip_think_tags(text)
    if json_mode:
        text = _extract_json_from_text(text)

    actual_model = getattr(resp, "model", None) or model
    usage = getattr(resp, "usage", None)
    logger.info(
        "ASYNC_FOUNDRY_CHAT_COMPLETE model_resolved=%s tokens_in=%s tokens_out=%s",
        actual_model,
        getattr(usage, "prompt_tokens", "n/a"),
        getattr(usage, "completion_tokens", "n/a"),
    )
    return CompletionResult(text=text, model=str(actual_model), raw=resp)


def _create_completion_foundry(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    response_format: dict[str, str] | None = None,
    stage: str | None = None,
) -> CompletionResult:
    """Azure AI Foundry path — Chat Completions API for DeepSeek/Mistral.

    DeepSeek-R1 specifics:
      - Reasoning model: ``<think>`` tags are stripped from output.
      - No native ``json_object`` response format: JSON enforced via prompt.
      - Temperature is sent (R1 on Azure accepts it, unlike o-series).
    """
    _throttle_foundry()

    client = _get_foundry_client()

    json_mode = bool(response_format and response_format.get("type") == "json_object")
    is_r1 = "r1" in model.lower()

    # Build system prompt with JSON instruction if needed
    effective_system = system_prompt
    if json_mode and "json" not in system_prompt.lower():
        effective_system = (
            "You must respond with strictly valid JSON (no markdown fences, "
            "no explanation outside the JSON object).\n\n" + system_prompt
        )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": effective_system},
        {"role": "user", "content": user_prompt},
    ]

    logger.info(
        "FOUNDRY_CHAT_REQUEST model=%s json_mode=%s temperature=%s stage=%s is_r1=%s",
        model, json_mode, temperature, stage or "n/a", is_r1,
    )

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    # DeepSeek-R1 on Azure AI Foundry accepts temperature
    if not is_r1:
        kwargs["temperature"] = temperature

    resp = _retry(client.chat.completions.create, **kwargs)

    text = resp.choices[0].message.content or "" if resp.choices else ""

    # Strip <think> reasoning traces from R1 output
    if is_r1 and "<think>" in text:
        text = _strip_think_tags(text)

    # Extract JSON from free-form text if needed
    if json_mode:
        text = _extract_json_from_text(text)

    actual_model = getattr(resp, "model", None) or model
    usage = getattr(resp, "usage", None)

    logger.info(
        "FOUNDRY_CHAT_COMPLETE model_resolved=%s tokens_in=%s tokens_out=%s",
        actual_model,
        getattr(usage, "prompt_tokens", "n/a"),
        getattr(usage, "completion_tokens", "n/a"),
    )

    return CompletionResult(text=text, model=str(actual_model), raw=resp)


def _dispatch_responses(client: OpenAI, kwargs: dict[str, Any], schema: type | None) -> tuple[Any, str]:
    """Execute Responses API call (create or parse) and return (raw_resp, text)."""
    if schema is not None:
        resp = _retry(client.responses.parse, **kwargs, text_format=schema)
        parsed = resp.output_parsed
        text = _json.dumps(parsed.model_dump(), default=str) if parsed else ""
    else:
        resp = _retry(client.responses.create, **kwargs)
        text = resp.output_text or ""
    return resp, text


def _create_completion_openai(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    response_format: dict[str, str] | None = None,
    schema: type | None = None,
    stage: str | None = None,
    reasoning_effort: str | None = None,
) -> CompletionResult:
    """OpenAI Responses API path with automatic Azure OpenAI fallback.

    Strategy: try direct OpenAI first.  If the call fails after retries
    (auth error, rate-limit exhaustion, server error, timeout), fall
    back transparently to Azure OpenAI — provided it is configured.
    """
    client = _get_client()

    json_mode = bool(response_format and response_format.get("type") == "json_object")
    skip_temp = _is_reasoning_model(model)  # o-series only; gpt-5.x accepts temp

    # ── Resolve reasoning_effort for o-series / gpt-5.x ───────────────
    eff = reasoning_effort or (stage and _REASONING_EFFORT.get(stage))

    # ── Audit log (never includes prompt content) ─────────────────────
    logger.info(
        "OPENAI_RESPONSES_REQUEST model_requested=%s json_mode=%s temperature=%s reasoning_effort=%s",
        model,
        json_mode,
        "skipped(reasoning)" if skip_temp else temperature,
        eff or "default",
    )

    # ── Build input — NEVER mutate the caller's arguments ─────────────
    json_hint_needed = json_mode and "json" not in user_prompt.lower()

    if json_hint_needed:
        api_input: str | list[dict[str, str]] = [
            {"role": "developer", "content": "Return strictly valid JSON."},
            {"role": "user", "content": user_prompt},
        ]
    else:
        api_input = user_prompt

    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": system_prompt,
        "input": api_input,
        "max_output_tokens": max_tokens,
    }

    if not skip_temp:
        kwargs["temperature"] = temperature

    if eff:
        kwargs["reasoning"] = {"effort": eff}

    if response_format:
        kwargs["text"] = {"format": response_format}

    # ── Dispatch with provider fallback ────────────────────────────────
    try:
        resp, text = _dispatch_responses(client, kwargs, schema)
    except Exception as primary_exc:
        fallback = _get_fallback_client()
        if fallback is None:
            raise
        logger.warning(
            "OPENAI_PROVIDER_FALLBACK primary failed (%s) — retrying with Azure OpenAI",
            f"{type(primary_exc).__name__}(status={getattr(primary_exc, 'status_code', 'n/a')})",
        )
        try:
            resp, text = _dispatch_responses(fallback, kwargs, schema)
            logger.info("OPENAI_FALLBACK_SUCCESS model=%s via Azure OpenAI", model)
        except Exception as fallback_exc:
            logger.error(
                "OPENAI_FALLBACK_ALSO_FAILED azure_error=%s — raising original error",
                f"{type(fallback_exc).__name__}(status={getattr(fallback_exc, 'status_code', 'n/a')})",
            )
            raise primary_exc from fallback_exc

    actual_model = getattr(resp, "model", None) or model

    logger.info(
        "OPENAI_RESPONSES_COMPLETE model_resolved=%s tokens_out=%s",
        actual_model,
        getattr(getattr(resp, "usage", None), "output_tokens", "n/a"),
    )

    return CompletionResult(text=text, model=str(actual_model), raw=resp)


# ---------------------------------------------------------------------------
# Async Completion (Responses API) — primary async implementation
# ---------------------------------------------------------------------------

async def _async_dispatch_responses(
    client: AsyncOpenAI, kwargs: dict[str, Any], schema: type | None,
) -> tuple[Any, str]:
    """Async equivalent of ``_dispatch_responses``."""
    if schema is not None:
        resp = await _async_retry(client.responses.parse, **kwargs, text_format=schema)
        parsed = resp.output_parsed
        text = _json.dumps(parsed.model_dump(), default=str) if parsed else ""
    else:
        resp = await _async_retry(client.responses.create, **kwargs)
        text = resp.output_text or ""
    return resp, text


async def _async_create_completion_openai(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    response_format: dict[str, str] | None = None,
    schema: type | None = None,
    stage: str | None = None,
    reasoning_effort: str | None = None,
) -> CompletionResult:
    """Async OpenAI Responses API path with automatic Azure OpenAI fallback."""
    client = _get_async_client()

    json_mode = bool(response_format and response_format.get("type") == "json_object")
    skip_temp = _is_reasoning_model(model)

    eff = reasoning_effort or (stage and _REASONING_EFFORT.get(stage))

    logger.info(
        "ASYNC_OPENAI_RESPONSES_REQUEST model_requested=%s json_mode=%s temperature=%s reasoning_effort=%s",
        model, json_mode,
        "skipped(reasoning)" if skip_temp else temperature,
        eff or "default",
    )

    json_hint_needed = json_mode and "json" not in user_prompt.lower()
    if json_hint_needed:
        api_input: str | list[dict[str, str]] = [
            {"role": "developer", "content": "Return strictly valid JSON."},
            {"role": "user", "content": user_prompt},
        ]
    else:
        api_input = user_prompt

    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": system_prompt,
        "input": api_input,
        "max_output_tokens": max_tokens,
    }
    if not skip_temp:
        kwargs["temperature"] = temperature
    if eff:
        kwargs["reasoning"] = {"effort": eff}
    if response_format:
        kwargs["text"] = {"format": response_format}

    try:
        resp, text = await _async_dispatch_responses(client, kwargs, schema)
    except Exception as primary_exc:
        fallback = _get_async_fallback_client()
        if fallback is None:
            raise
        logger.warning(
            "ASYNC_OPENAI_PROVIDER_FALLBACK primary failed (%s) — retrying with Azure OpenAI",
            f"{type(primary_exc).__name__}(status={getattr(primary_exc, 'status_code', 'n/a')})",
        )
        try:
            resp, text = await _async_dispatch_responses(fallback, kwargs, schema)
            logger.info("ASYNC_OPENAI_FALLBACK_SUCCESS model=%s via Azure OpenAI", model)
        except Exception as fallback_exc:
            logger.error(
                "ASYNC_OPENAI_FALLBACK_ALSO_FAILED azure_error=%s — raising original error",
                type(fallback_exc).__name__,
            )
            raise primary_exc from fallback_exc

    actual_model = getattr(resp, "model", None) or model
    logger.info(
        "ASYNC_OPENAI_RESPONSES_COMPLETE model_resolved=%s tokens_out=%s",
        actual_model,
        getattr(getattr(resp, "usage", None), "output_tokens", "n/a"),
    )
    return CompletionResult(text=text, model=str(actual_model), raw=resp)


async def async_create_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    response_format: dict[str, str] | None = None,
    schema: type | None = None,
    stage: str | None = None,
    reasoning_effort: str | None = None,
) -> CompletionResult:
    """Async primary implementation of ``create_completion``.

    Uses ``AsyncOpenAI`` for non-blocking I/O.  Same API surface and
    return type as the sync version.
    """
    mdl = model or settings.OPENAI_MODEL_INTELLIGENCE

    if _is_foundry_model(mdl):
        return await _async_create_completion_foundry(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=mdl,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            stage=stage,
        )

    return await _async_create_completion_openai(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=mdl,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        schema=schema,
        stage=stage,
        reasoning_effort=reasoning_effort,
    )


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    count: int


def create_embedding(
    *,
    inputs: list[str],
    model: str | None = None,
) -> EmbeddingResult:
    """Generate embeddings via OpenAI or Azure AI Foundry Embeddings API.

    Parameters
    ----------
    model : str | None
        Defaults to ``settings.OPENAI_EMBEDDING_MODEL`` (``text-embedding-3-large``).
    When ``OPENAI_API_KEY`` is not set but ``AZURE_AI_FOUNDRY_KEY`` is
    configured, the Foundry client is used transparently (same embedding
    model, routed through Azure AI Services).

    Raises ``RuntimeError`` if the resolved model does not match the
    canonical ``EMBEDDING_MODEL_NAME`` constant (B2 guard).
    """
    from ai_engine.validation.vector_integrity_guard import EMBEDDING_MODEL_NAME

    # ── Pick client: prefer OpenAI direct, then Azure OpenAI, then Foundry ──
    if settings.OPENAI_API_KEY or settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_KEY:
        client = _get_client()
    elif settings.AZURE_AI_FOUNDRY_KEY:
        logger.info("EMBEDDING_PROVIDER=foundry (no OpenAI/Azure OpenAI config)")
        client = _get_foundry_client()
    else:
        raise ValueError(
            "No AI provider configured for embeddings. "
            "Set OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT+KEY, or AZURE_AI_FOUNDRY_KEY."
        )

    mdl = model or settings.OPENAI_EMBEDDING_MODEL

    if mdl != EMBEDDING_MODEL_NAME:
        raise RuntimeError(
            f"Embedding model drift detected at runtime. "
            f"Expected '{EMBEDDING_MODEL_NAME}', got '{mdl}'. "
            f"Dynamic switching is not allowed."
        )

    logger.info("Creating embedding with model=%s for %d inputs", mdl, len(inputs))

    # ── Dispatch with provider fallback ────────────────────────────────
    try:
        resp = _retry(client.embeddings.create, model=mdl, input=inputs)
    except Exception as primary_exc:
        fallback = _get_fallback_client()
        if fallback is None:
            raise
        logger.warning(
            "EMBEDDING_PROVIDER_FALLBACK primary failed (%s) — retrying with Azure OpenAI",
            f"{type(primary_exc).__name__}(status={getattr(primary_exc, 'status_code', 'n/a')})",
        )
        try:
            resp = _retry(fallback.embeddings.create, model=mdl, input=inputs)
            logger.info("EMBEDDING_FALLBACK_SUCCESS model=%s via Azure OpenAI", mdl)
        except Exception as fallback_exc:
            logger.error(
                "EMBEDDING_FALLBACK_ALSO_FAILED azure_error=%s — raising original error",
                f"{type(fallback_exc).__name__}(status={getattr(fallback_exc, 'status_code', 'n/a')})",
            )
            raise primary_exc from fallback_exc

    items_sorted = sorted(resp.data, key=lambda x: x.index)
    vectors = [item.embedding for item in items_sorted]
    actual_model = getattr(resp, "model", None) or mdl
    return EmbeddingResult(vectors=vectors, model=str(actual_model), count=len(vectors))


async def async_create_embedding(
    *,
    inputs: list[str],
    model: str | None = None,
) -> EmbeddingResult:
    """Async equivalent of ``create_embedding``.

    Uses ``AsyncOpenAI`` / ``AsyncAzureOpenAI`` for non-blocking I/O.
    Replicates the B2 guard (model drift detection) and provider fallback
    chain from the sync version.
    """
    from ai_engine.validation.vector_integrity_guard import EMBEDDING_MODEL_NAME

    # ── Pick async client: prefer OpenAI direct, then Azure OpenAI, then Foundry
    if settings.OPENAI_API_KEY or settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_KEY:
        client = _get_async_client()
    elif settings.AZURE_AI_FOUNDRY_KEY:
        logger.info("ASYNC_EMBEDDING_PROVIDER=foundry (no OpenAI/Azure OpenAI config)")
        client = _get_async_foundry_client()
    else:
        raise ValueError(
            "No AI provider configured for embeddings. "
            "Set OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT+KEY, or AZURE_AI_FOUNDRY_KEY."
        )

    mdl = model or settings.OPENAI_EMBEDDING_MODEL

    if mdl != EMBEDDING_MODEL_NAME:
        raise RuntimeError(
            f"Embedding model drift detected at runtime. "
            f"Expected '{EMBEDDING_MODEL_NAME}', got '{mdl}'. "
            f"Dynamic switching is not allowed."
        )

    logger.info("ASYNC_EMBEDDING_REQUEST model=%s inputs=%d", mdl, len(inputs))

    # ── Dispatch with provider fallback ────────────────────────────────
    try:
        resp = await _async_retry(client.embeddings.create, model=mdl, input=inputs)
    except Exception as primary_exc:
        fallback = _get_async_fallback_client()
        if fallback is None:
            raise
        logger.warning(
            "ASYNC_EMBEDDING_PROVIDER_FALLBACK primary failed (%s) — retrying with Azure OpenAI",
            f"{type(primary_exc).__name__}(status={getattr(primary_exc, 'status_code', 'n/a')})",
        )
        try:
            resp = await _async_retry(fallback.embeddings.create, model=mdl, input=inputs)
            logger.info("ASYNC_EMBEDDING_FALLBACK_SUCCESS model=%s via Azure OpenAI", mdl)
        except Exception as fallback_exc:
            logger.error(
                "ASYNC_EMBEDDING_FALLBACK_ALSO_FAILED azure_error=%s — raising original error",
                f"{type(fallback_exc).__name__}(status={getattr(fallback_exc, 'status_code', 'n/a')})",
            )
            raise primary_exc from fallback_exc

    items_sorted = sorted(resp.data, key=lambda x: x.index)
    vectors = [item.embedding for item in items_sorted]
    actual_model = getattr(resp, "model", None) or mdl
    return EmbeddingResult(vectors=vectors, model=str(actual_model), count=len(vectors))
