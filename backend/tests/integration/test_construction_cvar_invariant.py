"""PR-A12.4 — construction-run CVaR invariant (live-DB integration).

Closes the A12.2 class of DB-only tests blind spot. The A12.2 migration
test validated only that ``portfolio_calibration.cvar_limit`` was updated
in the column — not that the optimizer actually consumed that value. A
wiring bug (A12.3 round 1) silently ignored the per-portfolio column and
applied stale profile-wide defaults; a winner-selection bug (A12.3 round
2 → A12.4) promoted SCS-fallback constraint-violating solutions to
cascade_summary=phase_1_succeeded.

This harness exercises the full runtime path for all 3 canonical
portfolios against a running uvicorn + local Postgres, asserting the
central invariant:

    |cvar_95_delivered| <= resolved_cvar_limit + tol
      OR
    cascade_summary in {phase_3_min_cvar_above_limit, upstream_heuristic,
                        constraint_polytope_empty}

Any future PR touching ``optimizer_service``, ``model_portfolios``,
``construction_run_executor``, or ``portfolio_calibration`` MUST keep
this test green. It is gated behind ``@pytest.mark.integration`` so the
default ``make test`` lane is unaffected; ``pytest -m integration`` or
CI-triggered live-db lane runs it.

Preconditions (test is skipped when absent):
- Backend reachable at ``http://localhost:8000/health``
- Postgres reachable at the canonical dev DSN
- The 3 canonical portfolio UUIDs seeded (see ``scripts/seed_canonical_portfolios.py``)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
import psycopg
import pytest

pytestmark = pytest.mark.integration

_CANONICAL_ORG = "403d8392-ebfa-5890-b740-45da49c556eb"
_BACKEND_URL = "http://localhost:8000"
_DB_DSN = "postgresql://netz:netz@localhost:5434/netz_engine"
_WITHIN_TOLERANCE = 1e-3  # annual CVaR tolerance — matches optimizer gate

_PORTFOLIOS = [
    ("Conservative Preservation", "3945cee6-f85d-4903-a2dd-cf6a51e1c6a5"),
    ("Balanced Income", "e5892474-7438-4ac5-85da-217abcf99932"),
    ("Dynamic Growth", "3163d72b-3f8c-427e-9cd2-bead6377b59c"),
]

_DEV_ACTOR = json.dumps({
    "actor_id": "cvar-invariant-test",
    "name": "CVaR Invariant",
    "email": "ci@netz.capital",
    "roles": ["ADMIN", "INVESTMENT_TEAM"],
    "org_id": _CANONICAL_ORG,
    "org_slug": "ci",
})
_HEADERS = {"X-DEV-ACTOR": _DEV_ACTOR, "Content-Type": "application/json"}

_ALLOWED_BELOW_FLOOR_SUMMARIES = {
    "phase_3_min_cvar_above_limit",
    "upstream_heuristic",
    "constraint_polytope_empty",
}


def _backend_reachable() -> bool:
    try:
        with httpx.Client(timeout=2.0) as c:
            return c.get(f"{_BACKEND_URL}/health").status_code == 200
    except Exception:
        return False


def _db_reachable() -> bool:
    try:
        with psycopg.connect(_DB_DSN, connect_timeout=2):
            return True
    except Exception:
        return False


def _portfolios_seeded() -> bool:
    try:
        with psycopg.connect(_DB_DSN, connect_timeout=2) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM model_portfolios WHERE id = ANY(%s)",
                ([pid for _, pid in _PORTFOLIOS],),
            )
            return (cur.fetchone() or [0])[0] == len(_PORTFOLIOS)
    except Exception:
        return False


@pytest.mark.skipif(
    not (_backend_reachable() and _db_reachable() and _portfolios_seeded()),
    reason="Requires local uvicorn + Postgres + seeded canonical portfolios",
)
def test_construction_delivered_cvar_within_limit_or_signaled() -> None:
    """For each of the 3 canonical portfolios, trigger /build and assert that
    the persisted cascade either honours the operator's CVaR limit
    (succeeded) or surfaces the below-floor state (degraded with a
    recognised summary)."""
    trigger_at = datetime.now(timezone.utc)
    with httpx.Client(timeout=20.0) as c:
        for name, pid in _PORTFOLIOS:
            resp = c.post(
                f"{_BACKEND_URL}/api/v1/portfolios/{pid}/build",
                headers=_HEADERS,
                json={},
            )
            assert resp.status_code in (200, 202), (
                f"{name}: unexpected build response {resp.status_code}"
            )

    # Poll until all three runs reach a terminal state (≤ 4 min).
    deadline = time.time() + 240
    terminal: list[tuple[str, str]] = []
    while time.time() < deadline:
        with psycopg.connect(_DB_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT mp.id::text, pcr.status
                FROM portfolio_construction_runs pcr
                JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
                WHERE pcr.started_at >= %s
                  AND mp.id = ANY(%s)
                ORDER BY pcr.started_at DESC
                """,
                (trigger_at, [pid for _, pid in _PORTFOLIOS]),
            )
            rows = cur.fetchall()
        terminal = [
            r for r in rows
            if r[1] in ("succeeded", "failed", "degraded", "cancelled")
        ]
        if len(terminal) >= len(_PORTFOLIOS):
            break
        time.sleep(5)

    assert len(terminal) >= len(_PORTFOLIOS), (
        f"only {len(terminal)}/{len(_PORTFOLIOS)} runs reached a terminal "
        f"state within the poll window"
    )

    with psycopg.connect(_DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mp.display_name,
                   pcr.status,
                   pcr.cascade_telemetry->>'cascade_summary' AS summary,
                   (pcr.calibration_snapshot->>'cvar_limit')::float AS limit_operator,
                   (pcr.ex_ante_metrics->>'cvar_95')::float AS delivered_cvar95
            FROM portfolio_construction_runs pcr
            JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
            WHERE pcr.started_at >= %s
              AND mp.id = ANY(%s)
            ORDER BY pcr.started_at DESC
            """,
            (trigger_at, [pid for _, pid in _PORTFOLIOS]),
        )
        rows = cur.fetchall()

    # One row per portfolio — each MUST either deliver within limit
    # or surface the below-floor signal.
    failures: list[str] = []
    for name, status, summary, limit, delivered in rows:
        delivered_abs = abs(delivered) if delivered is not None else None
        if status == "succeeded" and summary == "phase_1_succeeded":
            if delivered_abs is None or limit is None:
                failures.append(
                    f"{name}: succeeded but missing cvar_95 / calibration limit",
                )
            elif delivered_abs > limit + _WITHIN_TOLERANCE:
                failures.append(
                    f"{name}: PR-A12.4 invariant violated — "
                    f"succeeded/phase_1 but delivered {delivered_abs:.4f} > "
                    f"limit {limit:.4f} (tol {_WITHIN_TOLERANCE})",
                )
        elif status == "degraded":
            if summary not in _ALLOWED_BELOW_FLOOR_SUMMARIES:
                failures.append(
                    f"{name}: degraded with unrecognised summary {summary}; "
                    f"expected one of {_ALLOWED_BELOW_FLOOR_SUMMARIES}",
                )
        elif status == "failed":
            failures.append(f"{name}: unexpected status=failed, summary={summary}")

    assert not failures, "invariant violations:\n  " + "\n  ".join(failures)
