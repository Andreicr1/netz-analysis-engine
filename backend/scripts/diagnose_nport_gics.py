"""N-PORT sector/GICS coverage diagnostic.

Read-only runner for the decision blocks in
`docs/superpowers/specs/2026-04-19-edhec-gaps-data-layer.md` §2.1,
adapted to the actual `sec_nport_holdings` schema (migration 0040).

Column reconciliation (spec → actual):
  filer_cik          → cik
  period_of_report   → report_date
  industry_sector    → sector
  issuer_category    → asset_class
  value_usd          → market_value
  sic_code           → DOES NOT EXIST

Emits a JSON artifact + human summary to stdout. Idempotent.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def _run(database_url: str) -> dict[str, Any]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    result: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "schema_reconciliation": {
            "filer_cik": "cik",
            "period_of_report": "report_date",
            "industry_sector": "sector",
            "issuer_category": "asset_class",
            "value_usd": "market_value",
            "sic_code": None,
        },
    }

    async with maker() as session:
        # Block A — sector coverage in recent 15 months
        row = (await session.execute(text("""
            WITH recent AS (
                SELECT *
                FROM sec_nport_holdings
                WHERE report_date >= (CURRENT_DATE - INTERVAL '15 months')
            )
            SELECT
                COUNT(*)                                                             AS total_rows,
                COUNT(*) FILTER (WHERE sector IS NULL OR btrim(sector) = '')         AS sector_null,
                ROUND(100.0 * COUNT(*) FILTER (WHERE sector IS NULL OR btrim(sector) = '')
                      / NULLIF(COUNT(*),0), 2)                                       AS pct_null,
                COUNT(*) FILTER (WHERE asset_class IS NOT NULL
                                  AND btrim(asset_class) <> '')                      AS asset_class_filled,
                ROUND(100.0 * COUNT(*) FILTER (WHERE asset_class IS NOT NULL
                                  AND btrim(asset_class) <> '')
                      / NULLIF(COUNT(*),0), 2)                                       AS pct_asset_class_filled,
                COUNT(DISTINCT sector)                                               AS distinct_sectors,
                COUNT(DISTINCT asset_class)                                          AS distinct_asset_classes
            FROM recent
        """))).mappings().one()
        result["block_a_coverage"] = dict(row)

        # Block B — top-50 sector values
        rows = (await session.execute(text("""
            SELECT sector, COUNT(*) AS n
            FROM sec_nport_holdings
            WHERE report_date >= (CURRENT_DATE - INTERVAL '15 months')
              AND sector IS NOT NULL AND btrim(sector) <> ''
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 50
        """))).mappings().all()
        result["block_b_top_sectors"] = [dict(r) for r in rows]

        # Block B.2 — top-20 asset_class values
        rows = (await session.execute(text("""
            SELECT asset_class, COUNT(*) AS n
            FROM sec_nport_holdings
            WHERE report_date >= (CURRENT_DATE - INTERVAL '15 months')
              AND asset_class IS NOT NULL AND btrim(asset_class) <> ''
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 20
        """))).mappings().all()
        result["block_b2_top_asset_classes"] = [dict(r) for r in rows]

        # Block C — column introspection (SIC/NAICS/industry/sector)
        rows = (await session.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'sec_nport_holdings'
              AND (column_name ILIKE '%sic%'
                OR column_name ILIKE '%naics%'
                OR column_name ILIKE '%industry%'
                OR column_name ILIKE '%sector%')
            ORDER BY column_name
        """))).mappings().all()
        result["block_c_classification_columns"] = [dict(r) for r in rows]

        # Block D — SIC/NAICS not applicable (column absent). Record explicitly.
        result["block_d_sic_stats"] = {
            "applicable": False,
            "reason": "sic_code column does not exist on sec_nport_holdings",
        }

    await engine.dispose()

    # Decision tree — adapted to absence of SIC column.
    block_a = result["block_a_coverage"]
    pct_null = float(block_a.get("pct_null") or 0.0)
    pct_asset_class_filled = float(block_a.get("pct_asset_class_filled") or 0.0)

    if pct_null < 10.0:
        scenario = "A"
        rationale = f"sector fill rate >= 90% (pct_null={pct_null}%). Use sector directly."
        recommendation = {
            "migration_0133_needed": False,
            "matview_strategy": "COALESCE(NULLIF(btrim(sector), ''), 'Unclassified')",
        }
    elif pct_null <= 30.0 and pct_asset_class_filled >= 70.0:
        scenario = "C_with_asset_class"
        rationale = (
            f"sector has {pct_null}% null and no SIC column exists; asset_class filled "
            f"at {pct_asset_class_filled}%. Degrade F2 to asset_class-only grouping."
        )
        recommendation = {
            "migration_0133_needed": False,
            "matview_strategy": (
                "Use COALESCE(NULLIF(btrim(sector), ''), asset_class, 'Unclassified') "
                "— asset_class as taxonomic fallback when sector missing."
            ),
        }
    else:
        scenario = "C"
        rationale = (
            f"sector null {pct_null}%, asset_class filled {pct_asset_class_filled}%. "
            "Both classification columns unreliable; Brinson aggregation must be deferred."
        )
        recommendation = {
            "migration_0133_needed": False,
            "matview_strategy": "ABORT — holdings-based rail unavailable; returns-based only.",
        }

    result["scenario"] = scenario
    result["scenario_rationale"] = rationale
    result["recommendation"] = recommendation
    return result


def _format_summary(result: dict[str, Any]) -> str:
    block_a = result["block_a_coverage"]
    lines = [
        "N-PORT GICS/Sector Coverage Diagnostic",
        "=" * 60,
        f"Run at:                 {result['run_at']}",
        f"Scenario:               {result['scenario']}",
        "",
        "Block A — Coverage (last 15 months):",
        f"  total_rows:             {block_a.get('total_rows')}",
        f"  sector_null:            {block_a.get('sector_null')}",
        f"  pct_null (sector):      {block_a.get('pct_null')}%",
        f"  pct_asset_class_filled: {block_a.get('pct_asset_class_filled')}%",
        f"  distinct_sectors:       {block_a.get('distinct_sectors')}",
        f"  distinct_asset_classes: {block_a.get('distinct_asset_classes')}",
        "",
        "Block C — Classification columns present:",
    ]
    for col in result["block_c_classification_columns"]:
        lines.append(f"  - {col['column_name']}: {col['data_type']}")
    lines += [
        "",
        f"Rationale: {result['scenario_rationale']}",
        "",
        "Recommendation:",
        f"  migration_0133_needed: {result['recommendation']['migration_0133_needed']}",
        f"  matview_strategy:      {result['recommendation']['matview_strategy']}",
    ]
    return "\n".join(lines)


async def _main() -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    result = await _run(database_url)

    out_dir = Path("docs/diagnostics")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = out_dir / f"{stamp}-nport-gics-coverage.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    print(_format_summary(result))
    print(f"\nArtifact written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
