"""Tests for ``BoundedOutboundChannel`` (Stability Guardrails §2.1).

Every assertion here exists to prove one behavioral guarantee from the
design spec. When a guarantee changes, update both the test and the
module docstring — never just one.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.runtime.outbound_channel import (
    BoundedOutboundChannel,
    ChannelConfig,
    DropPolicy,
)

# ── Test doubles ───────────────────────────────────────────────────


class FakeWebSocket:
    """Deterministic WebSocket stand-in.

    Records every payload sent. Optional per-send delay (constant or
    per-call callable) lets tests simulate slow or hanging clients
    without real sockets.
    """

    def __init__(
        self,
        *,
        delay: float | None = None,
        hangs: bool = False,
        raises: type[BaseException] | None = None,
    ) -> None:
        self.sent: list[bytes] = []
        self._delay = delay
        self._hangs = hangs
        self._raises = raises

    async def send_bytes(self, data: bytes) -> None:
        if self._raises is not None:
            raise self._raises("forced send failure")
        if self._hangs:
            # Wait longer than any test send_timeout_s; the channel's
            # wait_for must cancel us.
            await asyncio.sleep(10.0)
        if self._delay:
            await asyncio.sleep(self._delay)
        self.sent.append(data)


# ── Config validation ─────────────────────────────────────────────


class TestChannelConfigValidation:
    def test_max_queued_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_queued"):
            ChannelConfig(max_queued=0)

    def test_send_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="send_timeout_s"):
            ChannelConfig(send_timeout_s=0)

    def test_eviction_threshold_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="eviction_threshold"):
            ChannelConfig(eviction_threshold=0)

    def test_drain_grace_must_be_non_negative(self) -> None:
        with pytest.raises(ValueError, match="drain_grace_s"):
            ChannelConfig(drain_grace_s=-0.1)

    def test_defaults_are_sane(self) -> None:
        cfg = ChannelConfig()
        assert cfg.max_queued == 256
        assert cfg.send_timeout_s == 2.0
        assert cfg.drop_policy is DropPolicy.DROP_OLDEST
        assert cfg.eviction_threshold == 3


# ── Offer semantics ───────────────────────────────────────────────


class TestOfferSemantics:
    async def test_offer_accepts_up_to_max_queued(self) -> None:
        ws = FakeWebSocket(hangs=True)  # nothing ever drains
        cfg = ChannelConfig(max_queued=3, send_timeout_s=5.0)
        ch = BoundedOutboundChannel(ws, cfg)
        # Intentionally no start() — we want to observe raw queue semantics.
        assert ch.offer(b"a") is True
        assert ch.offer(b"b") is True
        assert ch.offer(b"c") is True
        assert ch.metrics.accepted == 3
        assert ch.metrics.queued == 3

    async def test_drop_oldest_evicts_head_and_accepts_new(self) -> None:
        ws = FakeWebSocket(hangs=True)
        cfg = ChannelConfig(
            max_queued=2,
            drop_policy=DropPolicy.DROP_OLDEST,
            eviction_threshold=10,  # don't trigger eviction here
        )
        ch = BoundedOutboundChannel(ws, cfg)
        assert ch.offer(b"a") is True
        assert ch.offer(b"b") is True
        # Queue at capacity. DROP_OLDEST accepts the new payload and
        # drops b"a".
        assert ch.offer(b"c") is True
        assert list(ch._queue) == [b"b", b"c"]
        assert ch.metrics.dropped == 1

    async def test_drop_newest_rejects_new_and_keeps_head(self) -> None:
        ws = FakeWebSocket(hangs=True)
        cfg = ChannelConfig(
            max_queued=2,
            drop_policy=DropPolicy.DROP_NEWEST,
            eviction_threshold=10,
        )
        ch = BoundedOutboundChannel(ws, cfg)
        assert ch.offer(b"a") is True
        assert ch.offer(b"b") is True
        assert ch.offer(b"c") is False
        assert list(ch._queue) == [b"a", b"b"]
        assert ch.metrics.dropped == 1

    async def test_offer_after_stop_returns_false(self) -> None:
        ws = FakeWebSocket()
        ch = BoundedOutboundChannel(ws, ChannelConfig())
        await ch.start()
        await ch.stop()
        assert ch.offer(b"late") is False


# ── Drain loop: ordering and throughput ──────────────────────────


class TestDrainLoop:
    async def test_drain_sends_in_fifo_order(self) -> None:
        ws = FakeWebSocket()
        ch = BoundedOutboundChannel(ws, ChannelConfig(max_queued=10))
        await ch.start()
        try:
            for i in range(5):
                ch.offer(f"msg-{i}".encode())
            # Give the drain task a few cycles to flush.
            for _ in range(50):
                if len(ws.sent) == 5:
                    break
                await asyncio.sleep(0.01)
        finally:
            await ch.stop()

        assert ws.sent == [b"msg-0", b"msg-1", b"msg-2", b"msg-3", b"msg-4"]
        assert ch.metrics.sent == 5
        assert ch.metrics.accepted == 5

    async def test_successful_send_resets_consecutive_failures(self) -> None:
        ws = FakeWebSocket()
        cfg = ChannelConfig(max_queued=2, eviction_threshold=5)
        ch = BoundedOutboundChannel(ws, cfg)
        await ch.start()
        try:
            # Drive consecutive failures via drop-on-full (no drain
            # because we'll flood faster than the loop can run; use a
            # delay to slow the drain down predictably).
            ws_slow = FakeWebSocket(delay=0.05)
            ch2 = BoundedOutboundChannel(ws_slow, cfg)
            await ch2.start()
            try:
                # Flood beyond capacity to force drops.
                for i in range(10):
                    ch2.offer(f"m{i}".encode())
                # Let the drain catch up fully.
                for _ in range(100):
                    if not ch2._queue and ch2.metrics.sent >= 1:
                        break
                    await asyncio.sleep(0.02)
                assert ch2.metrics.consecutive_failures == 0
            finally:
                await ch2.stop(drain=True)
        finally:
            await ch.stop()


# ── Eviction ──────────────────────────────────────────────────────


class TestEviction:
    async def test_send_timeout_counts_toward_eviction(self) -> None:
        ws = FakeWebSocket(hangs=True)
        cfg = ChannelConfig(
            max_queued=5,
            send_timeout_s=0.05,  # very short — 3 timeouts happen fast
            eviction_threshold=3,
        )
        ch = BoundedOutboundChannel(ws, cfg)
        await ch.start()
        try:
            for i in range(5):
                ch.offer(f"m{i}".encode())
            # Wait long enough for 3 timeouts to fire.
            for _ in range(80):
                if ch.is_evictable:
                    break
                await asyncio.sleep(0.05)
            assert ch.is_evictable, (
                f"expected eviction after {cfg.eviction_threshold} timeouts; "
                f"metrics={ch.metrics}"
            )
            assert ch.metrics.timeouts >= cfg.eviction_threshold
        finally:
            await ch.stop()

    async def test_send_exception_counts_toward_eviction(self) -> None:
        ws = FakeWebSocket(raises=RuntimeError)
        cfg = ChannelConfig(
            max_queued=5,
            send_timeout_s=1.0,
            eviction_threshold=2,
        )
        ch = BoundedOutboundChannel(ws, cfg)
        await ch.start()
        try:
            for i in range(3):
                ch.offer(f"m{i}".encode())
            for _ in range(100):
                if ch.is_evictable:
                    break
                await asyncio.sleep(0.01)
            assert ch.is_evictable
            assert ch.metrics.send_errors >= cfg.eviction_threshold
        finally:
            await ch.stop()

    async def test_drop_oldest_counts_toward_eviction(self) -> None:
        ws = FakeWebSocket(hangs=True)
        cfg = ChannelConfig(
            max_queued=1,
            send_timeout_s=5.0,
            drop_policy=DropPolicy.DROP_OLDEST,
            eviction_threshold=2,
        )
        ch = BoundedOutboundChannel(ws, cfg)
        # Do not start — we want to flood faster than any drain.
        ch.offer(b"a")  # accepted, queue=[a]
        ch.offer(b"b")  # full → DROP_OLDEST, drop=1, queue=[b]
        assert not ch.is_evictable
        ch.offer(b"c")  # full → DROP_OLDEST, drop=2, queue=[c] → evict
        assert ch.is_evictable
        assert ch.metrics.dropped == 2

    async def test_eviction_flag_is_sticky(self) -> None:
        ws = FakeWebSocket()
        cfg = ChannelConfig(
            max_queued=2,
            eviction_threshold=1,
            drop_policy=DropPolicy.DROP_NEWEST,
        )
        ch = BoundedOutboundChannel(ws, cfg)
        await ch.start()
        try:
            # Fill the queue and force one drop → threshold=1 → evicted.
            ch.offer(b"a")
            ch.offer(b"b")
            ch.offer(b"c")  # dropped, evicted=True
            assert ch.is_evictable

            # Let the drain flush everything.
            for _ in range(100):
                if not ch._queue:
                    break
                await asyncio.sleep(0.01)

            # Successful sends should reset the counter but NOT clear
            # the sticky eviction flag.
            assert ch.metrics.consecutive_failures == 0
            assert ch.is_evictable
        finally:
            await ch.stop()


# ── Lifecycle: stop behavior ─────────────────────────────────────


class TestLifecycle:
    async def test_start_is_idempotent(self) -> None:
        ws = FakeWebSocket()
        ch = BoundedOutboundChannel(ws, ChannelConfig())
        await ch.start()
        first_task = ch._drain_task
        await ch.start()
        assert ch._drain_task is first_task
        await ch.stop()

    async def test_stop_is_idempotent(self) -> None:
        ws = FakeWebSocket()
        ch = BoundedOutboundChannel(ws, ChannelConfig())
        await ch.start()
        await ch.stop()
        await ch.stop()  # must not raise

    async def test_stop_with_drain_flushes_queue(self) -> None:
        ws = FakeWebSocket(delay=0.01)
        ch = BoundedOutboundChannel(
            ws,
            ChannelConfig(max_queued=10, send_timeout_s=1.0),
        )
        await ch.start()
        for i in range(5):
            ch.offer(f"m{i}".encode())
        await ch.stop(drain=True)
        assert len(ws.sent) == 5

    async def test_stop_without_drain_cancels_immediately(self) -> None:
        ws = FakeWebSocket(delay=0.5)
        ch = BoundedOutboundChannel(
            ws,
            ChannelConfig(max_queued=100, send_timeout_s=5.0),
        )
        await ch.start()
        for i in range(20):
            ch.offer(f"m{i}".encode())
        # Give the first send a chance to start.
        await asyncio.sleep(0.05)
        await ch.stop(drain=False)
        # Some may have gone through, but not all — proof that
        # cancellation happened mid-flight.
        assert len(ws.sent) < 20

    async def test_stop_drain_grace_timeout_does_not_block_forever(self) -> None:
        ws = FakeWebSocket(hangs=True)
        ch = BoundedOutboundChannel(
            ws,
            ChannelConfig(
                max_queued=5,
                send_timeout_s=0.05,
                drain_grace_s=0.1,
            ),
        )
        await ch.start()
        for i in range(5):
            ch.offer(f"m{i}".encode())
        # stop(drain=True) must return within ~drain_grace_s even
        # though the ws hangs forever.
        await asyncio.wait_for(ch.stop(drain=True), timeout=2.0)

    async def test_is_running_reflects_state(self) -> None:
        ws = FakeWebSocket()
        ch = BoundedOutboundChannel(ws, ChannelConfig())
        assert ch.is_running is False
        await ch.start()
        assert ch.is_running is True
        await ch.stop()
        assert ch.is_running is False
