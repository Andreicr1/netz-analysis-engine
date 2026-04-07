"""Tests for ``@idempotent`` decorator (Stability Guardrails §2.7).

Coverage of fail-open paths is mandatory: in institutional wealth
management, the error-handling branches are the most operationally
critical part of the primitive. Every storage exception, every
decode failure, every wait-timeout has its own test. A regression
in one of these branches would silently corrupt mutating routes
under Redis pressure.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import orjson
import pytest

from app.core.runtime.idempotency import (
    InMemoryIdempotencyStorage,
    RedisIdempotencyStorage,
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


# ── In-memory storage internals ───────────────────────────────────


class TestInMemoryStorage:
    async def test_get_result_evicts_expired_entry(self) -> None:
        storage = InMemoryIdempotencyStorage()
        await storage.set_result("k", b'{"x": 1}', ttl_s=1)
        # Force expiry by mutating the internal record.
        storage._results["k"] = (b'{"x": 1}', time.monotonic() - 0.1)
        result = await storage.get_result("k")
        assert result is None
        assert "k" not in storage._results

    async def test_try_acquire_blocks_until_lock_expires(self) -> None:
        storage = InMemoryIdempotencyStorage()
        assert await storage.try_acquire("k", ttl_s=60)
        assert not await storage.try_acquire("k", ttl_s=60)
        # Force lock expiry.
        storage._locks["k"] = time.monotonic() - 0.1
        assert await storage.try_acquire("k", ttl_s=60)


# ── Redis storage (with a fake redis client) ─────────────────────


class FakeRedis:
    """Minimal aioredis stand-in for testing RedisIdempotencyStorage.

    Implements just enough of the SET/GET/DELETE surface that the
    storage uses. ``raise_on`` lets a single method raise on demand
    so we can exercise the storage's exception paths.
    """

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.locks: set[str] = set()
        self.raise_on: set[str] = set()
        self.delete_called: list[str] = []

    async def set(
        self,
        key: str,
        value: Any,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        if "set" in self.raise_on:
            raise RuntimeError("forced redis set failure")
        if nx:
            if key in self.locks:
                return None
            self.locks.add(key)
            return True
        self.store[key] = value if isinstance(value, bytes) else str(value).encode()
        return True

    async def get(self, key: str) -> bytes | None:
        if "get" in self.raise_on:
            raise RuntimeError("forced redis get failure")
        return self.store.get(key)

    async def delete(self, key: str) -> int:
        self.delete_called.append(key)
        if "delete" in self.raise_on:
            raise RuntimeError("forced redis delete failure")
        had_lock = key in self.locks
        self.locks.discard(key)
        return 1 if had_lock else 0


class TestRedisIdempotencyStorage:
    async def test_try_acquire_success_and_collision(self) -> None:
        redis = FakeRedis()
        storage = RedisIdempotencyStorage(redis)
        assert await storage.try_acquire("k", ttl_s=60)
        # Second attempt fails until released.
        assert not await storage.try_acquire("k", ttl_s=60)

    async def test_release_uses_lock_prefix(self) -> None:
        redis = FakeRedis()
        storage = RedisIdempotencyStorage(redis)
        await storage.try_acquire("k", ttl_s=60)
        await storage.release("k")
        assert redis.delete_called == [f"{storage.LOCK_PREFIX}k"]

    async def test_release_swallows_redis_exception(self) -> None:
        redis = FakeRedis()
        redis.raise_on.add("delete")
        storage = RedisIdempotencyStorage(redis)
        # Must not raise even though redis.delete raises.
        await storage.release("k")

    async def test_set_and_get_result_roundtrip(self) -> None:
        redis = FakeRedis()
        storage = RedisIdempotencyStorage(redis)
        await storage.set_result("k", b'{"hello": "world"}', ttl_s=60)
        got = await storage.get_result("k")
        assert got == b'{"hello": "world"}'

    async def test_get_result_returns_none_on_miss(self) -> None:
        redis = FakeRedis()
        storage = RedisIdempotencyStorage(redis)
        assert await storage.get_result("missing") is None

    async def test_get_result_decodes_string_payload(self) -> None:
        """aioredis may return ``str`` if decode_responses=True is set
        on the connection. The storage should normalise to bytes.
        """
        redis = FakeRedis()
        # Inject a str payload directly to bypass set() normalisation.
        redis.store[f"{RedisIdempotencyStorage.RESULT_PREFIX}k"] = "raw-str"  # type: ignore[assignment]
        storage = RedisIdempotencyStorage(redis)
        got = await storage.get_result("k")
        assert got == b"raw-str"


# ── Decoder + storage failure branches in the decorator ─────────


class TestDecoderAndStorageFailures:
    async def test_corrupted_cache_treats_as_miss(self) -> None:
        """orjson decode failure on the cache hit should fall through
        to a fresh execution rather than crashing the request.
        """
        storage = InMemoryIdempotencyStorage()
        # Pre-seed the cache with garbage that orjson cannot parse.
        await storage.set_result(
            "test:SPY",
            b"\x00\x01not-json",
            ttl_s=60,
        )
        calls = 0

        @idempotent(key=make_key, ttl_s=60, storage=storage)
        async def handler(*, identifier: str) -> dict:
            nonlocal calls
            calls += 1
            return {"n": calls}

        result = await handler(identifier="SPY")
        assert calls == 1
        assert result == {"n": 1}

    async def test_release_exception_after_handler_raises_is_swallowed(
        self,
    ) -> None:
        class ReleaseBroken(InMemoryIdempotencyStorage):
            async def release(self, key: str) -> None:
                raise RuntimeError("release exploded")

        storage = ReleaseBroken()

        @idempotent(key=make_key, ttl_s=60, storage=storage)
        async def handler(*, identifier: str) -> dict:
            raise ValueError("business error")

        # Original exception should propagate, release exception swallowed.
        with pytest.raises(ValueError, match="business error"):
            await handler(identifier="SPY")

    async def test_set_result_exception_does_not_break_caller(self) -> None:
        class SetResultBroken(InMemoryIdempotencyStorage):
            async def set_result(self, key: str, value: bytes, ttl_s: int) -> None:
                raise RuntimeError("storage write failed")

        storage = SetResultBroken()
        calls = 0

        @idempotent(key=make_key, ttl_s=60, storage=storage)
        async def handler(*, identifier: str) -> dict:
            nonlocal calls
            calls += 1
            return {"n": calls}

        # The handler must still return its result even though the
        # cache write blew up.
        result = await handler(identifier="SPY")
        assert result == {"n": 1}

    async def test_release_exception_after_success_is_swallowed(self) -> None:
        """release() raising in the success-path finally must not
        propagate — the user already has their answer.
        """

        class ReleaseBroken(InMemoryIdempotencyStorage):
            async def release(self, key: str) -> None:
                raise RuntimeError("release exploded")

        storage = ReleaseBroken()

        @idempotent(key=make_key, ttl_s=60, storage=storage)
        async def handler(*, identifier: str) -> dict:
            return {"id": identifier}

        result = await handler(identifier="SPY")
        assert result == {"id": "SPY"}


# ── Waiter (concurrent caller) failure paths ────────────────────


class TestWaiterFailurePaths:
    async def test_waiter_get_result_exception_falls_open(self) -> None:
        """If get_result raises while a waiter is polling, the waiter
        breaks out of the poll loop and executes the function itself
        rather than blocking forever.

        Only the first invocation blocks on the gate; the fall-open
        execution by the waiter must NOT be re-blocked, otherwise the
        test would deadlock.
        """
        gate = asyncio.Event()
        get_call_count = 0

        class WaiterBroken(InMemoryIdempotencyStorage):
            async def get_result(self, key: str) -> bytes | None:
                nonlocal get_call_count
                get_call_count += 1
                # First poll: cache miss (returns None).
                # Subsequent polls (waiter polling loop): raise.
                if get_call_count <= 1:
                    return await super().get_result(key)
                raise RuntimeError("redis get exploded")

        storage = WaiterBroken()
        executed: list[int] = []

        @idempotent(
            key=make_key,
            ttl_s=60,
            storage=storage,
            wait_poll_s=0.01,
            wait_timeout_s=2.0,
        )
        async def handler(*, identifier: str) -> dict:
            n = len(executed) + 1
            executed.append(n)
            if n == 1:
                # Only the first invocation holds the lock open.
                await gate.wait()
            return {"id": identifier, "n": n}

        first = asyncio.create_task(handler(identifier="SPY"))
        # Let the first call enter the lock.
        await asyncio.sleep(0.05)
        second = asyncio.create_task(handler(identifier="SPY"))
        # Let the waiter enter its polling loop and observe the
        # broken get_result.
        await asyncio.sleep(0.1)
        gate.set()
        results = await asyncio.gather(first, second)
        assert results[0]["n"] == 1
        assert results[1]["n"] == 2  # waiter fell open and executed
        assert executed == [1, 2]

    async def test_waiter_corrupt_cache_falls_open(self) -> None:
        """If a waiter sees a cached payload but it fails to decode,
        the waiter breaks out of the loop and executes the function
        rather than serving garbage.
        """
        gate = asyncio.Event()

        class CorruptCache(InMemoryIdempotencyStorage):
            async def set_result(self, key: str, value: bytes, ttl_s: int) -> None:
                # Corrupt the value before storing — the waiter will
                # fail to decode it on its next poll.
                await super().set_result(key, b"\x00garbage", ttl_s)

        storage = CorruptCache()
        executed: list[int] = []

        @idempotent(
            key=make_key,
            ttl_s=60,
            storage=storage,
            wait_poll_s=0.01,
            wait_timeout_s=2.0,
        )
        async def handler(*, identifier: str) -> dict:
            n = len(executed) + 1
            executed.append(n)
            if n == 1:
                await gate.wait()
            return {"id": identifier, "n": n}

        first = asyncio.create_task(handler(identifier="SPY"))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(handler(identifier="SPY"))
        await asyncio.sleep(0.05)
        gate.set()
        results = await asyncio.gather(first, second)
        assert results[0]["n"] == 1
        assert results[1]["n"] == 2
        assert executed == [1, 2]

    async def test_waiter_timeout_falls_open(self) -> None:
        """If the waiter never sees a result within wait_timeout_s
        (the holder is hung), the waiter executes the function
        directly rather than blocking forever.
        """
        gate = asyncio.Event()
        executed: list[int] = []

        @idempotent(
            key=make_key,
            ttl_s=60,
            storage=InMemoryIdempotencyStorage(),
            wait_poll_s=0.02,
            wait_timeout_s=0.1,  # very short — first call will not finish in time
        )
        async def handler(*, identifier: str) -> dict:
            n = len(executed) + 1
            executed.append(n)
            if n == 1:
                await gate.wait()
            return {"id": identifier, "n": n}

        first = asyncio.create_task(handler(identifier="SPY"))
        await asyncio.sleep(0.02)
        # Second call: waiter will time out before first call resolves
        # and fall open to execute the handler directly.
        second_result = await handler(identifier="SPY")
        assert second_result["n"] == 2
        assert executed == [1, 2]
        # Clean up the still-blocked first call.
        gate.set()
        await first


# ── Sanity check that the orjson dependency is what we think ────


class TestOrjsonContract:
    """If orjson ever changes its decode error type, this primitive
    needs to know — the decorator catches ``orjson.JSONDecodeError``
    explicitly. Pin the contract here so a silent upstream change
    breaks tests instead of production.
    """

    def test_decode_error_type_is_jsondecodeerror(self) -> None:
        with pytest.raises(orjson.JSONDecodeError):
            orjson.loads(b"\x00not-json")
