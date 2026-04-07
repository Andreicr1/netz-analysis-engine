"""Tests for ``RateLimitedBroadcaster`` (Stability Guardrails §2.2).

Every assertion here proves one behavioral guarantee from the design
spec. The focus is on **isolation**: slow consumers must not affect
fast ones, dict mutation must not race with iteration, and the UUID
identity must eliminate any class of ``id(ws)`` collision.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.runtime.broadcaster import (
    BroadcasterClosedError,
    BroadcasterConfig,
    BroadcasterFullError,
    RateLimitedBroadcaster,
    make_connection_id,
)
from app.core.runtime.outbound_channel import ChannelConfig, DropPolicy

# ── Test doubles ───────────────────────────────────────────────────


class FakeWebSocket:
    """Deterministic WS mock with optional delay / hang / raise."""

    def __init__(
        self,
        *,
        name: str = "",
        delay: float | None = None,
        hangs: bool = False,
        raises: type[BaseException] | None = None,
    ) -> None:
        self.name = name
        self.sent: list[bytes] = []
        self._delay = delay
        self._hangs = hangs
        self._raises = raises

    async def send_bytes(self, data: bytes) -> None:
        if self._raises is not None:
            raise self._raises("forced failure")
        if self._hangs:
            await asyncio.sleep(10.0)
        if self._delay:
            await asyncio.sleep(self._delay)
        self.sent.append(data)


async def _flush(delay: float = 0.05, steps: int = 20) -> None:
    """Give the event loop a few cycles to run background tasks."""
    for _ in range(steps):
        await asyncio.sleep(delay)


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def default_channel_cfg() -> ChannelConfig:
    return ChannelConfig(
        max_queued=8,
        send_timeout_s=0.5,
        drop_policy=DropPolicy.DROP_OLDEST,
        eviction_threshold=3,
    )


# ── Config validation ─────────────────────────────────────────────


class TestBroadcasterConfigValidation:
    def test_max_connections_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_connections"):
            BroadcasterConfig(max_connections=0)

    def test_eviction_poll_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="eviction_poll_s"):
            BroadcasterConfig(eviction_poll_s=0)


# ── Attach / detach ───────────────────────────────────────────────


class TestAttachDetach:
    async def test_attach_and_detach_roundtrip(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        try:
            conn_id = make_connection_id()
            await bc.attach(conn_id, FakeWebSocket())
            assert bc.is_attached(conn_id)
            assert bc.attached_count == 1
            detached = await bc.detach(conn_id)
            assert detached is True
            assert bc.attached_count == 0
        finally:
            await bc.close()

    async def test_attach_duplicate_raises(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        try:
            conn_id = make_connection_id()
            await bc.attach(conn_id, FakeWebSocket())
            with pytest.raises(ValueError, match="already attached"):
                await bc.attach(conn_id, FakeWebSocket())
        finally:
            await bc.close()

    async def test_attach_beyond_cap_raises(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(
            default_channel_cfg,
            cfg=BroadcasterConfig(max_connections=2),
        )
        await bc.start()
        try:
            await bc.attach(make_connection_id(), FakeWebSocket())
            await bc.attach(make_connection_id(), FakeWebSocket())
            with pytest.raises(BroadcasterFullError):
                await bc.attach(make_connection_id(), FakeWebSocket())
        finally:
            await bc.close()

    async def test_detach_unknown_returns_false(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        try:
            assert await bc.detach(make_connection_id()) is False
        finally:
            await bc.close()

    async def test_attach_after_close_raises(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        await bc.close()
        with pytest.raises(BroadcasterClosedError):
            await bc.attach(make_connection_id(), FakeWebSocket())

    async def test_peak_attached_tracked(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        try:
            ids = [make_connection_id() for _ in range(3)]
            for cid in ids:
                await bc.attach(cid, FakeWebSocket())
            assert bc.metrics.peak_attached == 3
            await bc.detach(ids[0])
            assert bc.metrics.attached == 2
            # peak stays at 3 even after a detach
            assert bc.metrics.peak_attached == 3
        finally:
            await bc.close()


# ── Fan-out semantics ─────────────────────────────────────────────


class TestFanout:
    async def test_fanout_delivers_to_all_attached(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        sockets = [FakeWebSocket(name=f"c{i}") for i in range(3)]
        ids = [make_connection_id() for _ in sockets]
        try:
            for cid, ws in zip(ids, sockets, strict=True):
                await bc.attach(cid, ws)

            result = bc.fanout(b"hello", ids)
            assert result.offered == 3
            assert result.dropped == 0
            assert result.missing == 0

            await _flush()
            for ws in sockets:
                assert ws.sent == [b"hello"]
        finally:
            await bc.close()

    async def test_fanout_missing_targets_are_counted(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        try:
            cid = make_connection_id()
            await bc.attach(cid, FakeWebSocket())
            ghost = make_connection_id()
            result = bc.fanout(b"hi", [cid, ghost])
            assert result.offered == 1
            assert result.missing == 1
        finally:
            await bc.close()

    async def test_fanout_strict_mode_raises_on_missing(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(
            default_channel_cfg,
            cfg=BroadcasterConfig(strict_fanout_targets=True),
        )
        await bc.start()
        try:
            with pytest.raises(KeyError):
                bc.fanout(b"payload", [make_connection_id()])
        finally:
            await bc.close()

    async def test_broadcast_hits_all(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        try:
            sockets = [FakeWebSocket() for _ in range(4)]
            for ws in sockets:
                await bc.attach(make_connection_id(), ws)
            result = bc.broadcast(b"all")
            assert result.offered == 4
            await _flush()
            assert all(ws.sent == [b"all"] for ws in sockets)
        finally:
            await bc.close()

    async def test_fanout_after_close_raises(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        await bc.close()
        with pytest.raises(BroadcasterClosedError):
            bc.fanout(b"x", [make_connection_id()])


# ── Slow-consumer isolation (the whole reason this exists) ──────


class TestSlowConsumerIsolation:
    async def test_slow_client_does_not_block_fast_clients(self) -> None:
        """Core guarantee of P3: a hanging WS must not delay fan-out
        delivery to other channels.
        """
        fast = FakeWebSocket(name="fast")
        slow = FakeWebSocket(name="slow", hangs=True)
        ch_cfg = ChannelConfig(
            max_queued=16,
            send_timeout_s=0.1,
            eviction_threshold=50,  # disable eviction for this test
        )
        bc = RateLimitedBroadcaster(
            ch_cfg,
            cfg=BroadcasterConfig(max_connections=4, eviction_poll_s=5.0),
        )
        await bc.start()
        try:
            fast_id = make_connection_id()
            slow_id = make_connection_id()
            await bc.attach(fast_id, fast)
            await bc.attach(slow_id, slow)

            # Fan out 5 payloads rapidly.
            for i in range(5):
                result = bc.fanout(f"m{i}".encode(), [fast_id, slow_id])
                assert result.offered == 2  # both accepted into their queues

            await _flush(delay=0.02, steps=40)

            # Fast client received everything.
            assert fast.sent == [f"m{i}".encode() for i in range(5)]
            # Slow client received nothing (hangs forever).
            assert slow.sent == []
        finally:
            await bc.close()


# ── Eviction sweeper ─────────────────────────────────────────────


class TestEvictionSweeper:
    async def test_sweeper_detaches_evictable_channels(self) -> None:
        """Slow-enough clients trip the eviction threshold and the
        background sweeper removes them without publisher involvement.

        The healthy client's queue is sized generously (``max_queued=64``)
        so that no DROP_OLDEST events accrue against it between the
        synchronous fan-out calls and the first drain tick — otherwise
        a burst of 6 payloads on a 4-slot queue would taint the
        healthy client too.
        """
        stubborn = FakeWebSocket(hangs=True)
        healthy = FakeWebSocket()
        ch_cfg = ChannelConfig(
            max_queued=64,
            send_timeout_s=0.05,
            eviction_threshold=2,
        )
        bc = RateLimitedBroadcaster(
            ch_cfg,
            cfg=BroadcasterConfig(
                max_connections=4,
                eviction_poll_s=0.05,
            ),
        )
        await bc.start()
        try:
            stubborn_id = make_connection_id()
            healthy_id = make_connection_id()
            await bc.attach(stubborn_id, stubborn)
            await bc.attach(healthy_id, healthy)

            # Pump messages — stubborn will accumulate timeouts fast.
            for i in range(6):
                bc.fanout(f"m{i}".encode(), [stubborn_id, healthy_id])

            # Wait for sweeper to run several times.
            for _ in range(60):
                if not bc.is_attached(stubborn_id):
                    break
                await asyncio.sleep(0.05)

            assert not bc.is_attached(stubborn_id)
            assert bc.is_attached(healthy_id)
            assert bc.metrics.total_evicted >= 1
        finally:
            await bc.close()


# ── Identity: UUID keys prevent id(ws) collision ─────────────────


class TestConnectionIdentity:
    async def test_distinct_connections_have_distinct_ids(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        try:
            id1 = make_connection_id()
            id2 = make_connection_id()
            assert id1 != id2
            await bc.attach(id1, FakeWebSocket())
            await bc.attach(id2, FakeWebSocket())
            assert bc.is_attached(id1)
            assert bc.is_attached(id2)
        finally:
            await bc.close()

    async def test_reattaching_recycled_ws_instance_uses_new_id(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        """Even if the same Python ``ws`` instance is reused, a fresh
        ``ConnectionId`` keeps the two attachments isolated — no
        silent cross-talk via recycled ``id()`` slots.
        """
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        try:
            ws = FakeWebSocket()
            id1 = make_connection_id()
            await bc.attach(id1, ws)
            await bc.detach(id1)

            id2 = make_connection_id()
            await bc.attach(id2, ws)

            # id1 is gone, id2 is live; they must never refer to the
            # same entry even though the underlying object is the same.
            assert not bc.is_attached(id1)
            assert bc.is_attached(id2)
            assert id1 != id2
        finally:
            await bc.close()


# ── Lifecycle ────────────────────────────────────────────────────


class TestLifecycle:
    async def test_start_is_idempotent(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        first_task = bc._sweeper_task
        await bc.start()
        assert bc._sweeper_task is first_task
        await bc.close()

    async def test_close_detaches_every_channel(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        for _ in range(3):
            await bc.attach(make_connection_id(), FakeWebSocket())
        assert bc.attached_count == 3
        await bc.close()
        assert bc.attached_count == 0

    async def test_close_is_idempotent(
        self,
        default_channel_cfg: ChannelConfig,
    ) -> None:
        bc = RateLimitedBroadcaster(default_channel_cfg)
        await bc.start()
        await bc.close()
        await bc.close()  # must not raise
