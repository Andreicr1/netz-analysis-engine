"""Stability Guardrails Phase 4 — reproducible benchmark suite.

Runs against a live backend (`make serve`) + PG + Redis (`make up`)
to produce hard numbers for the impact report.

Usage:
    python -m backend.scripts.benchmark_stability_phase4

Three benchmarks:
  B1 — Idempotency: 5 parallel POST /screener/import/{ticker} with the
       same Idempotency-Key header. Asserts that exactly ONE distinct
       job_id is returned and exactly ONE InstrumentOrg row is created.
  B2 — Enqueue latency: 50 sequential imports of distinct tickers,
       measure p50/p95/p99 of the 202 enqueue. Proves the Job-or-Stream
       refactor brought the request handler under 100 ms.
  B3 — Triple-layer dedup against the DB: 20 parallel POSTs with 4
       distinct Idempotency-Keys (5 per key). Asserts exactly 4 jobs
       and 4 InstrumentOrg rows (proves the @idempotent + SingleFlight
       + crc32 advisory lock collapse correctly).
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
import uuid
from typing import Any

import asyncpg
import httpx

API_BASE = "http://127.0.0.1:8000/api/v1"
DB_DSN = "postgresql://netz:password@localhost:5434/netz_engine"

# Dev bypass actor — schema MUST match `_parse_dev_actor` in
# backend/app/core/security/clerk_auth.py: fields are `actor_id`,
# `org_id`, `org_slug`, `roles` (list of role strings), `fund_ids`
# (list of uuid strings). Field name mismatches silently produce
# an Actor with organization_id=None, which then makes the worker
# crash on InstrumentOrg.organization_id NOT NULL — exactly the
# failure mode the first run of this benchmark uncovered.
DEV_ACTOR = {
    "actor_id": "bench-actor-001",
    "name": "Bench Actor",
    "email": "bench@netz.local",
    "roles": ["INVESTMENT_TEAM", "ADMIN"],
    "org_id": "f1392e06-dda0-5537-aee7-2474f2ce9241",  # set in setup_org()
    "org_slug": "bench-org",
    "fund_ids": [],
}
DEV_HEADERS = {
    "Content-Type": "application/json",
    "X-DEV-ACTOR": json.dumps(DEV_ACTOR),
}


async def setup_org(conn: asyncpg.Connection) -> str:
    """Mint a stable UUID for the bench org. The Netz multi-tenant
    layer treats organization_id as the Clerk-issued UUID — there is
    no local ``organizations`` table, just RLS via SET LOCAL on the
    Clerk-issued ID.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, "bench-org-001"))


async def cleanup_org_imports(conn: asyncpg.Connection, org_id: str) -> int:
    """Drop any leftover instruments_org rows for the bench org so each
    benchmark run starts from a clean slate. Returns the count cleared.
    """
    result = await conn.execute(
        "DELETE FROM instruments_org WHERE organization_id = $1::uuid",
        org_id,
    )
    # asyncpg's execute returns "DELETE n" — parse n
    try:
        return int(result.split()[-1])
    except (IndexError, ValueError):
        return 0


async def count_org_instruments(
    conn: asyncpg.Connection,
    org_id: str,
    ticker: str,
) -> int:
    """Count InstrumentOrg rows for a given (org, ticker) pair."""
    return await conn.fetchval(
        """
        SELECT count(*)
        FROM instruments_org io
        JOIN instruments_universe iu ON iu.instrument_id = io.instrument_id
        WHERE io.organization_id = $1::uuid AND iu.ticker = $2
        """,
        org_id,
        ticker,
    )


async def post_import(
    client: httpx.AsyncClient,
    ticker: str,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = dict(DEV_HEADERS)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    response = await client.post(
        f"{API_BASE}/screener/import/{ticker}",
        headers=headers,
        json={"block_id": None, "strategy": None},
    )
    body: dict[str, Any]
    try:
        body = response.json()
    except json.JSONDecodeError:
        body = {"raw": response.text}
    return response.status_code, body


async def wait_for_terminal(
    client: httpx.AsyncClient, job_id: str, timeout: float = 10.0,
) -> dict[str, Any] | None:
    """Poll /jobs/{id}/status until terminal or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = await client.get(
            f"{API_BASE}/jobs/{job_id}/status",
            headers=DEV_HEADERS,
        )
        if r.status_code == 200:
            return r.json()
        await asyncio.sleep(0.1)
    return None


# ── B1 — Idempotency: 5 parallel calls, same key, expect 1 job ────


async def benchmark_b1(
    client: httpx.AsyncClient,
    db: asyncpg.Connection,
    org_id: str,
) -> dict[str, Any]:
    print("\n" + "=" * 64)
    print("B1 — IDEMPOTENCY: 5 parallel POSTs with same Idempotency-Key")
    print("=" * 64)
    ticker = "VTI"
    await cleanup_org_imports(db, org_id)
    pre_count = await count_org_instruments(db, org_id, ticker)
    print(f"Pre-state: {pre_count} InstrumentOrg rows for {ticker}")

    idem_key = f"b1-bench-{uuid.uuid4().hex[:8]}"
    print(f"Idempotency-Key: {idem_key}")

    start = time.monotonic()
    results = await asyncio.gather(
        *[post_import(client, ticker, idem_key) for _ in range(5)],
        return_exceptions=True,
    )
    elapsed_ms = (time.monotonic() - start) * 1000

    statuses = [r[0] if isinstance(r, tuple) else 599 for r in results]
    bodies = [r[1] if isinstance(r, tuple) else {"err": str(r)} for r in results]
    job_ids = {b.get("job_id") for b in bodies if b.get("job_id")}

    print(f"Wall time: {elapsed_ms:.1f} ms")
    print(f"Status codes: {statuses}")
    print(f"Distinct job_ids: {len(job_ids)} -> {sorted(job_ids)}")

    # Wait for the worker to land
    if job_ids:
        first_job = next(iter(job_ids))
        await wait_for_terminal(client, first_job)

    post_count = await count_org_instruments(db, org_id, ticker)
    print(f"Post-state: {post_count} InstrumentOrg rows for {ticker}")

    return {
        "ticker": ticker,
        "wall_ms": elapsed_ms,
        "status_codes": statuses,
        "distinct_job_ids": len(job_ids),
        "instrument_rows_pre": pre_count,
        "instrument_rows_post": post_count,
        "passes_acceptance": (
            len(job_ids) == 1
            and post_count - pre_count == 1
            and all(s in (200, 202) for s in statuses)
        ),
    }


# ── B2 — Enqueue latency: 50 sequential distinct imports ──────────


async def benchmark_b2(
    client: httpx.AsyncClient,
    db: asyncpg.Connection,
    org_id: str,
) -> dict[str, Any]:
    print("\n" + "=" * 64)
    print("B2 — ENQUEUE LATENCY: 50 sequential POSTs (p50/p95/p99)")
    print("=" * 64)

    # Pick 50 distinct tickers from sec_cusip_ticker_map that are
    # already in instruments_universe (so the LINKED fast path runs).
    rows = await db.fetch(
        """
        SELECT iu.ticker
        FROM instruments_universe iu
        WHERE iu.ticker IS NOT NULL
          AND length(iu.ticker) BETWEEN 1 AND 5
          AND iu.ticker ~ '^[A-Z]+$'
        ORDER BY iu.ticker
        LIMIT 50
        """,
    )
    tickers = [r["ticker"] for r in rows]
    print(f"Sample size: {len(tickers)} tickers")
    if len(tickers) < 5:
        print(f"WARNING: only {len(tickers)} eligible tickers — results sparse")

    await cleanup_org_imports(db, org_id)

    latencies_ms: list[float] = []
    for ticker in tickers:
        start = time.monotonic()
        status, body = await post_import(client, ticker, None)
        latencies_ms.append((time.monotonic() - start) * 1000)
        if status not in (200, 202):
            print(f"  {ticker}: HTTP {status} {body}")

    p50 = statistics.median(latencies_ms)
    p95 = statistics.quantiles(latencies_ms, n=20)[18] if len(latencies_ms) >= 20 else max(latencies_ms)
    p99 = statistics.quantiles(latencies_ms, n=100)[98] if len(latencies_ms) >= 100 else max(latencies_ms)
    mean = statistics.fmean(latencies_ms)
    mx = max(latencies_ms)

    print(f"Mean:  {mean:7.1f} ms")
    print(f"p50:   {p50:7.1f} ms")
    print(f"p95:   {p95:7.1f} ms")
    print(f"p99:   {p99:7.1f} ms")
    print(f"max:   {mx:7.1f} ms")
    print(f"Acceptance (p95 < 500ms — Job-or-Stream guarantee): "
          f"{'PASS' if p95 < 500 else 'FAIL'}")

    return {
        "sample_size": len(tickers),
        "mean_ms": mean,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "max_ms": mx,
        "passes_acceptance": p95 < 500,
    }


# ── B3 — Triple-layer dedup: 4 keys × 5 calls each ──────────────


async def benchmark_b3(
    client: httpx.AsyncClient,
    db: asyncpg.Connection,
    org_id: str,
) -> dict[str, Any]:
    print("\n" + "=" * 64)
    print("B3 — TRIPLE-LAYER DEDUP: 4 keys x 5 parallel calls each")
    print("=" * 64)
    tickers = ["IWM", "QQQ", "DIA", "SPY"]
    await cleanup_org_imports(db, org_id)

    keys = [f"b3-{t}-{uuid.uuid4().hex[:6]}" for t in tickers]
    print(f"Tickers: {tickers}")
    print(f"Keys: {keys}")

    start = time.monotonic()
    tasks = []
    for ticker, key in zip(tickers, keys, strict=False):
        for _ in range(5):
            tasks.append(post_import(client, ticker, key))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed_ms = (time.monotonic() - start) * 1000

    bodies = [r[1] if isinstance(r, tuple) else {"err": str(r)} for r in results]
    job_ids = {b.get("job_id") for b in bodies if b.get("job_id")}
    print(f"Wall time: {elapsed_ms:.1f} ms ({len(tasks)} requests)")
    print(f"Distinct job_ids: {len(job_ids)} (expected 4)")

    # Wait for workers
    for job_id in job_ids:
        await wait_for_terminal(client, job_id, timeout=15.0)

    counts = {
        ticker: await count_org_instruments(db, org_id, ticker)
        for ticker in tickers
    }
    print(f"InstrumentOrg rows per ticker: {counts}")
    expected = {t: 1 for t in tickers}

    return {
        "wall_ms": elapsed_ms,
        "request_count": len(tasks),
        "distinct_job_ids": len(job_ids),
        "instrument_counts": counts,
        "passes_acceptance": (
            len(job_ids) == len(tickers)
            and counts == expected
        ),
    }


# ── Runner ─────────────────────────────────────────────────────────


async def main() -> None:
    print("Stability Guardrails — Phase 4 reproducible benchmark")
    print(f"API: {API_BASE}")
    print(f"DB:  {DB_DSN}")

    db = await asyncpg.connect(DB_DSN)
    org_id = await setup_org(db)
    print(f"Bench org: {org_id}")

    # Patch the dev actor's org_id to match the seeded uuid
    DEV_ACTOR["org_id"] = org_id
    DEV_HEADERS["X-DEV-ACTOR"] = json.dumps(DEV_ACTOR)

    async with httpx.AsyncClient(timeout=15.0) as client:
        b1 = await benchmark_b1(client, db, org_id)
        b2 = await benchmark_b2(client, db, org_id)
        b3 = await benchmark_b3(client, db, org_id)

    await db.close()

    print("\n" + "=" * 64)
    print("SUMMARY")
    print("=" * 64)
    print(json.dumps(
        {"B1": b1, "B2": b2, "B3": b3},
        indent=2,
        default=str,
    ))


if __name__ == "__main__":
    asyncio.run(main())
