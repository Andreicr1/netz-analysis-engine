"""Tests for ``ExternalProviderGate`` (Stability Guardrails §2.5)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.runtime.provider_gate import (
    ExternalProviderGate,
    GateConfig,
    GateState,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


def make_gate(
    *,
    failure_threshold: int = 3,
    timeout_s: float = 0.5,
    recovery_after_s: float = 0.1,
    cache_ttl_s: float | None = None,
) -> ExternalProviderGate[int]:
    return ExternalProviderGate[int](
        GateConfig(
            name="test_provider",
            timeout_s=timeout_s,
            failure_threshold=failure_threshold,
            recovery_after_s=recovery_after_s,
            cache_ttl_s=cache_ttl_s,
        ),
    )


class TestConfigValidation:
    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name"):
            GateConfig(name="", timeout_s=1.0)

    def test_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="timeout_s"):
            GateConfig(name="p", timeout_s=0)

    def test_failure_threshold_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="failure_threshold"):
            GateConfig(name="p", timeout_s=1.0, failure_threshold=0)

    def test_recovery_after_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="recovery_after_s"):
            GateConfig(name="p", timeout_s=1.0, recovery_after_s=0)

    def test_cache_ttl_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="cache_ttl_s"):
            GateConfig(name="p", timeout_s=1.0, cache_ttl_s=-1.0)


class TestHappyPath:
    async def test_successful_call_returns_result(self) -> None:
        gate = make_gate()

        async def ok() -> int:
            return 42

        assert await gate.call("op", ok) == 42
        assert gate.state == GateState.CLOSED
        assert gate.metrics.successes == 1

    async def test_cache_hit_on_successive_calls(self) -> None:
        gate = make_gate(cache_ttl_s=60)
        calls = 0

        async def factory() -> int:
            nonlocal calls
            calls += 1
            return 7

        await gate.call("op", factory)
        # Cache is only consulted when the circuit is OPEN — a second
        # call with CLOSED circuit still executes the factory (see
        # "Non-goals: no request coalescing" in the module docstring).
        # This matches SingleFlightLock separation of concerns.
        await gate.call("op", factory)
        assert calls == 2


class TestTimeout:
    async def test_timeout_raises_provider_timeout_error(self) -> None:
        gate = make_gate(timeout_s=0.05)

        async def slow() -> int:
            await asyncio.sleep(1.0)
            return 1

        with pytest.raises(ProviderTimeoutError):
            await gate.call("op", slow)
        assert gate.metrics.timeouts == 1
        assert gate.metrics.failures == 1

    async def test_timeout_counts_toward_circuit_open(self) -> None:
        gate = make_gate(timeout_s=0.02, failure_threshold=2)

        async def slow() -> int:
            await asyncio.sleep(1.0)
            return 1

        with pytest.raises(ProviderTimeoutError):
            await gate.call("op", slow)
        with pytest.raises(ProviderTimeoutError):
            await gate.call("op", slow)
        assert gate.state == GateState.OPEN


class TestCircuitBreaker:
    async def test_circuit_opens_after_threshold(self) -> None:
        gate = make_gate(failure_threshold=3)

        async def failing() -> int:
            raise RuntimeError("nope")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await gate.call("op", failing)
        assert gate.state == GateState.OPEN
        assert gate.metrics.circuit_opens == 1

    async def test_open_circuit_rejects_without_calling(self) -> None:
        gate = make_gate(failure_threshold=1)
        calls = 0

        async def failing() -> int:
            nonlocal calls
            calls += 1
            raise RuntimeError("bad")

        with pytest.raises(RuntimeError):
            await gate.call("op", failing)
        # Circuit open — next call should not touch the factory.
        with pytest.raises(ProviderUnavailableError):
            await gate.call("op", failing)
        assert calls == 1
        assert gate.metrics.rejected_open == 1

    async def test_on_open_fallback_used_when_circuit_open(self) -> None:
        gate = make_gate(failure_threshold=1)

        async def failing() -> int:
            raise RuntimeError("bad")

        with pytest.raises(RuntimeError):
            await gate.call("op", failing)
        result = await gate.call("op", failing, on_open=lambda: -1)
        assert result == -1

    async def test_cache_fallback_used_when_circuit_open(self) -> None:
        gate = make_gate(failure_threshold=1, cache_ttl_s=60)
        state = {"fail": False}

        async def maybe() -> int:
            if state["fail"]:
                raise RuntimeError("bad")
            return 99

        # Seed the cache with a success.
        assert await gate.call("op", maybe) == 99
        state["fail"] = True
        with pytest.raises(RuntimeError):
            await gate.call("op", maybe)
        # Circuit now open; cache still has 99.
        assert await gate.call("op", maybe) == 99
        assert gate.metrics.cache_hits >= 1

    async def test_success_resets_consecutive_failures(self) -> None:
        gate = make_gate(failure_threshold=3)
        state = {"fail": True}

        async def maybe() -> int:
            if state["fail"]:
                raise RuntimeError("bad")
            return 1

        with pytest.raises(RuntimeError):
            await gate.call("op", maybe)
        with pytest.raises(RuntimeError):
            await gate.call("op", maybe)
        state["fail"] = False
        assert await gate.call("op", maybe) == 1
        # Consecutive failures reset → circuit still closed.
        state["fail"] = True
        with pytest.raises(RuntimeError):
            await gate.call("op", maybe)
        assert gate.state == GateState.CLOSED


class TestRecovery:
    async def test_probe_after_recovery_closes_circuit(self) -> None:
        gate = make_gate(failure_threshold=1, recovery_after_s=0.05)
        state = {"fail": True}

        async def maybe() -> int:
            if state["fail"]:
                raise RuntimeError("bad")
            return 1

        with pytest.raises(RuntimeError):
            await gate.call("op", maybe)
        assert gate.state == GateState.OPEN

        # Wait for recovery window.
        await asyncio.sleep(0.1)
        state["fail"] = False
        # Next call is the probe.
        assert await gate.call("op", maybe) == 1
        assert gate.state == GateState.CLOSED

    async def test_probe_failure_reopens_circuit(self) -> None:
        gate = make_gate(failure_threshold=1, recovery_after_s=0.05)

        async def failing() -> int:
            raise RuntimeError("bad")

        with pytest.raises(RuntimeError):
            await gate.call("op", failing)
        await asyncio.sleep(0.1)
        with pytest.raises(RuntimeError):
            await gate.call("op", failing)
        assert gate.state == GateState.OPEN


class TestInvalidation:
    async def test_invalidate_cache_single_key(self) -> None:
        gate = make_gate(cache_ttl_s=60)

        async def factory() -> int:
            return 1

        await gate.call("op", factory)
        gate.invalidate_cache("op")
        assert gate._cache == {}

    async def test_invalidate_cache_all(self) -> None:
        gate = make_gate(cache_ttl_s=60)

        async def factory() -> int:
            return 1

        await gate.call("a", factory)
        await gate.call("b", factory)
        gate.invalidate_cache()
        assert gate._cache == {}

    async def test_reset_returns_to_closed(self) -> None:
        gate = make_gate(failure_threshold=1)

        async def failing() -> int:
            raise RuntimeError("bad")

        with pytest.raises(RuntimeError):
            await gate.call("op", failing)
        assert gate.state == GateState.OPEN
        gate.reset()
        assert gate.state == GateState.CLOSED
