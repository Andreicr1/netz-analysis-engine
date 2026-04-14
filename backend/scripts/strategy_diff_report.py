"""Generate a CSV diff report for a strategy_reclassification_stage run.

Usage
-----
    python backend/scripts/strategy_diff_report.py --run-id <uuid>
    python backend/scripts/strategy_diff_report.py --run-id <uuid> \\
        --severity asset_class_change
    python backend/scripts/strategy_diff_report.py --run-id <uuid> \\
        --severity lost_class --output reports/lost_class.csv

Output columns
--------------
source_table, source_pk, fund_name, current_label, proposed_label,
current_family, proposed_family, severity_tier, severity_label,
classification_source, confidence, matched_pattern,
allocation_blocks (only for P2/P3 — current label's blocks)

The CSV is intended for manual review in a spreadsheet before invoking
``apply_strategy_reclassification.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.services.classification_family import (
    classify_severity,
    family_of,
)

# Map severity tag → P-tier label used in CSV/output
TIER_LABEL: dict[str, str] = {
    "unchanged": "skip",
    "safe_auto_apply": "P0",
    "style_refinement": "P1",
    "asset_class_change": "P2",
    "lost_class": "P3",
}

# Severity tags accepted by --severity (excluding the meta "all" handled
# elsewhere). Reused by argparse and the apply script for consistency.
VALID_SEVERITIES: tuple[str, ...] = tuple(TIER_LABEL.keys())


async def fetch_stage_rows(
    run_id: UUID, severity_filter: str | None,
) -> list[dict[str, Any]]:
    """Read all unapplied rows for ``run_id``, classify by severity."""
    async with async_session() as db:
        result = await db.execute(
            text(
                """
                SELECT
                    source_table, source_pk, fund_name,
                    current_strategy_label, proposed_strategy_label,
                    classification_source, confidence, matched_pattern
                FROM strategy_reclassification_stage
                WHERE run_id = :run_id
                  AND applied_at IS NULL
                ORDER BY source_table, source_pk
                """,
            ),
            {"run_id": str(run_id)},
        )
        rows = result.mappings().all()

    out: list[dict[str, Any]] = []
    for row in rows:
        current = row["current_strategy_label"]
        proposed = row["proposed_strategy_label"]
        severity = classify_severity(current, proposed)
        if severity_filter and severity != severity_filter:
            continue
        out.append(
            {
                "source_table": row["source_table"],
                "source_pk": row["source_pk"],
                "fund_name": (row["fund_name"] or "")[:200],
                "current_label": current or "",
                "proposed_label": proposed or "",
                "current_family": family_of(current) or "",
                "proposed_family": family_of(proposed) or "",
                "severity_tier": TIER_LABEL[severity],
                "severity_label": severity,
                "classification_source": row["classification_source"] or "",
                "confidence": row["confidence"] or "",
                "matched_pattern": row["matched_pattern"] or "",
            },
        )
    return out


def enrich_allocation_blocks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stamp each P2/P3 row with the allocation_blocks of its CURRENT label.

    P0/P1 rows are left blank — they are either harmless additions or
    same-family refinements that won't move blocks. The mapping is pure
    Python (no DB) so this is essentially free.
    """
    # Local import avoids paying the import cost when the script is used
    # to materialize an unfiltered diff (e.g., piping straight to a CSV
    # for raw audit, where allocation impact isn't needed).
    from vertical_engines.wealth.model_portfolio.block_mapping import (
        blocks_for_strategy_label,
    )

    for row in rows:
        if row["severity_tier"] in ("P2", "P3"):
            blocks = blocks_for_strategy_label(row["current_label"] or None)
            row["allocation_blocks"] = ",".join(blocks) if blocks else ""
        else:
            row["allocation_blocks"] = ""
    return rows


def _print_summary(rows: list[dict[str, Any]]) -> None:
    tier_counts = Counter(r["severity_tier"] for r in rows)
    source_counts = Counter(r["source_table"] for r in rows)
    print("\nSeverity tier breakdown:")
    for tier in ("P0", "P1", "P2", "P3", "skip"):
        print(f"  {tier}: {tier_counts.get(tier, 0):,}")
    print("\nPer source_table:")
    for source, count in sorted(source_counts.items()):
        print(f"  {source}: {count:,}")


def _write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    fieldnames = [
        "source_table",
        "source_pk",
        "fund_name",
        "current_label",
        "proposed_label",
        "current_family",
        "proposed_family",
        "severity_tier",
        "severity_label",
        "classification_source",
        "confidence",
        "matched_pattern",
        "allocation_blocks",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="Stage run_id (UUID)")
    parser.add_argument(
        "--severity",
        default=None,
        choices=VALID_SEVERITIES,
        help="Filter to a single severity (default: all)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (default: reports/strategy_diff_<run8>.csv)",
    )
    parser.add_argument(
        "--skip-blocks",
        action="store_true",
        help="Skip allocation_blocks enrichment",
    )
    args = parser.parse_args()

    run_id = UUID(args.run_id)
    output = Path(
        args.output
        or f"reports/strategy_diff_{str(run_id)[:8]}.csv",
    )

    rows = await fetch_stage_rows(run_id, args.severity)
    print(f"Fetched {len(rows):,} stage rows")

    if not rows:
        print("No rows matched filter — nothing to write.")
        return

    if not args.skip_blocks:
        rows = enrich_allocation_blocks(rows)

    _write_csv(rows, output)
    print(f"Wrote {len(rows):,} rows to {output}")
    _print_summary(rows)


if __name__ == "__main__":
    asyncio.run(main())
