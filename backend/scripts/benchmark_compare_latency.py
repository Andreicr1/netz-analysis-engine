"""B2-style latency comparison — works against either contract.

Sends N sequential POSTs to /screener/import/{ticker} and reports
percentiles. Designed to run against both the HEAD (202 enqueue)
and the pre-Phase-4 (201 sync) backend on the same port.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
import uuid

import asyncpg
import httpx

API_BASE = "http://127.0.0.1:8000/api/v1"
DB_DSN = "postgresql://netz:password@localhost:5434/netz_engine"
ORG_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "bench-org-001"))

DEV_HEADERS = {
    "Content-Type": "application/json",
    "X-DEV-ACTOR": json.dumps({
        "actor_id": "bench-actor-001",
        "name": "Bench Actor",
        "email": "bench@netz.local",
        "roles": ["INVESTMENT_TEAM", "ADMIN"],
        "org_id": ORG_ID,
        "org_slug": "bench-org",
        "fund_ids": [],
    }),
}


async def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    db = await asyncpg.connect(DB_DSN)
    await db.execute(
        "DELETE FROM instruments_org WHERE organization_id = $1::uuid",
        ORG_ID,
    )

    tickers = [
        r["ticker"]
        for r in await db.fetch(
            """
            SELECT iu.ticker
            FROM instruments_universe iu
            WHERE iu.ticker IS NOT NULL
              AND length(iu.ticker) BETWEEN 1 AND 5
              AND iu.ticker ~ '^[A-Z]+$'
            ORDER BY iu.ticker
            LIMIT $1
            """,
            n,
        )
    ]
    await db.close()

    print(f"==== {label} — {len(tickers)} sequential imports ====")

    latencies: list[float] = []
    statuses: list[int] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for ticker in tickers:
            t0 = time.monotonic()
            r = await client.post(
                f"{API_BASE}/screener/import/{ticker}",
                headers=DEV_HEADERS,
                json={"block_id": None, "strategy": None},
            )
            latencies.append((time.monotonic() - t0) * 1000)
            statuses.append(r.status_code)

    p50 = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
    p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)

    summary = {
        "label": label,
        "sample_size": len(tickers),
        "status_codes_distribution": {
            str(s): statuses.count(s) for s in sorted(set(statuses))
        },
        "latency_mean_ms": round(statistics.fmean(latencies), 2),
        "latency_p50_ms": round(p50, 2),
        "latency_p95_ms": round(p95, 2),
        "latency_p99_ms": round(p99, 2),
        "latency_max_ms": round(max(latencies), 2),
        "latency_min_ms": round(min(latencies), 2),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
