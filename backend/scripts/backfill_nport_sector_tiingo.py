"""CLI runner for the N-PORT CUSIP Tiingo enrichment worker.

Usage:
    python -m scripts.backfill_nport_sector_tiingo \
        --max-openfigi-batches 10 \
        --max-tiingo-batches 20

Defaults cap both phases at 10 batches each — safe for dev iteration.
Remove caps (--max-* 0) to run full backfill.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from app.domains.wealth.workers.nport_cusip_enrichment_tiingo import run


def _none_if_zero(v: int) -> int | None:
    return None if v <= 0 else v


async def _main(args: argparse.Namespace) -> int:
    summary = await run(
        max_openfigi_batches=_none_if_zero(args.max_openfigi_batches),
        max_tiingo_batches=_none_if_zero(args.max_tiingo_batches),
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--max-openfigi-batches", type=int, default=10,
        help="Cap on OpenFIGI batches (0 = uncapped).",
    )
    p.add_argument(
        "--max-tiingo-batches", type=int, default=20,
        help="Cap on Tiingo fundamentals/meta batches (0 = uncapped).",
    )
    args = p.parse_args()

    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
