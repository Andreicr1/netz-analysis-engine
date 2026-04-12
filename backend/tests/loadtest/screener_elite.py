"""Screener ELITE fast-path load test harness.

Phase 2 Session C commit 6 — proves that the physical schema +
partial index work from Sessions 2.A and 2.B delivers the Phase 3
Screener hot path p95 < 300ms target.

Approach
--------
* Fires ``CONCURRENCY`` asyncio coroutines against the local backend
  for ``DURATION_SECONDS`` seconds, each repeatedly calling
  ``GET /screener/catalog/elite`` with a rotating set of realistic
  filter combinations.
* Measures wall-clock latency client-side for every request.
* Writes a CSV summary with p50/p95/p99/max per scenario and an
  aggregated row across all scenarios.
* Captures ``EXPLAIN (ANALYZE, BUFFERS)`` against the hot-path
  query directly through psycopg, asserts the partial index is
  named in the plan.

The script is deliberately lightweight and uses only ``httpx`` +
``asyncio`` + ``psycopg`` (already in the project's dependency
tree) so it runs in any developer environment without pulling in
Locust or k6.

Exit codes
----------
* 0 — PASS: all scenarios stayed under the p95 threshold AND the
  EXPLAIN plan referenced one of the expected partial indexes.
* 1 — FAIL: at least one scenario exceeded the threshold, or the
  partial index was not used.
* 2 — infrastructure error (backend not reachable, CSV not written).

Environment variables
---------------------
``NETZ_LOADTEST_BASE_URL``
    Base URL for the backend. Default: ``http://127.0.0.1:8765``.
``NETZ_LOADTEST_ORG_ID``
    Organisation UUID to use for the dev-actor header. Default
    falls back to the ``DEV_ORG_ID`` env var or a hard-coded
    canary org.
``NETZ_LOADTEST_P95_MS``
    Threshold in milliseconds. Default: 300. NEVER raise this
    without Andrei's approval — the threshold is a shipping gate,
    not an aspiration (see session C plan §NOT VALID ESCAPE
    HATCHES).
``NETZ_LOADTEST_DURATION``
    Seconds to run the concurrent phase. Default: 30.
``NETZ_LOADTEST_CONCURRENCY``
    Number of simultaneous async clients. Default: 20.
``NETZ_LOADTEST_DB_URL``
    Sync libpq URL for the EXPLAIN check. Default reads
    ``DATABASE_URL_SYNC`` from the project ``.env``.
``NETZ_LOADTEST_OUTPUT``
    Path for the CSV output. Default:
    ``backend/tests/loadtest/results/screener_elite_stats.csv``.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


@dataclass
class Scenario:
    """One probe scenario: a query-string payload + a friendly label."""

    label: str
    params: dict[str, Any]


@dataclass
class ScenarioStats:
    """Latency samples + derived summary for one scenario."""

    label: str
    latencies_ms: list[float] = field(default_factory=list)
    errors: int = 0

    def summary(self) -> dict[str, Any]:
        if not self.latencies_ms:
            return {
                "label": self.label,
                "count": 0,
                "errors": self.errors,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "max_ms": 0.0,
                "mean_ms": 0.0,
            }
        sorted_latencies = sorted(self.latencies_ms)
        return {
            "label": self.label,
            "count": len(sorted_latencies),
            "errors": self.errors,
            "p50_ms": round(_percentile(sorted_latencies, 0.50), 3),
            "p95_ms": round(_percentile(sorted_latencies, 0.95), 3),
            "p99_ms": round(_percentile(sorted_latencies, 0.99), 3),
            "max_ms": round(max(sorted_latencies), 3),
            "mean_ms": round(statistics.fmean(sorted_latencies), 3),
        }


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile — matches numpy ``default``."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = q * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


SCENARIOS: list[Scenario] = [
    Scenario(
        label="elite_all",
        params={"limit": 50},
    ),
    Scenario(
        label="elite_equity_fixed_income",
        params={"asset_class": "equity,fixed_income", "limit": 50},
    ),
    Scenario(
        label="elite_equity_only",
        params={"asset_class": "equity", "limit": 100},
    ),
    Scenario(
        label="elite_multi_class",
        params={
            "asset_class": "equity,fixed_income,alternatives",
            "limit": 50,
        },
    ),
]


async def _probe_loop(
    client: httpx.AsyncClient,
    scenarios: list[Scenario],
    stats_by_label: dict[str, ScenarioStats],
    deadline_ts: float,
) -> None:
    """Single async worker — rotates through scenarios until deadline."""
    idx = 0
    while time.perf_counter() < deadline_ts:
        scenario = scenarios[idx % len(scenarios)]
        idx += 1
        started = time.perf_counter()
        try:
            resp = await client.get(
                "/api/v1/screener/catalog/elite",
                params=scenario.params,
                timeout=5.0,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if resp.status_code == 200:
                stats_by_label[scenario.label].latencies_ms.append(elapsed_ms)
            else:
                stats_by_label[scenario.label].errors += 1
        except Exception:
            stats_by_label[scenario.label].errors += 1


async def _run_load_phase(
    base_url: str,
    dev_actor_header: str,
    concurrency: int,
    duration_s: int,
) -> dict[str, ScenarioStats]:
    """Fan out ``concurrency`` workers for ``duration_s`` seconds."""
    stats_by_label: dict[str, ScenarioStats] = {
        s.label: ScenarioStats(label=s.label) for s in SCENARIOS
    }

    headers = {"X-DEV-ACTOR": dev_actor_header}
    async with httpx.AsyncClient(
        base_url=base_url, headers=headers, timeout=5.0,
    ) as client:
        deadline_ts = time.perf_counter() + duration_s
        workers = [
            _probe_loop(client, SCENARIOS, stats_by_label, deadline_ts)
            for _ in range(concurrency)
        ]
        await asyncio.gather(*workers)
    return stats_by_label


def _write_csv(stats_by_label: dict[str, ScenarioStats], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "label",
                "count",
                "errors",
                "p50_ms",
                "p95_ms",
                "p99_ms",
                "max_ms",
                "mean_ms",
            ],
        )
        writer.writeheader()
        for stats in stats_by_label.values():
            writer.writerow(stats.summary())

        # Aggregated row across all scenarios — p95 calculated on the
        # concatenated sample set so it's a true worst-case view, not
        # a mean of p95s.
        all_latencies: list[float] = []
        total_errors = 0
        for stats in stats_by_label.values():
            all_latencies.extend(stats.latencies_ms)
            total_errors += stats.errors
        aggregated = ScenarioStats(
            label="aggregated",
            latencies_ms=all_latencies,
            errors=total_errors,
        )
        writer.writerow(aggregated.summary())


_EXPLAIN_SQL = """
EXPLAIN (ANALYZE, BUFFERS)
WITH elite_set AS MATERIALIZED (
    SELECT
        instrument_id,
        sharpe_1y,
        manager_score,
        cvar_95_12m,
        max_drawdown_1y,
        elite_rank_within_strategy
    FROM mv_fund_risk_latest
    WHERE elite_flag = true
)
SELECT
    es.instrument_id,
    iu.name,
    iu.ticker,
    iu.asset_class,
    es.sharpe_1y,
    es.manager_score,
    es.cvar_95_12m,
    es.max_drawdown_1y,
    es.elite_rank_within_strategy
FROM elite_set es
JOIN instruments_universe iu
  ON iu.instrument_id = es.instrument_id
WHERE iu.asset_class = ANY(ARRAY['equity','fixed_income'])
ORDER BY es.sharpe_1y DESC NULLS LAST
LIMIT 50
"""


_EXPECTED_INDEX_NAMES = (
    "idx_mv_fund_risk_latest_elite",
    "idx_fund_risk_metrics_elite_partial",
)


def _load_sync_db_url() -> str:
    """Resolve the sync libpq URL for the EXPLAIN probe."""
    env_url = os.environ.get("NETZ_LOADTEST_DB_URL")
    if env_url:
        return env_url
    # Fall back to DATABASE_URL_SYNC read directly from .env so the
    # script works when invoked by `make loadtest` without loading
    # the project's full settings stack.
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if raw.startswith("DATABASE_URL_SYNC="):
                return raw.split("=", 1)[1].strip()
    raise RuntimeError(
        "Cannot resolve sync DB URL. Set NETZ_LOADTEST_DB_URL or "
        "DATABASE_URL_SYNC in .env.",
    )


def _normalize_pg_url(url: str) -> str:
    """Strip the SQLAlchemy ``+psycopg`` / ``+asyncpg`` driver suffix."""
    return url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://",
    )


def verify_index_usage(db_url: str) -> tuple[bool, str]:
    """Run EXPLAIN (ANALYZE, BUFFERS) and assert the partial index is used.

    Returns ``(ok, plan_text)``. ``ok`` is True when the plan text
    contains at least one of ``_EXPECTED_INDEX_NAMES``.
    """
    try:
        import psycopg
    except ImportError:  # pragma: no cover
        return False, "psycopg not available — cannot run EXPLAIN probe"

    normalized = _normalize_pg_url(db_url)
    with psycopg.connect(normalized) as conn:
        with conn.cursor() as cur:
            cur.execute(_EXPLAIN_SQL)
            plan_lines = [row[0] for row in cur.fetchall()]
    plan_text = "\n".join(plan_lines)
    ok = any(name in plan_text for name in _EXPECTED_INDEX_NAMES)
    return ok, plan_text


def _resolve_dev_actor_header() -> str:
    """Build the JSON header value consumed by ``_parse_dev_actor``."""
    org_id = os.environ.get("NETZ_LOADTEST_ORG_ID") or os.environ.get("DEV_ORG_ID")
    if not org_id:
        # Dev default — same UUID used in the project .env, kept
        # here as a last-resort fallback so `make loadtest` works
        # even when .env is not loaded into the current shell.
        env_path = Path(__file__).resolve().parents[3] / ".env"
        if env_path.exists():
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                if raw.startswith("DEV_ORG_ID="):
                    org_id = raw.split("=", 1)[1].strip()
                    break
    if not org_id:
        raise RuntimeError(
            "Cannot resolve DEV_ORG_ID for the load test dev-actor header.",
        )
    return json.dumps(
        {"actor_id": "loadtest@netz.internal", "roles": ["ADMIN"], "org_id": org_id},
    )


def main() -> int:
    base_url = os.environ.get("NETZ_LOADTEST_BASE_URL", "http://127.0.0.1:8765")
    threshold_ms = float(os.environ.get("NETZ_LOADTEST_P95_MS", "300"))
    duration_s = int(os.environ.get("NETZ_LOADTEST_DURATION", "30"))
    concurrency = int(os.environ.get("NETZ_LOADTEST_CONCURRENCY", "20"))
    output_path = Path(
        os.environ.get(
            "NETZ_LOADTEST_OUTPUT",
            str(
                Path(__file__).resolve().parent
                / "results"
                / "screener_elite_stats.csv",
            ),
        ),
    )

    try:
        dev_actor_header = _resolve_dev_actor_header()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Sanity probe — make sure the backend is reachable before the
    # concurrent phase. A single GET surfaces connection errors as
    # exit 2 (infrastructure) instead of polluting the CSV with
    # client-side failures.
    try:
        probe = httpx.get(
            f"{base_url}/api/v1/screener/catalog/elite",
            params={"limit": 1},
            headers={"X-DEV-ACTOR": dev_actor_header},
            timeout=5.0,
        )
        probe.raise_for_status()
    except Exception as exc:
        print(
            f"ERROR: backend not reachable at {base_url} — {exc}",
            file=sys.stderr,
        )
        return 2

    print(
        f"Starting load test — {concurrency} workers x {duration_s}s, "
        f"p95 gate {threshold_ms}ms",
    )
    stats_by_label = asyncio.run(
        _run_load_phase(base_url, dev_actor_header, concurrency, duration_s),
    )
    _write_csv(stats_by_label, output_path)

    # Per-scenario and aggregated reporting
    print("\n=== Scenario summaries ===")
    max_p95 = 0.0
    any_errors = False
    for stats in stats_by_label.values():
        summary = stats.summary()
        print(
            f"{summary['label']:<32} "
            f"n={summary['count']:>6} "
            f"err={summary['errors']:>3} "
            f"p50={summary['p50_ms']:>8.2f} "
            f"p95={summary['p95_ms']:>8.2f} "
            f"p99={summary['p99_ms']:>8.2f} "
            f"max={summary['max_ms']:>8.2f}",
        )
        max_p95 = max(max_p95, summary["p95_ms"])
        any_errors = any_errors or summary["errors"] > 0

    all_latencies: list[float] = []
    for stats in stats_by_label.values():
        all_latencies.extend(stats.latencies_ms)
    aggregated = ScenarioStats(label="aggregated", latencies_ms=all_latencies)
    agg_summary = aggregated.summary()
    print(
        f"\naggregated{' ' * 22}"
        f"n={agg_summary['count']:>6} "
        f"p50={agg_summary['p50_ms']:>8.2f} "
        f"p95={agg_summary['p95_ms']:>8.2f} "
        f"p99={agg_summary['p99_ms']:>8.2f} "
        f"max={agg_summary['max_ms']:>8.2f}",
    )

    # EXPLAIN probe — prove the partial index is actually used.
    try:
        db_url = _load_sync_db_url()
    except RuntimeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2
    ok, plan_text = verify_index_usage(db_url)
    print("\n=== EXPLAIN plan (hot-path query) ===")
    print(plan_text)
    if not ok:
        print(
            "\nFAIL: plan did not reference any of "
            f"{_EXPECTED_INDEX_NAMES}",
            file=sys.stderr,
        )
        return 1
    print(
        f"\nPASS: plan uses one of {_EXPECTED_INDEX_NAMES}",
    )

    # Final p95 gate
    print(f"\nThreshold: {threshold_ms}ms")
    print(f"Max p95 across scenarios: {max_p95:.2f}ms")
    print(f"Aggregated p95: {agg_summary['p95_ms']:.2f}ms")
    if max_p95 > threshold_ms or agg_summary["p95_ms"] > threshold_ms:
        print(
            f"\nFAIL: p95 exceeded {threshold_ms}ms — see CSV at {output_path}",
            file=sys.stderr,
        )
        return 1
    if any_errors:
        print(
            "\nFAIL: scenarios reported client-side errors — see CSV",
            file=sys.stderr,
        )
        return 1

    print("\nPASS: all p95 gates green, partial index usage verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
