"""CLI runner for the FIRDS UCITS security sync worker (PR-Q11B).

Populates ``esma_securities`` from ESMA FIRDS FULINS_C daily files,
filtered by known ``esma_funds.lei`` values.

Usage:
    python backend/scripts/run_firds_ucits_security_sync.py
    python backend/scripts/run_firds_ucits_security_sync.py --target-date 2026-04-25
    python backend/scripts/run_firds_ucits_security_sync.py --dry-run
"""
import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

# Allow ``python backend/scripts/run_firds_ucits_security_sync.py`` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db.engine import async_session_factory  # noqa: E402
from app.core.jobs.firds_ucits_security_sync import run_firds_ucits_security_sync  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the FIRDS UCITS security sync worker.",
    )
    parser.add_argument(
        "--target-date",
        type=date.fromisoformat,
        default=None,
        help="FIRDS publication date to fetch (YYYY-MM-DD). Default: yesterday.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count without upserting.",
    )

    args = parser.parse_args()

    async with async_session_factory() as db:
        result = await run_firds_ucits_security_sync(
            db,
            target_date=args.target_date,
            dry_run=args.dry_run,
        )

    print("\nFIRDS Sync Summary:")
    for k, v in result.items():
        print(f"  {k}: {v}")

    if result.get("status") == "skipped":
        sys.exit(2)
    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
