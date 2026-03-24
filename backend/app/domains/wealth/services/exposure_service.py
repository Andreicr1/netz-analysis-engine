"""Exposure service — aggregates real portfolio positions by geography or sector.

Data flow:
    portfolio_snapshots.weights (JSONB {block_id: weight})
    → allocation_blocks (block_id → geography, asset_class)
    → pivot into matrix (rows × columns → 2D weights)

Never-raises: returns empty response on any error.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.schemas.exposure import ExposureMatrixRead, ExposureMetadataRead

logger = structlog.get_logger()

# Dimension → AllocationBlock column. Fixed dict — safe to interpolate in SQL.
_DIM_COL: dict[str, str] = {
    "geographic": "geography",
    "sector": "asset_class",
}

_EMPTY_MATRIX = dict(rows=[], columns=[], data=[], is_empty=True, as_of=None)


async def get_exposure_matrix(
    db: AsyncSession,
    organization_id: UUID | None,
    dimension: Literal["geographic", "sector"],
    aggregation: Literal["portfolio", "manager"],
) -> ExposureMatrixRead:
    """Return weighted exposure matrix from real portfolio snapshots."""
    try:
        if organization_id is None:
            return ExposureMatrixRead(dimension=dimension, aggregation=aggregation, **_EMPTY_MATRIX)
        dim_col = _DIM_COL[dimension]
        org_id = str(organization_id)

        if aggregation == "portfolio":
            raw = await _query_portfolio_exposure(db, org_id, dim_col)
        else:
            raw = await _query_manager_exposure(db, org_id, dim_col)

        if not raw:
            return ExposureMatrixRead(dimension=dimension, aggregation=aggregation, **_EMPTY_MATRIX)

        # Pivot flat rows into matrix
        as_of = raw[0].as_of
        row_labels: list[str] = list(dict.fromkeys(r.row_label for r in raw))
        col_labels: list[str] = list(dict.fromkeys(r.dimension_value for r in raw))
        cell_map = {(r.row_label, r.dimension_value): float(r.total_weight) for r in raw}
        data = [
            [round(cell_map.get((row, col), 0.0), 6) for col in col_labels]
            for row in row_labels
        ]

        return ExposureMatrixRead(
            dimension=dimension,
            aggregation=aggregation,
            rows=row_labels,
            columns=col_labels,
            data=data,
            is_empty=False,
            as_of=as_of,
        )
    except Exception:
        logger.exception("exposure_matrix_failed", dimension=dimension, aggregation=aggregation)
        return ExposureMatrixRead(dimension=dimension, aggregation=aggregation, **_EMPTY_MATRIX)


async def get_exposure_metadata(
    db: AsyncSession,
    organization_id: UUID | None,
) -> ExposureMetadataRead:
    """Return snapshot freshness metadata for the tenant."""
    try:
        if organization_id is None:
            return ExposureMetadataRead(as_of=None, snapshot_count=0, profile_count=0)
        org_id = str(organization_id)
        result = await db.execute(
            text("""
                SELECT
                    MAX(snapshot_date)    AS as_of,
                    COUNT(*)             AS snapshot_count,
                    COUNT(DISTINCT profile) AS profile_count
                FROM portfolio_snapshots
                WHERE organization_id = :org_id
            """),
            {"org_id": org_id},
        )
        row = result.one()
        return ExposureMetadataRead(
            as_of=row.as_of,
            snapshot_count=row.snapshot_count,
            profile_count=row.profile_count,
        )
    except Exception:
        logger.exception("exposure_metadata_failed")
        return ExposureMetadataRead(as_of=None, snapshot_count=0, profile_count=0)


# ---------------------------------------------------------------------------
#  Internal query helpers
# ---------------------------------------------------------------------------


async def _query_portfolio_exposure(
    db: AsyncSession, org_id: str, dim_col: str,
) -> list:
    """Rows = profiles, values = block weights grouped by dimension.

    dim_col is from _DIM_COL (fixed dict), not user input — safe to embed.
    """
    sql = text(f"""
        WITH latest AS (
            SELECT MAX(snapshot_date) AS max_date
            FROM portfolio_snapshots
            WHERE organization_id = :org_id
        )
        SELECT
            ps.profile                     AS row_label,
            ab.{dim_col}                   AS dimension_value,
            SUM((w.value)::numeric)        AS total_weight,
            latest.max_date                AS as_of
        FROM portfolio_snapshots ps
        CROSS JOIN latest
        CROSS JOIN LATERAL jsonb_each_text(ps.weights) AS w(block_id, value)
        JOIN allocation_blocks ab
            ON ab.block_id = w.block_id AND ab.is_active = true
        WHERE ps.organization_id = :org_id
          AND ps.snapshot_date = latest.max_date
        GROUP BY ps.profile, ab.{dim_col}, latest.max_date
        ORDER BY ps.profile, total_weight DESC
    """)
    result = await db.execute(sql, {"org_id": org_id})
    return result.all()


async def _query_manager_exposure(
    db: AsyncSession, org_id: str, dim_col: str,
) -> list:
    """Rows = manager names, values = proportional block weights by dimension.

    Block weight is distributed equally among active instruments in that block.
    dim_col is from _DIM_COL (fixed dict), not user input — safe to embed.
    """
    sql = text(f"""
        WITH latest AS (
            SELECT MAX(snapshot_date) AS max_date
            FROM portfolio_snapshots
            WHERE organization_id = :org_id
        ),
        block_totals AS (
            SELECT
                w.block_id,
                SUM((w.value)::numeric) AS total_weight
            FROM portfolio_snapshots ps
            CROSS JOIN latest
            CROSS JOIN LATERAL jsonb_each_text(ps.weights) AS w(block_id, value)
            WHERE ps.organization_id = :org_id
              AND ps.snapshot_date = latest.max_date
            GROUP BY w.block_id
        ),
        inst_counts AS (
            SELECT block_id, COUNT(*) AS cnt
            FROM instruments_universe
            WHERE organization_id = :org_id AND is_active = true
            GROUP BY block_id
        )
        SELECT
            COALESCE(i.attributes->>'manager_name', i.name) AS row_label,
            ab.{dim_col}                                     AS dimension_value,
            SUM(bt.total_weight / GREATEST(ic.cnt, 1))       AS total_weight,
            (SELECT max_date FROM latest)                     AS as_of
        FROM block_totals bt
        JOIN allocation_blocks ab
            ON ab.block_id = bt.block_id AND ab.is_active = true
        JOIN instruments_universe i
            ON i.block_id = bt.block_id
           AND i.organization_id = :org_id
           AND i.is_active = true
        LEFT JOIN inst_counts ic ON ic.block_id = bt.block_id
        GROUP BY row_label, ab.{dim_col}
        ORDER BY row_label, total_weight DESC
    """)
    result = await db.execute(sql, {"org_id": org_id})
    return result.all()
