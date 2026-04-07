"""LLM gate — fault-tolerant wrapper for large language model calls.

Stability Guardrails §2.5b — satisfies P6 (Fault-Tolerant) for the
LLM-specific failure modes.

Problem this solves
-------------------
LLM calls have materially different semantics from REST APIs:

- **Latency is variable and large.** A normal OpenAI chat completion
  ranges from 2s to 30s depending on prompt and output length. A
  hard 5-second timeout from ``ExternalProviderGate`` would kill
  every legitimate call.
- **429 rate limits are frequent and recoverable.** OpenAI returns
  HTTP 429 with a ``Retry-After`` header, expected to be handled
  with exponential backoff + jitter. A circuit breaker that opens
  on five consecutive 429s would treat a transient burst as a
  permanent failure and refuse all subsequent requests.
- **Fallback models exist.** Many call sites can degrade from
  ``gpt-4o`` to ``gpt-4o-mini`` under pressure. The primitive
  should support this explicitly.
- **Calls are non-idempotent.** LLMs are stochastic — caching a
  response for ``op_key`` would serve a stale response that never
  reflects the caller's current context. No cache here.

``LLMGate`` is a dedicated primitive that handles these concerns.
It does **not** inherit from ``ExternalProviderGate``; the two
primitives share the P6 principle but otherwise have disjoint
implementations.

What this primitive guarantees
------------------------------
- **Soft/hard timeout separation.** ``soft_timeout_s`` is the
  latency budget — calls longer than this log a structured warning
  but are **not** aborted. ``hard_timeout_s`` is the wall — calls
  longer than this are aborted with ``LLMHardTimeoutError``. Defaults
  are 60s soft / 180s hard.
- **Exponential backoff with jitter on 429.** When the caller's
  chat function raises ``LLMRateLimitError``, the gate sleeps
  ``backoff_base_s * 2^attempt`` (capped at ``backoff_max_s``) plus
  a random jitter of ±``jitter_ratio``, honouring any ``retry_after_s``
  on the exception. 429s are **not** counted toward retry attempts
  — they drain a separate rate-limit budget.
- **Retry with backoff on server/network errors.** Any exception
  that isn't ``LLMRateLimitError`` counts as a failed attempt. Up
  to ``max_retries`` retries are allowed, then ``LLMUnavailableError``
  is raised.
- **Automatic fallback model.** When consecutive 429s exceed
  ``rate_limit_threshold``, the gate switches the next call to the
  configured ``fallback_model`` (if any). A successful call resets
  the consecutive counter.
- **Total-budget enforcement.** The elapsed time across all retries
  is bounded by ``hard_timeout_s``. If the retry budget would push
  the total over the wall, the gate raises instead of attempting
  another call.
- **Transport-agnostic.** The gate does not import any LLM SDK. It
  accepts a ``chat_fn: Callable[[str, list[dict]], Awaitable[LLMResponse]]``
  on every call; real call sites wire this up to OpenAI / Anthropic /
  whatever. Tests inject a fake callable and drive deterministic
  scenarios.

Non-goals (v1)
--------------
- No cache — LLM calls are stochastic and caching is the caller's
  responsibility (memo chapters, fact sheet sections, etc.).
- No streaming — the return type is a single ``LLMResponse``. A
  streaming variant can be added when a real call site needs it.
- No tool-calling protocol awareness — treat the response opaquely;
  caller parses it.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Errors ─────────────────────────────────────────────────────────


class LLMGateError(Exception):
    """Base class for LLM gate errors."""


class LLMRateLimitError(LLMGateError):
    """Raised by the caller's ``chat_fn`` when the provider returned
    HTTP 429. If the provider supplied a ``Retry-After`` header, pass
    it as ``retry_after_s``.
    """

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LLMHardTimeoutError(LLMGateError):
    """Raised when a call exceeds ``hard_timeout_s`` across all
    retries. The underlying task is cancelled.
    """


class LLMUnavailableError(LLMGateError):
    """Raised after ``max_retries`` failed attempts (non-429
    failures). Wraps the last exception.
    """

    def __init__(self, message: str, *, last_error: BaseException | None = None) -> None:
        super().__init__(message)
        self.last_error = last_error


# ── Config ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LLMGateConfig:
    """Declarative LLM gate configuration."""

    primary_model: str
    fallback_model: str | None = None
    soft_timeout_s: float = 60.0
    hard_timeout_s: float = 180.0
    max_retries: int = 3
    backoff_base_s: float = 2.0
    backoff_max_s: float = 30.0
    jitter_ratio: float = 0.25
    rate_limit_threshold: int = 5
    # Optional random source for jitter — tests inject a deterministic
    # generator to get reproducible sleep timings.
    rng: Callable[[], float] | None = None

    def __post_init__(self) -> None:
        if not self.primary_model:
            raise ValueError("LLMGateConfig.primary_model must be non-empty")
        if self.soft_timeout_s <= 0:
            raise ValueError("LLMGateConfig.soft_timeout_s must be > 0")
        if self.hard_timeout_s <= 0:
            raise ValueError("LLMGateConfig.hard_timeout_s must be > 0")
        if self.hard_timeout_s < self.soft_timeout_s:
            raise ValueError(
                "LLMGateConfig.hard_timeout_s must be >= soft_timeout_s",
            )
        if self.max_retries < 0:
            raise ValueError("LLMGateConfig.max_retries must be >= 0")
        if self.backoff_base_s <= 0:
            raise ValueError("LLMGateConfig.backoff_base_s must be > 0")
        if self.backoff_max_s < self.backoff_base_s:
            raise ValueError(
                "LLMGateConfig.backoff_max_s must be >= backoff_base_s",
            )
        if not 0 <= self.jitter_ratio < 1:
            raise ValueError("LLMGateConfig.jitter_ratio must be in [0, 1)")
        if self.rate_limit_threshold <= 0:
            raise ValueError("LLMGateConfig.rate_limit_threshold must be > 0")


# ── Response ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class LLMResponse:
    model: str
    content: str
    usage: dict[str, Any] | None = None


# ── Metrics ────────────────────────────────────────────────────────


@dataclass
class LLMGateMetrics:
    calls: int = 0
    successes: int = 0
    rate_limited: int = 0
    retries: int = 0
    hard_timeouts: int = 0
    exhausted: int = 0
    soft_timeout_warnings: int = 0
    fallback_uses: int = 0
    total_sleep_s: float = 0.0


# ── Gate ───────────────────────────────────────────────────────────


ChatFn = Callable[[str, Sequence[dict[str, Any]]], Awaitable[LLMResponse]]


class LLMGate:
    """Fault-tolerant wrapper for LLM chat calls."""

    def __init__(self, cfg: LLMGateConfig) -> None:
        self._cfg = cfg
        self._consecutive_rate_limits = 0
        self._metrics = LLMGateMetrics()

    @property
    def metrics(self) -> LLMGateMetrics:
        return self._metrics

    async def chat(
        self,
        chat_fn: ChatFn,
        messages: Sequence[dict[str, Any]],
        *,
        op_key: str,
        prefer_fallback: bool = False,
    ) -> LLMResponse:
        """Execute ``chat_fn`` under the gate's protections.

        Args:
            chat_fn: async callable ``(model, messages) -> LLMResponse``
                supplied by the call site (wraps the actual SDK call).
            messages: message list passed through to ``chat_fn``.
            op_key: opaque label used in structured logs. Not a cache
                key — LLM gate has no cache.
            prefer_fallback: force the first attempt to use the
                fallback model, e.g. when the caller already knows
                the primary is unavailable.
        """
        self._metrics.calls += 1
        start = time.monotonic()
        deadline = start + self._cfg.hard_timeout_s

        use_fallback = prefer_fallback or (
            self._consecutive_rate_limits >= self._cfg.rate_limit_threshold
            and self._cfg.fallback_model is not None
        )
        if use_fallback and self._cfg.fallback_model is None:
            use_fallback = False

        last_error: BaseException | None = None

        for attempt in range(self._cfg.max_retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._metrics.hard_timeouts += 1
                raise LLMHardTimeoutError(
                    f"LLM gate '{op_key}' exhausted hard_timeout_s "
                    f"({self._cfg.hard_timeout_s}s) across {attempt} attempts",
                )

            model = (
                self._cfg.fallback_model
                if (use_fallback and self._cfg.fallback_model is not None)
                else self._cfg.primary_model
            )
            if use_fallback:
                self._metrics.fallback_uses += 1

            try:
                response = await asyncio.wait_for(
                    chat_fn(model, messages),
                    timeout=remaining,
                )
            except asyncio.TimeoutError as exc:
                self._metrics.hard_timeouts += 1
                raise LLMHardTimeoutError(
                    f"LLM gate '{op_key}' hit hard_timeout_s "
                    f"({self._cfg.hard_timeout_s}s)",
                ) from exc
            except asyncio.CancelledError:
                raise
            except LLMRateLimitError as exc:
                self._metrics.rate_limited += 1
                self._consecutive_rate_limits += 1
                sleep_for = self._compute_backoff(
                    attempt,
                    retry_after=exc.retry_after_s,
                )
                # Do not count 429s against ``max_retries`` — they have
                # their own escalation via ``rate_limit_threshold``.
                if (
                    self._consecutive_rate_limits >= self._cfg.rate_limit_threshold
                    and self._cfg.fallback_model is not None
                ):
                    use_fallback = True
                    logger.warning(
                        "llm_gate_escalate_to_fallback op_key=%s "
                        "consecutive_429=%d",
                        op_key,
                        self._consecutive_rate_limits,
                    )
                # Check total budget before sleeping.
                if time.monotonic() + sleep_for >= deadline:
                    self._metrics.hard_timeouts += 1
                    raise LLMHardTimeoutError(
                        f"LLM gate '{op_key}' would exceed hard_timeout_s "
                        f"during 429 backoff",
                    ) from exc
                await asyncio.sleep(sleep_for)
                self._metrics.total_sleep_s += sleep_for
                last_error = exc
                continue
            except Exception as exc:  # noqa: BLE001 — opaque transport errors
                self._metrics.retries += 1
                last_error = exc
                if attempt >= self._cfg.max_retries:
                    self._metrics.exhausted += 1
                    raise LLMUnavailableError(
                        f"LLM gate '{op_key}' exhausted {self._cfg.max_retries} "
                        "retries",
                        last_error=exc,
                    ) from exc
                sleep_for = self._compute_backoff(attempt)
                if time.monotonic() + sleep_for >= deadline:
                    self._metrics.hard_timeouts += 1
                    raise LLMHardTimeoutError(
                        f"LLM gate '{op_key}' would exceed hard_timeout_s "
                        "during retry backoff",
                    ) from exc
                await asyncio.sleep(sleep_for)
                self._metrics.total_sleep_s += sleep_for
                continue
            else:
                self._consecutive_rate_limits = 0
                self._metrics.successes += 1
                elapsed = time.monotonic() - start
                if elapsed > self._cfg.soft_timeout_s:
                    self._metrics.soft_timeout_warnings += 1
                    logger.warning(
                        "llm_gate_soft_timeout_exceeded op_key=%s "
                        "elapsed_s=%.2f soft_budget_s=%.2f model=%s",
                        op_key,
                        elapsed,
                        self._cfg.soft_timeout_s,
                        model,
                    )
                return response

        # Should be unreachable — the loop either returns or raises.
        self._metrics.exhausted += 1
        raise LLMUnavailableError(
            f"LLM gate '{op_key}' exited retry loop unexpectedly",
            last_error=last_error,
        )

    def _compute_backoff(
        self,
        attempt: int,
        *,
        retry_after: float | None = None,
    ) -> float:
        """Exponential backoff with jitter; respects ``retry_after``."""
        base = min(
            self._cfg.backoff_base_s * (2**attempt),
            self._cfg.backoff_max_s,
        )
        if retry_after is not None and retry_after > base:
            base = retry_after
        rng = self._cfg.rng or random.random
        jitter = (rng() * 2 - 1) * self._cfg.jitter_ratio  # in [-ratio, +ratio]
        sleep_for: float = base * (1 + jitter)
        return max(0.0, sleep_for)
