"""Tests for ``IdleBridgePolicy`` (Stability Guardrails §2.4)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.runtime.idle_bridge import (
    BridgeState,
    IdleBridgeConfig,
    IdleBridgePolicy,
    IllegalStateError,
)

# ── Concrete bridge that records every hook invocation ───────────


class RecordingBridge(IdleBridgePolicy):
    """Minimal concrete bridge used across the test suite."""

    def __init__(
        self,
        cfg: IdleBridgeConfig | None = None,
        *,
        fail_on_start: bool = False,
    ) -> None:
        super().__init__(cfg)
        self.events: list[object] = []
        self.fail_on_start = fail_on_start

    async def _on_start(self) -> None:
        self.events.append("start")
        if self.fail_on_start:
            raise RuntimeError("start failed")

    async def _on_resume(self) -> None:
        self.events.append("resume")

    async def _on_shutdown(self) -> None:
        self.events.append("shutdown")

    async def _on_demand_added(self, items: set[str]) -> None:
        self.events.append(("added", sorted(items)))

    async def _on_demand_removed(self, items: set[str]) -> None:
        self.events.append(("removed", sorted(items)))

    async def _on_idle_disconnect(self) -> None:
        self.events.append("idle_disconnect")


# ── Config validation ────────────────────────────────────────────


class TestIdleBridgeConfigValidation:
    def test_idle_disconnect_delay_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="idle_disconnect_delay_s"):
            IdleBridgeConfig(idle_disconnect_delay_s=0)


# ── Cold start ───────────────────────────────────────────────────


class TestColdStart:
    async def test_request_demand_from_stopped_starts_bridge(self) -> None:
        bridge = RecordingBridge()
        assert bridge.state == BridgeState.STOPPED
        await bridge.request_demand({"SPY", "QQQ"})
        assert bridge.state == BridgeState.RUNNING
        assert bridge.demand == frozenset({"SPY", "QQQ"})
        # Start must fire before demand_added.
        assert bridge.events[0] == "start"
        assert ("added", ["QQQ", "SPY"]) in bridge.events

    async def test_empty_request_is_a_noop(self) -> None:
        bridge = RecordingBridge()
        await bridge.request_demand(set())
        assert bridge.state == BridgeState.STOPPED
        assert bridge.events == []

    async def test_start_failure_reverts_to_stopped(self) -> None:
        bridge = RecordingBridge(fail_on_start=True)
        with pytest.raises(RuntimeError, match="start failed"):
            await bridge.request_demand({"SPY"})
        assert bridge.state == BridgeState.STOPPED
        assert bridge.demand == frozenset({"SPY"}) or bridge.demand == frozenset()


# ── Release & idle ──────────────────────────────────────────────


class TestReleaseAndIdle:
    async def test_release_all_transitions_to_idle(self) -> None:
        bridge = RecordingBridge()
        await bridge.request_demand({"SPY"})
        await bridge.release_demand({"SPY"})
        assert bridge.state == BridgeState.IDLE
        assert bridge.demand == frozenset()
        assert ("removed", ["SPY"]) in bridge.events

    async def test_release_partial_stays_running(self) -> None:
        bridge = RecordingBridge()
        await bridge.request_demand({"SPY", "QQQ", "IWM"})
        await bridge.release_demand({"SPY"})
        assert bridge.state == BridgeState.RUNNING
        assert bridge.demand == frozenset({"QQQ", "IWM"})

    async def test_release_of_nothing_is_a_noop(self) -> None:
        bridge = RecordingBridge()
        await bridge.request_demand({"SPY"})
        prior_events = list(bridge.events)
        await bridge.release_demand({"NOPE"})
        assert bridge.events == prior_events

    async def test_release_while_stopped_is_a_noop(self) -> None:
        bridge = RecordingBridge()
        await bridge.release_demand({"SPY"})
        assert bridge.state == BridgeState.STOPPED


# ── Resume from idle ────────────────────────────────────────────


class TestResumeFromIdle:
    async def test_request_demand_from_idle_resumes(self) -> None:
        cfg = IdleBridgeConfig(idle_disconnect_delay_s=60.0)
        bridge = RecordingBridge(cfg)
        await bridge.request_demand({"SPY"})
        await bridge.release_demand({"SPY"})
        assert bridge.state == BridgeState.IDLE

        await bridge.request_demand({"QQQ"})
        assert bridge.state == BridgeState.RUNNING
        assert bridge.demand == frozenset({"QQQ"})
        assert "resume" in bridge.events
        assert ("added", ["QQQ"]) in bridge.events

    async def test_resume_cancels_idle_timer(self) -> None:
        cfg = IdleBridgeConfig(idle_disconnect_delay_s=0.2)
        bridge = RecordingBridge(cfg)
        await bridge.request_demand({"SPY"})
        await bridge.release_demand({"SPY"})
        # Resume before the idle timer fires.
        await asyncio.sleep(0.05)
        await bridge.request_demand({"QQQ"})
        assert bridge.state == BridgeState.RUNNING
        # Give time for the cancelled timer to NOT fire.
        await asyncio.sleep(0.3)
        assert "idle_disconnect" not in bridge.events


# ── Idle disconnect ─────────────────────────────────────────────


class TestIdleDisconnect:
    async def test_idle_timer_fires_hook_after_delay(self) -> None:
        cfg = IdleBridgeConfig(idle_disconnect_delay_s=0.05)
        bridge = RecordingBridge(cfg)
        await bridge.request_demand({"SPY"})
        await bridge.release_demand({"SPY"})
        assert bridge.state == BridgeState.IDLE

        # Wait for timer to fire.
        for _ in range(40):
            if "idle_disconnect" in bridge.events:
                break
            await asyncio.sleep(0.02)
        assert "idle_disconnect" in bridge.events

    async def test_idle_hook_skipped_if_demand_returns(self) -> None:
        cfg = IdleBridgeConfig(idle_disconnect_delay_s=0.1)
        bridge = RecordingBridge(cfg)
        await bridge.request_demand({"SPY"})
        await bridge.release_demand({"SPY"})
        await asyncio.sleep(0.02)
        await bridge.request_demand({"QQQ"})
        await asyncio.sleep(0.2)
        assert "idle_disconnect" not in bridge.events


# ── Shutdown: only from lifespan ────────────────────────────────


class TestShutdownOnlyFromLifespan:
    async def test_shutdown_without_lifespan_raises(self) -> None:
        bridge = RecordingBridge()
        await bridge.request_demand({"SPY"})
        with pytest.raises(IllegalStateError, match="lifespan"):
            await bridge.shutdown()
        # State is unchanged.
        assert bridge.state == BridgeState.RUNNING

    async def test_shutdown_from_lifespan_tears_down(self) -> None:
        bridge = RecordingBridge()
        await bridge.request_demand({"SPY"})
        await bridge.shutdown(_from_lifespan=True)
        assert bridge.state == BridgeState.STOPPED
        assert bridge.demand == frozenset()
        assert "shutdown" in bridge.events

    async def test_shutdown_from_idle(self) -> None:
        bridge = RecordingBridge()
        await bridge.request_demand({"SPY"})
        await bridge.release_demand({"SPY"})
        assert bridge.state == BridgeState.IDLE
        await bridge.shutdown(_from_lifespan=True)
        assert bridge.state == BridgeState.STOPPED

    async def test_shutdown_when_stopped_is_noop(self) -> None:
        bridge = RecordingBridge()
        await bridge.shutdown(_from_lifespan=True)
        assert bridge.state == BridgeState.STOPPED
        assert "shutdown" not in bridge.events

    async def test_request_demand_after_shutdown_is_terminal(self) -> None:
        """Once shutdown completes the bridge is dead for the life of
        the process. Any subsequent request_demand must raise rather
        than silently resurrect — callers create a new instance.
        """
        bridge = RecordingBridge()
        await bridge.request_demand({"SPY"})
        await bridge.shutdown(_from_lifespan=True)
        with pytest.raises(IllegalStateError, match="shut down"):
            await bridge.request_demand({"QQQ"})
        assert bridge.state == BridgeState.STOPPED

    async def test_request_demand_while_stopping_raises(self) -> None:
        """If a task calls request_demand while shutdown is still
        executing its ``_on_shutdown`` hook, it must observe STOPPING
        and raise rather than interleave with the teardown.
        """

        start = asyncio.Event()

        class SlowShutdownBridge(RecordingBridge):
            async def _on_shutdown(self) -> None:
                self.events.append("shutdown")
                start.set()
                await asyncio.sleep(0.15)

        bridge = SlowShutdownBridge()
        await bridge.request_demand({"SPY"})

        shutdown_task = asyncio.create_task(
            bridge.shutdown(_from_lifespan=True),
        )
        await start.wait()
        # Bridge is in STOPPING with the lock held. Release lock
        # only happens after _on_shutdown finishes and sets STOPPED
        # + _terminated=True — by which point request_demand observes
        # the terminal flag and raises the "shut down" message.
        with pytest.raises(IllegalStateError):
            await bridge.request_demand({"QQQ"})
        await shutdown_task
        assert bridge.state == BridgeState.STOPPED


# ── Concurrency ─────────────────────────────────────────────────


class TestConcurrency:
    async def test_lock_serialises_concurrent_demand_changes(self) -> None:
        bridge = RecordingBridge()
        # Kick off many concurrent requests at once.
        await asyncio.gather(
            bridge.request_demand({"A", "B"}),
            bridge.request_demand({"C"}),
            bridge.request_demand({"D", "E"}),
        )
        assert bridge.state == BridgeState.RUNNING
        assert bridge.demand == frozenset({"A", "B", "C", "D", "E"})
