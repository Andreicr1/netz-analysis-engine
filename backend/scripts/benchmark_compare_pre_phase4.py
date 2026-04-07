"""Pre vs Post Phase-4 comparison benchmark — contract-agnostic.

This script is the **comparison harness** for the Stability Guardrails
impact report. Unlike `benchmark_stability_phase4.py` (which assumes
the 202 + job_id contract), this script measures the OUTCOME via the
DB regardless of response shape:

  - 5 parallel POSTs to /screener/import/{ticker}
  - Same Idempotency-Key header on all 5
  - Same TICKER (so the unique constraint on (org_id, instrument_id)
    is the only thing that could prevent duplicates in the bad path)
  - Wait briefly for any background work to settle
  - Count (a) status code distribution, (b) wall-time, (c)
    InstrumentOrg rows for the bench org × ticker

Run against HEAD: backend on :8000, this script run.
Run against pre-Phase-4: kill HEAD uvicorn, start pre-Phase-4
uvicorn from the worktree on :8000, run the same script. The
DB is shared so the rows accumulate — clean up between runs.

Output is a JSON line that can be diffed against the previous run.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from typing import Any

import asyncpg
import httpx

API_BASE = "http://127.0.0.1:8000/api/v1"
DB_DSN = "postgresql://netz:password@localhost:5434/netz_engine"
ORG_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "bench-org-001"))

DEV_ACTOR = {
    "actor_id": "bench-actor-001",
    "name": "Bench Actor",
    "email": "bench@netz.local",
    "roles": ["INVESTMENT_TEAM", "ADMIN"],
    "org_id": ORG_ID,
    "org_slug": "bench-org",
    "fund_ids": [],
}
DEV_HEADERS = {
    "Content-Type": "application/json",
    "X-DEV-ACTOR": json.dumps(DEV_ACTOR),
}


async def cleanup(conn: asyncpg.Connection, ticker: str) -> int:
    """Drop any existing InstrumentOrg rows for the bench org × ticker."""
    deleted = await conn.execute(
        """
        DELETE FROM instruments_org io
        USING instruments_universe iu
        WHERE io.instrument_id = iu.instrument_id
          AND io.organization_id = $1::uuid
          AND iu.ticker = $2
        """,
        ORG_ID,
        ticker,
    )
    try:
        return int(deleted.split()[-1])
    except (IndexError, ValueError):
        return 0


async def count_rows(conn: asyncpg.Connection, ticker: str) -> int:
    return await conn.fetchval(
        """
        SELECT count(*)
        FROM instruments_org io
        JOIN instruments_universe iu ON iu.instrument_id = io.instrument_id
        WHERE io.organization_id = $1::uuid AND iu.ticker = $2
        """,
        ORG_ID,
        ticker,
    )


async def post_one(
    client: httpx.AsyncClient,
    ticker: str,
    idem_key: str,
) -> tuple[int, dict[str, Any], float]:
    headers = dict(DEV_HEADERS)
    headers["Idempotency-Key"] = idem_key
    start = time.monotonic()
    response = await client.post(
        f"{API_BASE}/screener/import/{ticker}",
        headers=headers,
        json={"block_id": None, "strategy": None},
    )
    elapsed_ms = (time.monotonic() - start) * 1000
    try:
        body = response.json()
    except json.JSONDecodeError:
        body = {"raw": response.text[:200]}
    return response.status_code, body, elapsed_ms


async def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    ticker = sys.argv[2] if len(sys.argv) > 2 else "VTI"
    parallel = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    print(f"==== {label} — {parallel}× POST /screener/import/{ticker} ====")

    db = await asyncpg.connect(DB_DSN)
    cleared = await cleanup(db, ticker)
    pre = await count_rows(db, ticker)
    print(f"Cleanup: dropped {cleared} pre-existing rows. Pre-state: {pre}")

    idem_key = f"compare-{uuid.uuid4().hex[:8]}"
    print(f"Idempotency-Key: {idem_key}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        wall_start = time.monotonic()
        results = await asyncio.gather(
            *[post_one(client, ticker, idem_key) for _ in range(parallel)],
            return_exceptions=True,
        )
        wall_ms = (time.monotonic() - wall_start) * 1000

    statuses: list[int] = []
    latencies: list[float] = []
    bodies: list[dict[str, Any]] = []
    errors: list[str] = []
    for r in results:
        if isinstance(r, Exception):
            errors.append(f"{type(r).__name__}: {r}")
            continue
        s, b, l = r
        statuses.append(s)
        bodies.append(b)
        latencies.append(l)

    # Wait briefly for any async worker to land its commits
    await asyncio.sleep(2.0)

    post = await count_rows(db, ticker)
    await db.close()

    summary = {
        "label": label,
        "ticker": ticker,
        "parallel": parallel,
        "wall_ms": round(wall_ms, 2),
        "status_codes": statuses,
        "errors": errors,
        "latency_min_ms": round(min(latencies), 2) if latencies else None,
        "latency_max_ms": round(max(latencies), 2) if latencies else None,
        "latency_mean_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "rows_pre": pre,
        "rows_post": post,
        "rows_created": post - pre,
        "passes_idempotency": (post - pre) == 1,
        # Body fingerprint — first body for each unique response shape
        "first_body_keys": sorted(bodies[0].keys()) if bodies else [],
    }

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
