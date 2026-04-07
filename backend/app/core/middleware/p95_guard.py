"""p95 guard middleware — passive latency budget observability.

Stability Guardrails §2.8 (operationalises P1 + P3).

Problem this solves
-------------------
The "Job-or-Stream" rule from the design spec says any route whose
p95 exceeds 500ms should be refactored to enqueue a background job
and return a ``202 Accepted``. Enforcing that rule requires
measuring p95 per route in the first place. We don't want a full
observability stack (APM, tracing, Prometheus) for this sprint; we
want a minimum viable signal so that during development and early
production we can see which routes are the next candidates for
migration.

``P95GuardMiddleware`` is the minimum viable signal: a sliding
window per route, a p95 estimator, and a structured ``WARNING`` log
whenever the p95 crosses the configured budget. It never blocks,
never short-circuits, never mutates responses — it only observes
and reports.

What this middleware guarantees
-------------------------------
- **No request is blocked.** The middleware runs after
  ``call_next(request)``, measures elapsed time, and returns the
  response unchanged. Failures in the measurement path are caught
  and logged at DEBUG — the request still succeeds.
- **Bounded memory.** Each route key holds at most ``window``
  samples in a ``deque(maxlen=window)``. The dict of route keys is
  bounded by the number of distinct routes in the app.
- **Hysteresis.** Once a route's p95 exceeds the budget, the
  warning log fires **once** until a later sample drops the p95
  back under the budget. This avoids log spam under sustained
  slowness.
- **Deterministic quantile.** Uses nearest-rank method on a sorted
  copy of the window; not a reservoir approximation. At 100
  samples the p95 is sample number 95 (0-indexed).

Non-goals (v1)
--------------
- No ``@async_job`` marker for per-route exemptions. Every route
  is measured. Exemption support lands in a later iteration once
  we have a baseline.
- No Prometheus export. Logs are the only sink.
- No response header with the elapsed time. Keep the response
  bytes exactly what the handler produced.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# ── Per-route window ──────────────────────────────────────────────


@dataclass
class RouteWindow:
    samples: deque[float]
    over_budget: bool = False  # hysteresis flag


# ── Middleware ────────────────────────────────────────────────────


class P95GuardMiddleware(BaseHTTPMiddleware):
    """Passive latency observability middleware.

    Register once in ``app/main.py``::

        app.add_middleware(P95GuardMiddleware, window=100, budget_ms=500)
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[Response]],
        *,
        window: int = 100,
        budget_ms: int = 500,
        min_samples_for_p95: int = 20,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        if window <= 0:
            raise ValueError("P95GuardMiddleware.window must be > 0")
        if budget_ms <= 0:
            raise ValueError("P95GuardMiddleware.budget_ms must be > 0")
        if min_samples_for_p95 <= 0:
            raise ValueError(
                "P95GuardMiddleware.min_samples_for_p95 must be > 0",
            )
        self._window = window
        self._budget_ms = budget_ms
        self._min_samples = min_samples_for_p95
        self._routes: dict[str, RouteWindow] = defaultdict(
            lambda: RouteWindow(samples=deque(maxlen=self._window)),
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000.0

        try:
            self._record(request, elapsed_ms)
        except Exception:  # noqa: BLE001 — observation must never break requests
            logger.debug("p95_guard_record_failed", exc_info=True)

        return response

    def _record(self, request: Request, elapsed_ms: float) -> None:
        route_key = self._route_key(request)
        window = self._routes[route_key]
        window.samples.append(elapsed_ms)

        if len(window.samples) < self._min_samples:
            return

        p95 = self._compute_p95(window.samples)

        if p95 > self._budget_ms and not window.over_budget:
            window.over_budget = True
            logger.warning(
                "p95_budget_exceeded route=%s p95_ms=%.1f budget_ms=%d "
                "samples=%d guidance=%s",
                route_key,
                p95,
                self._budget_ms,
                len(window.samples),
                (
                    "consider migrating to the Job-or-Stream pattern — see "
                    "docs/reference/stability-guardrails.md §2.8"
                ),
            )
        elif p95 <= self._budget_ms and window.over_budget:
            window.over_budget = False
            logger.info(
                "p95_budget_recovered route=%s p95_ms=%.1f budget_ms=%d",
                route_key,
                p95,
                self._budget_ms,
            )

    def _route_key(self, request: Request) -> str:
        """Derive a stable per-route key.

        Uses the templated path from Starlette's route resolver when
        available (e.g. ``/screener/fund/{id}``) so unique instance
        paths are collapsed to a single key. Falls back to the raw
        URL path when no route is attached (404s, startup probes).
        """
        route = request.scope.get("route")
        if route is not None:
            template = getattr(route, "path", None)
            if isinstance(template, str) and template:
                return f"{request.method} {template}"
        return f"{request.method} {request.url.path}"

    @staticmethod
    def _compute_p95(samples: deque[float]) -> float:
        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        # Nearest-rank: ceil(0.95 * n) − 1
        idx = max(0, min(n - 1, int(round(0.95 * n)) - 1))
        return sorted_samples[idx]

    # ── Test / introspection hooks ─────────────────────────────

    def snapshot(self) -> dict[str, float]:
        """Return the current p95 per route key. Intended for tests
        and ad-hoc debugging, not a public API.
        """
        out: dict[str, float] = {}
        for key, window in self._routes.items():
            if len(window.samples) >= self._min_samples:
                out[key] = self._compute_p95(window.samples)
        return out
