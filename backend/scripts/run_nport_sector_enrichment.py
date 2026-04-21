"""Standalone runner for N-PORT sector enrichment.

Invokes the same `_enrich_nport_sectors` helper used by the scheduled
nport_ingestion worker, but decoupled from the ingestion flow so we can
backfill the matview without waiting for the full weekly cycle. After
every batch completes, refreshes `mv_nport_sector_attribution` so the
GICS sectors surface in the holdings rail immediately.

Usage:
    python -m scripts.run_nport_sector_enrichment --batches 10

Defaults to 1 batch (500 CUSIPs). Each batch loops until either the
batch limit is reached or the worker returns 0 enrichments (exhausted).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

from app.core.db.engine import async_session_factory
from app.domains.wealth.workers.nport_ingestion import (
    _enrich_nport_sectors,
    _refresh_sector_attribution_matview,
)


async def _run(batches: int, refresh_every: int) -> None:
    total = 0
    for i in range(1, batches + 1):
        t0 = time.monotonic()
        async with async_session_factory() as db:
            enriched = await _enrich_nport_sectors(db)
        dt = time.monotonic() - t0
        total += enriched
        print(
            f"[{i}/{batches}] batch enriched={enriched} "
            f"total={total} duration_s={dt:.1f}",
        )
        if enriched == 0:
            print("Exhausted — no more equity CUSIPs need enrichment.")
            break
        if i % max(1, refresh_every) == 0 or i == batches:
            t0 = time.monotonic()
            status = await _refresh_sector_attribution_matview()
            dt = time.monotonic() - t0
            print(f"  matview refresh: {status['status']} ({dt:.1f}s)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--batches", type=int, default=1)
    p.add_argument(
        "--refresh-every",
        type=int,
        default=5,
        help="Refresh matview every N batches (default 5).",
    )
    args = p.parse_args()

    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    asyncio.run(_run(args.batches, args.refresh_every))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
