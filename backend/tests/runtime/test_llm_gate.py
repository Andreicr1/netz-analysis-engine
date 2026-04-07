"""Tests for ``LLMGate`` (Stability Guardrails §2.5b)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

from app.core.runtime.llm_gate import (
    LLMGate,
    LLMGateConfig,
    LLMHardTimeoutError,
    LLMRateLimitError,
    LLMResponse,
    LLMUnavailableError,
)

# ── Fake chat_fn helpers ──────────────────────────────────────────


def make_chat_fn(
    *,
    returns: LLMResponse | None = None,
    raises_sequence: list[BaseException] | None = None,
) -> tuple[Any, list[tuple[str, Sequence[dict[str, Any]]]]]:
    """Build a chat_fn that returns a canned response or raises a
    sequence of errors before eventually returning.

    Returns a tuple ``(chat_fn, calls_list)`` so tests can inspect
    which models/messages were invoked.
    """
    calls: list[tuple[str, Sequence[dict[str, Any]]]] = []
    errors_iter = iter(raises_sequence or [])

    async def chat_fn(model: str, messages: Sequence[dict[str, Any]]) -> LLMResponse:
        calls.append((model, list(messages)))
        try:
            exc = next(errors_iter)
        except StopIteration:
            if returns is not None:
                return returns
            return LLMResponse(model=model, content="ok")
        else:
            raise exc

    return chat_fn, calls


# ── Deterministic jitter ──────────────────────────────────────────


def zero_rng() -> float:
    return 0.5  # produces 0 jitter (2*0.5-1 = 0)


# ── Config validation ────────────────────────────────────────────


class TestConfigValidation:
    def test_primary_model_required(self) -> None:
        with pytest.raises(ValueError, match="primary_model"):
            LLMGateConfig(primary_model="")

    def test_hard_timeout_must_exceed_soft(self) -> None:
        with pytest.raises(ValueError, match="hard_timeout_s"):
            LLMGateConfig(
                primary_model="gpt-4o",
                soft_timeout_s=60,
                hard_timeout_s=30,
            )

    def test_jitter_ratio_in_range(self) -> None:
        with pytest.raises(ValueError, match="jitter_ratio"):
            LLMGateConfig(primary_model="gpt-4o", jitter_ratio=1.5)

    def test_max_retries_non_negative(self) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            LLMGateConfig(primary_model="gpt-4o", max_retries=-1)


# ── Happy path ───────────────────────────────────────────────────


class TestHappyPath:
    async def test_successful_call_returns_response(self) -> None:
        gate = LLMGate(LLMGateConfig(primary_model="gpt-4o"))
        chat_fn, calls = make_chat_fn(
            returns=LLMResponse(model="gpt-4o", content="hello"),
        )
        result = await gate.chat(chat_fn, [{"role": "user", "content": "hi"}], op_key="t")
        assert result.content == "hello"
        assert calls[0][0] == "gpt-4o"
        assert gate.metrics.successes == 1


# ── Rate limit handling ──────────────────────────────────────────


class TestRateLimit:
    async def test_429_triggers_backoff_and_retries(self) -> None:
        cfg = LLMGateConfig(
            primary_model="gpt-4o",
            max_retries=3,
            backoff_base_s=0.01,
            backoff_max_s=0.05,
            jitter_ratio=0,
            rng=zero_rng,
            rate_limit_threshold=10,
        )
        gate = LLMGate(cfg)
        chat_fn, calls = make_chat_fn(
            raises_sequence=[
                LLMRateLimitError("429", retry_after_s=0.01),
                LLMRateLimitError("429", retry_after_s=0.01),
            ],
            returns=LLMResponse(model="gpt-4o", content="after_retry"),
        )
        result = await gate.chat(chat_fn, [], op_key="rl")
        assert result.content == "after_retry"
        assert gate.metrics.rate_limited == 2
        assert len(calls) == 3

    async def test_consecutive_429s_trigger_fallback(self) -> None:
        cfg = LLMGateConfig(
            primary_model="gpt-4o",
            fallback_model="gpt-4o-mini",
            max_retries=5,
            backoff_base_s=0.001,
            backoff_max_s=0.01,
            jitter_ratio=0,
            rng=zero_rng,
            rate_limit_threshold=2,
        )
        gate = LLMGate(cfg)
        chat_fn, calls = make_chat_fn(
            raises_sequence=[
                LLMRateLimitError("429"),
                LLMRateLimitError("429"),
            ],
            returns=LLMResponse(model="gpt-4o-mini", content="fallback_answer"),
        )
        result = await gate.chat(chat_fn, [], op_key="rl")
        assert result.content == "fallback_answer"
        # Third call should have used the fallback model.
        assert calls[-1][0] == "gpt-4o-mini"
        assert gate.metrics.fallback_uses >= 1

    async def test_success_resets_consecutive_rate_limit_counter(self) -> None:
        cfg = LLMGateConfig(
            primary_model="gpt-4o",
            max_retries=5,
            backoff_base_s=0.001,
            backoff_max_s=0.01,
            jitter_ratio=0,
            rng=zero_rng,
        )
        gate = LLMGate(cfg)
        chat_fn, _ = make_chat_fn(
            raises_sequence=[LLMRateLimitError("429")],
            returns=LLMResponse(model="gpt-4o", content="ok"),
        )
        await gate.chat(chat_fn, [], op_key="rl")
        assert gate._consecutive_rate_limits == 0


# ── Retry + exhaustion ───────────────────────────────────────────


class TestRetryAndExhaustion:
    async def test_retry_on_network_error(self) -> None:
        cfg = LLMGateConfig(
            primary_model="gpt-4o",
            max_retries=3,
            backoff_base_s=0.001,
            backoff_max_s=0.005,
            jitter_ratio=0,
            rng=zero_rng,
        )
        gate = LLMGate(cfg)
        chat_fn, calls = make_chat_fn(
            raises_sequence=[
                RuntimeError("network"),
                RuntimeError("network"),
            ],
            returns=LLMResponse(model="gpt-4o", content="ok"),
        )
        result = await gate.chat(chat_fn, [], op_key="net")
        assert result.content == "ok"
        assert len(calls) == 3
        assert gate.metrics.retries == 2

    async def test_exhausts_retries_raises_unavailable(self) -> None:
        cfg = LLMGateConfig(
            primary_model="gpt-4o",
            max_retries=2,
            backoff_base_s=0.001,
            backoff_max_s=0.005,
            jitter_ratio=0,
            rng=zero_rng,
        )
        gate = LLMGate(cfg)
        chat_fn, _ = make_chat_fn(
            raises_sequence=[
                RuntimeError("e1"),
                RuntimeError("e2"),
                RuntimeError("e3"),
            ],
        )
        with pytest.raises(LLMUnavailableError) as excinfo:
            await gate.chat(chat_fn, [], op_key="fail")
        assert excinfo.value.last_error is not None
        assert gate.metrics.exhausted == 1


# ── Hard timeout ─────────────────────────────────────────────────


class TestHardTimeout:
    async def test_slow_call_raises_hard_timeout(self) -> None:
        cfg = LLMGateConfig(
            primary_model="gpt-4o",
            soft_timeout_s=0.05,
            hard_timeout_s=0.1,
        )
        gate = LLMGate(cfg)

        async def slow_chat(model: str, messages: Sequence[dict[str, Any]]) -> LLMResponse:
            await asyncio.sleep(1.0)
            return LLMResponse(model=model, content="late")

        with pytest.raises(LLMHardTimeoutError):
            await gate.chat(slow_chat, [], op_key="slow")
        assert gate.metrics.hard_timeouts == 1

    async def test_soft_timeout_logs_warning_but_returns(self) -> None:
        cfg = LLMGateConfig(
            primary_model="gpt-4o",
            soft_timeout_s=0.02,
            hard_timeout_s=1.0,
        )
        gate = LLMGate(cfg)

        async def sluggish(model: str, messages: Sequence[dict[str, Any]]) -> LLMResponse:
            await asyncio.sleep(0.05)
            return LLMResponse(model=model, content="slow_ok")

        result = await gate.chat(sluggish, [], op_key="slow")
        assert result.content == "slow_ok"
        assert gate.metrics.soft_timeout_warnings == 1


# ── Prefer fallback ──────────────────────────────────────────────


class TestPreferFallback:
    async def test_prefer_fallback_uses_fallback_model_on_first_call(self) -> None:
        cfg = LLMGateConfig(
            primary_model="gpt-4o",
            fallback_model="gpt-4o-mini",
        )
        gate = LLMGate(cfg)
        chat_fn, calls = make_chat_fn()
        await gate.chat(chat_fn, [], op_key="pf", prefer_fallback=True)
        assert calls[0][0] == "gpt-4o-mini"


# ── Backoff budget guard ────────────────────────────────────────


class TestBackoffBudgetGuard:
    async def test_backoff_exceeding_hard_timeout_raises(self) -> None:
        """If the next retry sleep would push total elapsed past
        hard_timeout_s, the gate must raise instead of sleeping.
        """
        cfg = LLMGateConfig(
            primary_model="gpt-4o",
            soft_timeout_s=0.01,
            hard_timeout_s=0.05,
            max_retries=5,
            backoff_base_s=1.0,
            backoff_max_s=1.0,
            jitter_ratio=0,
            rng=zero_rng,
        )
        gate = LLMGate(cfg)
        chat_fn, _ = make_chat_fn(
            raises_sequence=[RuntimeError("e")],
        )
        with pytest.raises(LLMHardTimeoutError):
            await gate.chat(chat_fn, [], op_key="budget")
