"""Resolve a Discovery ``external_id`` to the tenant-scoped instrument.

Discovery's Col2 rows carry ``external_id`` (the ``mv_unified_funds``
primary key — a class_id/series_id/CIK/UUID/ISIN depending on the
universe branch). Downstream analytics — DD reports, risk metrics,
fact sheets — are keyed by the Wealth ``instrument_id`` catalog UUID.

``resolve_fund`` performs the bridge in a single round trip and
returns a dict suitable for re-use across Col3 and the standalone
Analysis page (Phase 5+). Missing instruments are returned with
``instrument_id = None`` so callers can decide whether a fund lives
only in the global catalog (no per-org data yet) or has been imported.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_fund(db: AsyncSession, external_id: str) -> dict[str, Any]:
    """Resolve a Discovery external_id → (instrument_id, cik, universe)."""
    mv_sql = """
        SELECT external_id, universe, ticker, series_id, name
        FROM mv_unified_funds
        WHERE external_id = :id
        LIMIT 1
    """
    mv_row = (
        await db.execute(text(mv_sql), {"id": external_id})
    ).mappings().first()
    if mv_row is None:
        raise HTTPException(status_code=404, detail=f"fund {external_id} not found")

    inst_sql = """
        SELECT instrument_id, attributes->>'sec_cik' AS cik
        FROM instruments_universe
        WHERE
            (:ticker::text IS NOT NULL AND ticker = :ticker)
            OR (:sid::text IS NOT NULL AND attributes->>'series_id' = :sid)
        ORDER BY ticker NULLS LAST
        LIMIT 1
    """
    inst_row = (
        await db.execute(
            text(inst_sql),
            {"ticker": mv_row["ticker"], "sid": mv_row["series_id"]},
        )
    ).mappings().first()

    return {
        "external_id": external_id,
        "universe": mv_row["universe"],
        "name": mv_row["name"],
        "ticker": mv_row["ticker"],
        "series_id": mv_row["series_id"],
        "instrument_id": inst_row["instrument_id"] if inst_row else None,
        "cik": inst_row["cik"] if inst_row else None,
    }
