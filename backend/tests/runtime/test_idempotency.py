"""Tests for ``@idempotent`` decorator (Stability Guardrails §2.7)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.runtime.idempotency import (
    InMemoryIdempotencyStorage,
    idempotent,
)

# ── Helpers ───────────────────────────────────────────────────────


def make_key(*args: Any, **kwargs: Any) -> str:
    """Test key extractor: uses the ``identifier`` kwarg verbatim."""
    return f"test:{kwargs['identifier']}"


class TestCacheHit:
    async def test_second_call_returns_cached_result(self) -> None:
        storage = InMemoryIdempotencyStorage()
        calls = 0

        @idempotent(key=make_key, ttl_s=60, storage=storage)
        async def handler(*, identifier: str) -> dict:
            nonlocal calls
            calls += 1
            return {"identifier": identifier, "count": calls}

        first = await handler(identifier="SPY")
        second = await handler(identifier="SPY")
        assert first == second
        assert calls == 1

    async def test_different_keys_isolated(self) -> None:
        storage = InMemoryIdempotencyStorage()

        @idempotent(key=make_key, ttl_s=60, storage=storage)
        async def handler(*, identifier: str) -> dict:
            return {"id": identifier}

        a = await handler(identifier="SPY")
        b = await handler(identifier="QQQ")
        assert a != b


class TestConcurrentDedupe:
    async def test_concurrent_callers_share_execution(self) -> None:
        storage = InMemoryIdempotencyStorage()
        calls = 0
        release = asyncio.Event()

        @idempotent(
            key=make_key,
            ttl_s=60,
            storage=storage,
            wait_poll_s=0.01,
            wait_timeout_s=5.0,
        )
        async def handler(*, identifier: str) -> dict:
            nonlocal calls
            calls += 1
            await release.wait()
            return {"id": identifier, "n": calls}

        # Fire 5 concurrent calls for the same key.
        tasks = [
            asyncio.create_task(handler(identifier="SPY"))
            for _ in range(5)
        ]
        await asyncio.sleep(0.02)
        release.set()
        results = await asyncio.gather(*tasks)

        # Only one execution, all callers observe the same dict.
        assert calls == 1
        assert all(r == results[0] for r in results)


class TestFailureHandling:
    async def test_exception_releases_lock_and_skips_cache(self) -> None:
        storage = InMemoryIdempotencyStorage()
        calls = 0

        @idempotent(key=make_key, ttl_s=60, storage=storage)
        async def handler(*, identifier: str) -> dict:
            nonlocal calls
            calls += 1
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await handler(identifier="SPY")
        with pytest.raises(RuntimeError):
            await handler(identifier="SPY")
        # No cache → second call executed again.
        assert calls == 2


class TestGracefulDegradation:
    async def test_storage_get_result_failure_executes_without_cache(self) -> None:
        class BrokenStorage(InMemoryIdempotencyStorage):
            async def get_result(self, key: str) -> bytes | None:
                raise RuntimeError("redis down")

        storage = BrokenStorage()
        calls = 0

        @idempotent(key=make_key, ttl_s=60, storage=storage)
        async def handler(*, identifier: str) -> dict:
            nonlocal calls
            calls += 1
            return {"n": calls}

        # Both calls execute — storage fail-open.
        await handler(identifier="SPY")
        await handler(identifier="SPY")
        assert calls == 2

    async def test_storage_acquire_failure_executes_without_lock(self) -> None:
        class BrokenStorage(InMemoryIdempotencyStorage):
            async def try_acquire(self, key: str, ttl_s: int) -> bool:
                raise RuntimeError("redis down")

        storage = BrokenStorage()
        calls = 0

        @idempotent(key=make_key, ttl_s=60, storage=storage)
        async def handler(*, identifier: str) -> dict:
            nonlocal calls
            calls += 1
            return {"n": calls}

        await handler(identifier="SPY")
        await handler(identifier="SPY")
        assert calls == 2

    async def test_key_extractor_failure_executes_without_cache(self) -> None:
        storage = InMemoryIdempotencyStorage()
        calls = 0

        def bad_key(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("missing identifier")

        @idempotent(key=bad_key, ttl_s=60, storage=storage)
        async def handler() -> dict:
            nonlocal calls
            calls += 1
            return {"n": calls}

        await handler()
        await handler()
        assert calls == 2


class TestTTLExpiry:
    async def test_ttl_expiry_refreshes_cache(self) -> None:
        storage = InMemoryIdempotencyStorage()
        calls = 0

        @idempotent(key=make_key, ttl_s=1, storage=storage)
        async def handler(*, identifier: str) -> dict:
            nonlocal calls
            calls += 1
            return {"n": calls}

        await handler(identifier="SPY")
        # Manually expire the in-memory entries.
        storage._results.clear()
        storage._locks.clear()
        await handler(identifier="SPY")
        assert calls == 2


class TestConfigValidation:
    def test_ttl_must_be_positive(self) -> None:
        storage = InMemoryIdempotencyStorage()
        with pytest.raises(ValueError, match="ttl_s"):

            @idempotent(key=make_key, ttl_s=0, storage=storage)
            async def handler(*, identifier: str) -> dict:
                return {}

    def test_wait_timeout_must_be_positive(self) -> None:
        storage = InMemoryIdempotencyStorage()
        with pytest.raises(ValueError, match="wait_timeout_s"):

            @idempotent(
                key=make_key,
                ttl_s=60,
                storage=storage,
                wait_timeout_s=0,
            )
            async def handler(*, identifier: str) -> dict:
                return {}
