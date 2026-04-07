"""Tests for ``SingleFlightLock`` (Stability Guardrails §2.3)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.runtime.single_flight import SingleFlightLock


class TestBasicExecution:
    async def test_single_call_executes_factory_once(self) -> None:
        lock: SingleFlightLock[str, int] = SingleFlightLock()
        calls = 0

        async def factory() -> int:
            nonlocal calls
            calls += 1
            return 42

        assert await lock.run("k", factory) == 42
        assert calls == 1

    async def test_different_keys_are_isolated(self) -> None:
        lock: SingleFlightLock[str, str] = SingleFlightLock()

        async def make_factory(value: str):
            async def f() -> str:
                return value
            return f

        r1 = await lock.run("a", await make_factory("first"))
        r2 = await lock.run("b", await make_factory("second"))
        assert r1 == "first"
        assert r2 == "second"


class TestConcurrentDeduplication:
    async def test_concurrent_calls_share_single_execution(self) -> None:
        lock: SingleFlightLock[str, int] = SingleFlightLock()
        calls = 0
        release = asyncio.Event()

        async def slow_factory() -> int:
            nonlocal calls
            calls += 1
            await release.wait()
            return 7

        tasks = [
            asyncio.create_task(lock.run("same", slow_factory))
            for _ in range(10)
        ]
        # Give all 10 tasks a chance to enter the lock.
        await asyncio.sleep(0.01)
        release.set()
        results = await asyncio.gather(*tasks)

        assert results == [7] * 10
        assert calls == 1

    async def test_sequential_calls_after_flight_rerun(self) -> None:
        """Without a TTL, completed flights do not cache — subsequent
        calls should re-execute the factory.
        """
        lock: SingleFlightLock[str, int] = SingleFlightLock()
        calls = 0

        async def factory() -> int:
            nonlocal calls
            calls += 1
            return calls

        assert await lock.run("k", factory) == 1
        assert await lock.run("k", factory) == 2
        assert await lock.run("k", factory) == 3


class TestExceptions:
    async def test_exception_propagates_to_every_waiter(self) -> None:
        lock: SingleFlightLock[str, int] = SingleFlightLock()
        release = asyncio.Event()

        async def failing_factory() -> int:
            await release.wait()
            raise ValueError("boom")

        tasks = [
            asyncio.create_task(lock.run("k", failing_factory))
            for _ in range(5)
        ]
        await asyncio.sleep(0.01)
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert all(isinstance(r, ValueError) and str(r) == "boom" for r in results)

    async def test_exception_does_not_populate_cache(self) -> None:
        lock: SingleFlightLock[str, int] = SingleFlightLock()
        calls = 0

        async def failing_factory() -> int:
            nonlocal calls
            calls += 1
            raise RuntimeError("bad")

        with pytest.raises(RuntimeError):
            await lock.run("k", failing_factory, ttl_s=60)
        with pytest.raises(RuntimeError):
            await lock.run("k", failing_factory, ttl_s=60)
        assert calls == 2  # cache never stored the failed result


class TestCancellation:
    async def test_cancellation_propagates_to_waiters(self) -> None:
        lock: SingleFlightLock[str, int] = SingleFlightLock()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def factory() -> int:
            entered.set()
            await release.wait()
            return 1

        first = asyncio.create_task(lock.run("k", factory))
        await entered.wait()

        # Start a second waiter.
        second = asyncio.create_task(lock.run("k", factory))
        await asyncio.sleep(0.01)

        # Cancel the original flight.
        first.cancel()

        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(asyncio.CancelledError):
            await second

    async def test_flight_removed_after_cancellation(self) -> None:
        """Once a cancelled flight clears, a new call must be able
        to start a fresh flight (lock is not left in a dead state).
        """
        lock: SingleFlightLock[str, int] = SingleFlightLock()
        release = asyncio.Event()

        async def factory_blocking() -> int:
            await release.wait()
            return 1

        task = asyncio.create_task(lock.run("k", factory_blocking))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Fresh call should work.
        async def factory_fast() -> int:
            return 99

        assert await lock.run("k", factory_fast) == 99


class TestTTLCache:
    async def test_ttl_cache_hits_skip_factory(self) -> None:
        lock: SingleFlightLock[str, int] = SingleFlightLock()
        calls = 0

        async def factory() -> int:
            nonlocal calls
            calls += 1
            return 123

        assert await lock.run("k", factory, ttl_s=60) == 123
        assert await lock.run("k", factory, ttl_s=60) == 123
        assert await lock.run("k", factory, ttl_s=60) == 123
        assert calls == 1

    async def test_ttl_expiry_triggers_refresh(self) -> None:
        lock: SingleFlightLock[str, int] = SingleFlightLock()
        calls = 0

        async def factory() -> int:
            nonlocal calls
            calls += 1
            return calls

        # TTL of 0.05s → cache expires quickly.
        assert await lock.run("k", factory, ttl_s=0.05) == 1
        assert await lock.run("k", factory, ttl_s=0.05) == 1
        await asyncio.sleep(0.1)
        assert await lock.run("k", factory, ttl_s=0.05) == 2
        assert calls == 2

    async def test_invalidate_removes_cache(self) -> None:
        lock: SingleFlightLock[str, int] = SingleFlightLock()
        calls = 0

        async def factory() -> int:
            nonlocal calls
            calls += 1
            return calls

        await lock.run("k", factory, ttl_s=60)
        assert lock.invalidate("k") is True
        assert lock.invalidate("k") is False  # already gone
        await lock.run("k", factory, ttl_s=60)
        assert calls == 2

    async def test_clear_removes_all_cache(self) -> None:
        lock: SingleFlightLock[str, int] = SingleFlightLock()

        async def make_factory(v: int):
            async def f() -> int:
                return v
            return f

        await lock.run("a", await make_factory(1), ttl_s=60)
        await lock.run("b", await make_factory(2), ttl_s=60)
        lock.clear()
        assert lock._cache == {}
