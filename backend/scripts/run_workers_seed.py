"""Run all background workers for initial data seed.

Usage:
    python scripts/run_workers_seed.py

Runs in order: macro → treasury → benchmark → OFR → BIS → IMF
Each worker is independent — failure in one does not stop the others.
"""
from __future__ import annotations

import asyncio
import time
import traceback


async def run_all() -> None:
    workers = [
        ("macro_ingestion",   _run_macro),
        ("treasury_ingestion", _run_treasury),
        ("benchmark_ingest",  _run_benchmark),
        ("ofr_ingestion",     _run_ofr),
        ("bis_ingestion",     _run_bis),
        ("imf_ingestion",     _run_imf),
    ]

    for name, fn in workers:
        print(f"\n{'=' * 60}")
        print(f"  Starting: {name}")
        print(f"{'=' * 60}")
        t0 = time.monotonic()
        try:
            result = await fn()
            elapsed = time.monotonic() - t0
            print(f"  Done: {name} ({elapsed:.1f}s) → {result}")
        except Exception:
            elapsed = time.monotonic() - t0
            print(f"  FAILED: {name} ({elapsed:.1f}s)")
            traceback.print_exc()


async def _run_macro():
    from app.domains.wealth.workers.macro_ingestion import run_macro_ingestion
    return await run_macro_ingestion(lookback_years=10)


async def _run_treasury():
    from app.domains.wealth.workers.treasury_ingestion import run_treasury_ingestion
    return await run_treasury_ingestion()


async def _run_benchmark():
    from app.domains.wealth.workers.benchmark_ingest import run_benchmark_ingest
    return await run_benchmark_ingest()


async def _run_ofr():
    from app.domains.wealth.workers.ofr_ingestion import run_ofr_ingestion
    return await run_ofr_ingestion()


async def _run_bis():
    from app.domains.wealth.workers.bis_ingestion import run_bis_ingestion
    return await run_bis_ingestion()


async def _run_imf():
    from app.domains.wealth.workers.imf_ingestion import run_imf_ingestion
    return await run_imf_ingestion()


if __name__ == "__main__":
    asyncio.run(run_all())
