"""Generate audit report of universe sanitization exclusions.

Usage:
    python backend/scripts/universe_sanitization_report.py [--samples=20]

Output:
    - Per-table, per-reason exclusion counts
    - Remaining institutional totals
    - Random samples of excluded funds for the largest table
      (sec_manager_funds) to spot-check false positives before moving on
      to Round 2 classifier patches or Session B of the apply gate.

Run AFTER ``run_universe_sanitization()`` completes and before promoting
the new classifier/apply-gate outputs.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

TABLES = [
    "sec_manager_funds",
    "sec_registered_funds",
    "sec_etfs",
    "sec_bdcs",
    "sec_money_market_funds",
    "esma_funds",
]


async def main(samples: int = 20) -> None:
    from app.core.db.engine import async_session_factory

    print("\n=== UNIVERSE SANITIZATION AUDIT REPORT ===\n")

    async with async_session_factory() as db:
        for table in TABLES:
            print(f"\n--- {table} ---")
            r = await db.execute(text(f"""
                SELECT
                    exclusion_reason,
                    COUNT(*) AS n
                FROM {table}
                WHERE NOT is_institutional
                GROUP BY exclusion_reason
                ORDER BY n DESC
            """))
            rows = r.all()
            if not rows:
                print("  (no exclusions)")
            else:
                total_excluded = sum(row[1] for row in rows)
                for reason, n in rows:
                    reason_str = reason or "(null)"
                    print(f"  {reason_str:<30} {n:>8,}")
                print(f"  {'TOTAL EXCLUDED':<30} {total_excluded:>8,}")

            inst_r = await db.execute(text(f"""
                SELECT COUNT(*) FROM {table} WHERE is_institutional
            """))
            inst = inst_r.scalar() or 0
            print(f"  {'INSTITUTIONAL':<30} {inst:>8,}")

        # Samples per reason for sec_manager_funds (largest table).
        print(
            f"\n\n=== SAMPLE EXCLUSIONS "
            f"(sec_manager_funds, {samples} per reason) ===",
        )
        reasons_r = await db.execute(text("""
            SELECT DISTINCT exclusion_reason
            FROM sec_manager_funds
            WHERE NOT is_institutional AND exclusion_reason IS NOT NULL
            ORDER BY exclusion_reason
        """))
        for (reason,) in reasons_r.all():
            print(f"\n--- {reason} ---")
            r = await db.execute(
                text("""
                    SELECT fund_name, crd_number, gross_asset_value
                    FROM sec_manager_funds
                    WHERE exclusion_reason = :reason
                    ORDER BY RANDOM()
                    LIMIT :limit
                """),
                {"reason": reason, "limit": samples},
            )
            for row in r.all():
                name, crd, gav = row
                gav_str = f"${gav/1e9:.2f}B" if gav else "--"
                name_str = (name or "?")[:70]
                print(f"  [{crd}] {name_str:<70} {gav_str}")


if __name__ == "__main__":
    samples = 20
    for arg in sys.argv[1:]:
        if arg.startswith("--samples="):
            samples = int(arg.split("=", 1)[1])
    asyncio.run(main(samples=samples))
