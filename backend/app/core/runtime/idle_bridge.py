"""Idle bridge policy — base class for persistent external connectors.

Stability Guardrails §2.4 — satisfies P4 (Lifecycle-correct).

Problem this solves
-------------------
The legacy ``TiingoStreamBridge.unsubscribe`` called ``shutdown()``
whenever its subscription set became empty, killing the background
WebSocket task and the Redis publisher loop. When the Dashboard tab
was closed the bridge died for every other component — a fresh tick
would re-create the entire bridge lifecycle, racing with whatever
lingering state had not been cleaned up.

The underlying mistake is a confusion between two concepts:

- **Demand** — which tickers do any currently-connected clients care
  about? This can go to zero and come back at any time.
- **Liveness** — is the bridge process/task still alive? This is
  owned exclusively by the application lifespan.

``IdleBridgePolicy`` separates the two. Demand is tracked as a set;
when it goes to zero the bridge transitions to ``IDLE`` but keeps its
task alive. When demand returns, the bridge resumes in place. Only
the application's shutdown handler, via an explicit
``_from_lifespan=True`` argument, is allowed to tear the bridge down.

What this primitive guarantees
------------------------------
- **Single shutdown path.** ``shutdown()`` without
  ``_from_lifespan=True`` raises ``IllegalStateError``. The Tiingo
  bridge (and every future persistent connector) can only be killed
  from one place: the application's shutdown hook.
- **Deterministic state machine.** The bridge lives in one of five
  states — ``STOPPED``, ``STARTING``, ``RUNNING``, ``IDLE``,
  ``STOPPING`` — with explicit transitions. Invalid transitions
  raise ``IllegalStateError`` rather than silently leaking tasks.
- **Bounded idle recovery.** After ``idle_disconnect_delay_s`` in
  ``IDLE`` state the policy fires ``_on_idle_disconnect()`` — a hook
  subclasses use to close the underlying WebSocket without killing
  the task. When demand returns, ``_on_resume()`` reopens it.
- **Serialised transitions.** A single ``asyncio.Lock`` serialises
  demand mutations so concurrent ``request_demand`` / ``release_demand``
  calls cannot race into an inconsistent state.
- **Hook-driven subclassing.** Concrete bridges override
  ``_on_start``, ``_on_resume``, ``_on_shutdown``,
  ``_on_demand_added``, ``_on_demand_removed``,
  ``_on_idle_disconnect``. The policy owns the state machine; the
  subclass owns the transport.

Non-goals (v1)
--------------
- No built-in reconnect/backoff for the transport. Subclasses that
  need reconnection implement it inside their own ``_on_start`` hook.
- No per-item authorization. ``request_demand`` takes whatever the
  caller hands it; access control lives one layer up.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


# ── Errors ─────────────────────────────────────────────────────────


class IllegalStateError(Exception):
    """Raised when a state machine transition is invalid or when
    ``shutdown()`` is called without the lifespan marker.
    """


# ── State ──────────────────────────────────────────────────────────


class BridgeState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    IDLE = "idle"
    STOPPING = "stopping"


@dataclass(frozen=True)
class IdleBridgeConfig:
    """Declarative config for an ``IdleBridgePolicy``.

    ``idle_disconnect_delay_s`` is how long the bridge stays in
    ``IDLE`` state before firing ``_on_idle_disconnect()``. Set to
    ``math.inf`` (or a very large value) to disable the grace
    timeout entirely — the bridge will then stay connected for the
    lifetime of the process regardless of demand. Default 60s.
    """

    name: str = "bridge"
    idle_disconnect_delay_s: float = 60.0

    def __post_init__(self) -> None:
        if self.idle_disconnect_delay_s <= 0:
            raise ValueError(
                "IdleBridgeConfig.idle_disconnect_delay_s must be > 0",
            )


# ── Policy base class ─────────────────────────────────────────────


class IdleBridgePolicy(ABC):
    """Base class for persistent external connectors.

    See the module docstring for the state machine diagram and the
    rationale behind the single-shutdown-path rule.
    """

    def __init__(self, cfg: IdleBridgeConfig | None = None) -> None:
        self._cfg = cfg or IdleBridgeConfig()
        self._state: BridgeState = BridgeState.STOPPED
        self._demand: set[str] = set()
        self._idle_task: asyncio.Task[None] | None = None
        self._lock: asyncio.Lock | None = None
        # Terminal flag: once shutdown completes, the bridge is dead
        # for the lifetime of the process. A fresh instance is required
        # to re-open. This distinguishes "never started" (STOPPED,
        # _terminated=False) from "finished" (STOPPED, _terminated=True).
        self._terminated = False

    @property
    def state(self) -> BridgeState:
        return self._state

    @property
    def demand(self) -> frozenset[str]:
        return frozenset(self._demand)

    @property
    def is_running(self) -> bool:
        return self._state == BridgeState.RUNNING

    @property
    def is_idle(self) -> bool:
        return self._state == BridgeState.IDLE

    def _get_lock(self) -> asyncio.Lock:
        # Lazy-init so the lock binds to the correct event loop.
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ── Public API ─────────────────────────────────────────────

    async def request_demand(self, items: Iterable[str]) -> None:
        """Add items to the demand set. Starts or resumes the bridge.

        Transitions:
            STOPPED → STARTING → RUNNING (+ _on_start)
            IDLE → RUNNING (+ _on_resume, cancels idle timer)
            RUNNING → RUNNING (no transition)
        """
        new = set(items)
        if not new:
            return
        async with self._get_lock():
            if self._terminated:
                raise IllegalStateError(
                    f"{self._cfg.name} has been shut down; create a new "
                    "bridge instance to restart",
                )
            if self._state == BridgeState.STOPPING:
                raise IllegalStateError(
                    "cannot request_demand while bridge is stopping",
                )
            added = new - self._demand
            self._demand |= new

            if self._state == BridgeState.STOPPED:
                self._state = BridgeState.STARTING
                try:
                    await self._on_start()
                except Exception:
                    self._state = BridgeState.STOPPED
                    raise
                self._state = BridgeState.RUNNING
            elif self._state == BridgeState.IDLE:
                self._cancel_idle_task()
                await self._on_resume()
                self._state = BridgeState.RUNNING

            if added and self._state == BridgeState.RUNNING:
                await self._on_demand_added(added)

    async def release_demand(self, items: Iterable[str]) -> None:
        """Remove items from the demand set. May transition to IDLE.

        Transitions:
            RUNNING → IDLE (when demand empties; spawns idle timer)
            IDLE → IDLE (no transition, items already absent)
            STOPPED → STOPPED (no transition)
        """
        removed_iter = set(items)
        if not removed_iter:
            return
        async with self._get_lock():
            removed = removed_iter & self._demand
            if not removed:
                return
            self._demand -= removed

            if self._state == BridgeState.RUNNING:
                await self._on_demand_removed(removed)
                if not self._demand:
                    self._state = BridgeState.IDLE
                    self._idle_task = asyncio.create_task(
                        self._idle_timer(),
                        name=f"{self._cfg.name}_idle_timer",
                    )

    async def shutdown(self, *, _from_lifespan: bool = False) -> None:
        """Tear down the bridge. Only callable from application lifespan.

        Raises:
            IllegalStateError: if ``_from_lifespan`` is not True.
        """
        if not _from_lifespan:
            raise IllegalStateError(
                f"{self._cfg.name}.shutdown() must be called from the "
                "application lifespan only. Pass _from_lifespan=True "
                "from your shutdown handler.",
            )
        async with self._get_lock():
            if self._state == BridgeState.STOPPED:
                return
            self._cancel_idle_task()
            self._state = BridgeState.STOPPING
            try:
                await self._on_shutdown()
            finally:
                self._demand.clear()
                self._state = BridgeState.STOPPED
                self._terminated = True

    # ── Internals ──────────────────────────────────────────────

    def _cancel_idle_task(self) -> None:
        task = self._idle_task
        self._idle_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _idle_timer(self) -> None:
        """Sleep for ``idle_disconnect_delay_s`` then fire the hook."""
        try:
            await asyncio.sleep(self._cfg.idle_disconnect_delay_s)
        except asyncio.CancelledError:
            return
        # Re-check state — demand may have returned during the sleep.
        if self._state != BridgeState.IDLE:
            return
        try:
            await self._on_idle_disconnect()
        except Exception:  # noqa: BLE001
            logger.exception(
                "idle_bridge_on_idle_disconnect_error name=%s",
                self._cfg.name,
            )

    # ── Hooks for subclasses ──────────────────────────────────

    @abstractmethod
    async def _on_start(self) -> None:
        """Called when transitioning STOPPED → RUNNING.

        Subclasses open the underlying transport here (e.g. connect
        the Tiingo WebSocket and spawn the read loop).
        """

    async def _on_resume(self) -> None:
        """Called when transitioning IDLE → RUNNING.

        Default implementation delegates to ``_on_start()``. Override
        if resume semantics differ from cold start (for example, if
        the task is still alive and only the transport needs
        reopening).
        """
        await self._on_start()

    async def _on_shutdown(self) -> None:
        """Called on final shutdown. Default no-op.

        Subclasses close transports, cancel background tasks, flush
        buffers. Failures here are logged by ``shutdown()`` but do
        not prevent the state from reaching ``STOPPED``.
        """
        return None

    async def _on_demand_added(self, items: set[str]) -> None:
        """Called when items are added to the demand set while
        ``RUNNING``. Subclasses forward subscriptions to the transport
        here. Default no-op.
        """
        return None

    async def _on_demand_removed(self, items: set[str]) -> None:
        """Called when items are removed from the demand set while
        ``RUNNING``. Subclasses unsubscribe from the transport here.
        Default no-op.
        """
        return None

    async def _on_idle_disconnect(self) -> None:
        """Called ``idle_disconnect_delay_s`` seconds after entering
        ``IDLE``. Subclasses close the underlying socket but keep the
        policy object alive, ready for ``_on_resume()``. Default no-op.
        """
        return None
