"""PR-A23 Section C — batch re-classification of auto-imported rows.

Re-runs the corrected classifier over every ``instruments_org`` row
with ``source LIKE '%universe_auto_import%'`` and updates ``block_id``
where the new classifier result differs from the stored value. Rows
that newly surface a ``needs_human_review`` reason have their
corresponding ``instruments_universe.attributes.needs_human_review``
flag set to ``true`` (JSONB merge).

Must run AFTER migration ``0151_fix_known_strategy_labels`` —
strategy_label is the classifier's primary signal, so the label patch
needs to land first.

Idempotent: re-running on a clean state produces zero changes. Each
organization is processed in its own transaction. Honors the
``instruments_org.block_overridden = TRUE`` flag — hand-curated
overrides are never touched.

Usage::

    # Preview intended changes without writing.
    python -m backend.scripts.pr_a23_reclassify_auto_import --dry-run

    # Apply.
    python -m backend.scripts.pr_a23_reclassify_auto_import
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.domains.wealth.services.universe_auto_import_classifier import (
    classify_block,
)

logger: Any = structlog.get_logger()


_SELECT_ROWS_SQL = text(
    """
    SELECT io.id,
           io.instrument_id,
           io.block_id AS current_block_id,
           io.block_overridden,
           iu.ticker,
           iu.instrument_type,
           iu.asset_class,
           iu.investment_geography,
           iu.name,
           iu.attributes
      FROM instruments_org io
      JOIN instruments_universe iu USING (instrument_id)
     WHERE io.organization_id = :org_id
       AND io.source LIKE '%universe_auto_import%'
    """
)

_UPDATE_BLOCK_SQL = text(
    """
    UPDATE instruments_org
       SET block_id = :block_id
     WHERE id = :row_id
       AND block_overridden = FALSE
    """
)

_FLAG_UNIVERSE_SQL = text(
    """
    UPDATE instruments_universe
       SET attributes = jsonb_set(
           COALESCE(attributes, '{}'::jsonb),
           '{needs_human_review}',
           'true'::jsonb,
           true
       )
     WHERE instrument_id = :instrument_id
       AND COALESCE(attributes->>'needs_human_review', 'false') <> 'true'
    """
)


# PR-A24 — mandate-level exclusion reclassification: when the updated
# classifier surfaces a muni (or other excluded-class) instrument, we
# DELETE the org row rather than nulling block_id. Honours block_overridden
# so hand-curated selections are never touched.
_DELETE_EXCLUDED_SQL = text(
    """
    DELETE FROM instruments_org
     WHERE id = :row_id
       AND block_overridden = FALSE
    """
)

_FLAG_UNIVERSE_EXCLUDED_SQL = text(
    """
    UPDATE instruments_universe
       SET attributes = jsonb_set(
           COALESCE(attributes, '{}'::jsonb),
           '{strategic_excluded_reason}',
           to_jsonb(CAST(:strategy_label AS text)),
           true
       )
     WHERE instrument_id = :instrument_id
       AND COALESCE(
               attributes->>'strategic_excluded_reason', ''
           ) IS DISTINCT FROM :strategy_label
    """
)

_VALID_BLOCKS_SQL = text("SELECT block_id FROM allocation_blocks")

_LIST_ORGS_SQL = text(
    """
    SELECT DISTINCT organization_id
      FROM instruments_org
     WHERE source LIKE '%universe_auto_import%'
       AND organization_id IS NOT NULL
    """
)


class _OrgSummary(dict[str, Any]):
    """Typed-dict-like container for per-org results."""


async def _valid_blocks(db: AsyncSession) -> set[str]:
    result = await db.execute(_VALID_BLOCKS_SQL)
    return {row[0] for row in result.all()}


async def _process_org(
    db: AsyncSession,
    *,
    org_id: UUID,
    valid_blocks: set[str],
    dry_run: bool,
) -> _OrgSummary:
    """Re-classify every auto-imported row for a single org.

    Returns a summary dict with counts of updates / flags / no-ops.
    Writes inside a single transaction (caller's session is used; the
    caller commits or rolls back).
    """
    await db.execute(text("SET LOCAL statement_timeout = '120s'"))

    rows = (
        await db.execute(_SELECT_ROWS_SQL, {"org_id": str(org_id)})
    ).mappings().all()

    rows_updated = 0
    rows_flagged = 0
    rows_override_skipped = 0
    rows_unchanged = 0
    rows_deleted_as_excluded = 0
    changes: list[dict[str, Any]] = []

    for row in rows:
        payload: dict[str, Any] = {
            "instrument_id": row["instrument_id"],
            "instrument_type": row["instrument_type"],
            "asset_class": row["asset_class"],
            "investment_geography": row["investment_geography"] or "",
            "name": row["name"] or "",
            "ticker": row["ticker"],
            "attributes": row["attributes"] or {},
        }
        new_block, new_reason = classify_block(payload, valid_blocks=valid_blocks)
        current_block = row["current_block_id"]

        # PR-A24 — mandate-level exclusion: delete the org row entirely
        # rather than flag or null. Honours block_overridden (operator
        # curated) — those rows are left intact and recorded as drift.
        if new_reason == "excluded_asset_class":
            if row["block_overridden"]:
                rows_override_skipped += 1
                changes.append({
                    "row_id": str(row["id"]),
                    "ticker": row["ticker"],
                    "current_block_id": current_block,
                    "new_block_id": None,
                    "new_reason": new_reason,
                    "applied": False,
                    "skip_reason": "block_overridden",
                })
                continue
            if not dry_run:
                strategy_label = (row["attributes"] or {}).get("strategy_label")
                await db.execute(
                    _DELETE_EXCLUDED_SQL,
                    {"row_id": row["id"]},
                )
                await db.execute(
                    _FLAG_UNIVERSE_EXCLUDED_SQL,
                    {
                        "instrument_id": row["instrument_id"],
                        "strategy_label": strategy_label,
                    },
                )
            rows_deleted_as_excluded += 1
            changes.append({
                "row_id": str(row["id"]),
                "ticker": row["ticker"],
                "current_block_id": current_block,
                "new_block_id": None,
                "new_reason": new_reason,
                "applied": not dry_run,
                "skip_reason": None,
            })
            continue

        if new_block == current_block:
            rows_unchanged += 1
            continue

        # New classifier result surfaces a needs_review → flag universe.
        if new_block is None:
            if not dry_run:
                await db.execute(
                    _FLAG_UNIVERSE_SQL,
                    {"instrument_id": row["instrument_id"]},
                )
            rows_flagged += 1

        if row["block_overridden"]:
            # Human-curated — never overwrite, but record the drift.
            rows_override_skipped += 1
            changes.append({
                "row_id": str(row["id"]),
                "ticker": row["ticker"],
                "current_block_id": current_block,
                "new_block_id": new_block,
                "new_reason": new_reason,
                "applied": False,
                "skip_reason": "block_overridden",
            })
            continue

        if not dry_run:
            await db.execute(
                _UPDATE_BLOCK_SQL,
                {"block_id": new_block, "row_id": row["id"]},
            )
        rows_updated += 1
        changes.append({
            "row_id": str(row["id"]),
            "ticker": row["ticker"],
            "current_block_id": current_block,
            "new_block_id": new_block,
            "new_reason": new_reason,
            "applied": not dry_run,
            "skip_reason": None,
        })

    return _OrgSummary(
        org_id=str(org_id),
        rows_considered=len(rows),
        rows_updated=rows_updated,
        rows_flagged_for_review=rows_flagged,
        rows_override_skipped=rows_override_skipped,
        rows_unchanged=rows_unchanged,
        rows_deleted_as_excluded=rows_deleted_as_excluded,
        changes=changes,
    )


async def _run(dry_run: bool) -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Fetch org list + valid blocks in an RLS-free session (no-RLS reads).
    async with session_factory() as db:
        valid_blocks = await _valid_blocks(db)
        org_ids = [
            row[0] for row in (await db.execute(_LIST_ORGS_SQL)).all()
        ]

    per_org_summaries: list[_OrgSummary] = []
    total_updated = 0
    total_flagged = 0
    total_override_skipped = 0
    total_unchanged = 0
    total_deleted_as_excluded = 0

    for org_id in org_ids:
        async with session_factory() as db:
            # Scope RLS context per org so UPDATEs on instruments_org
            # respect tenancy. instruments_universe is global (no RLS).
            # PostgreSQL's SET LOCAL cannot use bind params — interpolate
            # the UUID directly. Safe because org_id is already a UUID
            # instance from the DB, not user input.
            await db.execute(
                text(
                    f"SET LOCAL app.current_organization_id = '{org_id}'",
                ),
            )
            summary = await _process_org(
                db,
                org_id=org_id,
                valid_blocks=valid_blocks,
                dry_run=dry_run,
            )
            if dry_run:
                await db.rollback()
            else:
                await db.commit()

        per_org_summaries.append(summary)
        total_updated += summary["rows_updated"]
        total_flagged += summary["rows_flagged_for_review"]
        total_override_skipped += summary["rows_override_skipped"]
        total_unchanged += summary["rows_unchanged"]
        total_deleted_as_excluded += summary["rows_deleted_as_excluded"]

    await engine.dispose()

    return {
        "dry_run": dry_run,
        "orgs_processed": len(org_ids),
        "rows_updated": total_updated,
        "rows_flagged_for_review": total_flagged,
        "rows_override_skipped": total_override_skipped,
        "rows_unchanged": total_unchanged,
        "rows_deleted_as_excluded": total_deleted_as_excluded,
        "per_org": per_org_summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended changes without writing.",
    )
    args = parser.parse_args()

    report = asyncio.run(_run(dry_run=args.dry_run))

    summary_only = {
        k: v for k, v in report.items() if k != "per_org"
    }
    print(json.dumps(summary_only, indent=2))

    print(
        f"[pr_a23_reclassify] dry_run={report['dry_run']} "
        f"orgs={report['orgs_processed']} "
        f"updated={report['rows_updated']} "
        f"flagged_for_review={report['rows_flagged_for_review']} "
        f"override_skipped={report['rows_override_skipped']} "
        f"unchanged={report['rows_unchanged']} "
        f"deleted_as_excluded={report['rows_deleted_as_excluded']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
