"""Holdings analytics for the Discovery Analysis page (Phase 6).

DB-only hot path. Reads from global SEC tables (``sec_nport_holdings``,
``sec_13f_holdings``, ``sec_managers``) which carry no ``organization_id``
and no RLS policy.

Three query functions back the Analysis page Holdings view:

* :func:`fetch_top_holdings` — top 25 positions of a fund (by CIK) plus
  sector breakdown derived from the latest N-PORT report date.
* :func:`fetch_style_drift` — quarter-over-quarter sector weight history.
* :func:`fetch_reverse_lookup` — given a CUSIP, who holds it (NPORT funds
  + 13F filers), used to render the network/Sankey on the Analysis page.

Schema notes (verified against ``backend/app/shared/models.py``):

* ``sec_nport_holdings``: ``cik``, ``report_date``, ``cusip``, ``issuer_name``,
  ``sector`` (NOT ``security_type``), ``pct_of_nav`` (NOT ``percent_value``),
  ``market_value``.
* ``sec_13f_holdings``: ``cik`` (NOT ``filer_cik``), ``report_date``, ``cusip``,
  ``issuer_name``, ``market_value`` (NOT ``value``).
* ``sec_managers``: PK is ``crd_number`` — the foreign ``cik`` column is
  nullable but used to join 13F filers back to firm names.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_top_holdings(db: AsyncSession, cik: str) -> dict[str, Any]:
    """Top 25 positions + sector breakdown from the latest N-PORT report.

    Args:
        db: Async SQLAlchemy session (RLS not required — table is global).
        cik: Fund CIK (matches ``sec_nport_holdings.cik``).

    Returns:
        ``{"top_holdings": [...], "sector_breakdown": [...], "as_of": date|None}``.
        Lists are empty when no N-PORT filing exists for the CIK.
    """
    as_of_sql = text(
        """
        SELECT MAX(report_date) AS as_of
        FROM sec_nport_holdings
        WHERE cik = :cik
        """,
    )
    as_of_row = (await db.execute(as_of_sql, {"cik": cik})).mappings().first()
    as_of = as_of_row["as_of"] if as_of_row else None

    if as_of is None:
        return {"top_holdings": [], "sector_breakdown": [], "as_of": None}

    top_sql = text(
        """
        SELECT
            issuer_name,
            cusip,
            COALESCE(sector, 'Unknown') AS sector,
            pct_of_nav,
            market_value
        FROM sec_nport_holdings
        WHERE cik = :cik
          AND report_date = :as_of
        ORDER BY pct_of_nav DESC NULLS LAST
        LIMIT 25
        """,
    )
    top_rows = (
        await db.execute(top_sql, {"cik": cik, "as_of": as_of})
    ).mappings().all()

    sector_sql = text(
        """
        SELECT
            COALESCE(sector, 'Unknown') AS sector,
            SUM(pct_of_nav) AS weight,
            COUNT(*) AS holdings_count
        FROM sec_nport_holdings
        WHERE cik = :cik
          AND report_date = :as_of
        GROUP BY COALESCE(sector, 'Unknown')
        ORDER BY weight DESC NULLS LAST
        """,
    )
    sector_rows = (
        await db.execute(sector_sql, {"cik": cik, "as_of": as_of})
    ).mappings().all()

    return {
        "top_holdings": [
            {
                "issuer_name": r["issuer_name"],
                "cusip": r["cusip"],
                "sector": r["sector"],
                "weight": float(r["pct_of_nav"]) if r["pct_of_nav"] is not None else None,
                "market_value": int(r["market_value"]) if r["market_value"] is not None else None,
            }
            for r in top_rows
        ],
        "sector_breakdown": [
            {
                "name": r["sector"],
                "weight": float(r["weight"]) if r["weight"] is not None else None,
                "holdings_count": int(r["holdings_count"]),
            }
            for r in sector_rows
        ],
        "as_of": as_of,
    }


async def fetch_style_drift(
    db: AsyncSession, cik: str, quarters: int = 8,
) -> dict[str, Any]:
    """Sector weight history across the last ``quarters`` N-PORT reports."""
    sql = text(
        """
        WITH q AS (
            SELECT DISTINCT report_date
            FROM sec_nport_holdings
            WHERE cik = :cik
            ORDER BY report_date DESC
            LIMIT :quarters
        )
        SELECT
            h.report_date,
            COALESCE(h.sector, 'Unknown') AS sector,
            SUM(h.pct_of_nav) AS weight
        FROM sec_nport_holdings h
        JOIN q ON q.report_date = h.report_date
        WHERE h.cik = :cik
        GROUP BY h.report_date, COALESCE(h.sector, 'Unknown')
        ORDER BY h.report_date ASC, weight DESC NULLS LAST
        """,
    )
    rows = (
        await db.execute(sql, {"cik": cik, "quarters": quarters})
    ).mappings().all()

    snapshots: list[dict[str, Any]] = []
    current_quarter = None
    current_sectors: list[dict[str, Any]] = []
    for r in rows:
        rd = r["report_date"]
        if rd != current_quarter:
            if current_quarter is not None:
                snapshots.append({"quarter": current_quarter, "sectors": current_sectors})
            current_quarter = rd
            current_sectors = []
        current_sectors.append(
            {
                "name": r["sector"],
                "weight": float(r["weight"]) if r["weight"] is not None else None,
            },
        )
    if current_quarter is not None:
        snapshots.append({"quarter": current_quarter, "sectors": current_sectors})

    return {"snapshots": snapshots}


async def fetch_reverse_lookup(
    db: AsyncSession, target_cusip: str, limit: int = 30,
) -> dict[str, Any]:
    """Given a CUSIP, list NPORT funds + 13F filers holding it (latest report)."""
    name_sql = text(
        """
        SELECT COALESCE(
            (SELECT issuer_name FROM sec_nport_holdings WHERE cusip = :cusip LIMIT 1),
            (SELECT issuer_name FROM sec_13f_holdings WHERE cusip = :cusip LIMIT 1)
        ) AS issuer_name
        """,
    )
    name_row = (
        await db.execute(name_sql, {"cusip": target_cusip})
    ).mappings().first()
    target_name = (name_row["issuer_name"] if name_row else None) or target_cusip

    holders_sql = text(
        """
        WITH nport_latest AS (
            SELECT cik, MAX(report_date) AS rd
            FROM sec_nport_holdings
            WHERE cusip = :cusip
            GROUP BY cik
        ),
        nport_holders AS (
            SELECT
                h.cik AS holder_cik,
                SUM(h.market_value) AS position_value,
                'nport'::text AS source
            FROM sec_nport_holdings h
            JOIN nport_latest nl ON nl.cik = h.cik AND nl.rd = h.report_date
            WHERE h.cusip = :cusip
            GROUP BY h.cik
        ),
        thirteenf_latest AS (
            SELECT cik, MAX(report_date) AS rd
            FROM sec_13f_holdings
            WHERE cusip = :cusip
            GROUP BY cik
        ),
        thirteenf_holders AS (
            SELECT
                h.cik AS holder_cik,
                SUM(h.market_value) AS position_value,
                '13f'::text AS source
            FROM sec_13f_holdings h
            JOIN thirteenf_latest tl ON tl.cik = h.cik AND tl.rd = h.report_date
            WHERE h.cusip = :cusip
            GROUP BY h.cik
        ),
        combined AS (
            SELECT * FROM nport_holders
            UNION ALL
            SELECT * FROM thirteenf_holders
        )
        SELECT
            c.holder_cik,
            c.position_value,
            c.source,
            m.firm_name
        FROM combined c
        LEFT JOIN sec_managers m ON m.cik = c.holder_cik
        ORDER BY c.position_value DESC NULLS LAST
        LIMIT :limit
        """,
    )
    holder_rows = (
        await db.execute(holders_sql, {"cusip": target_cusip, "limit": limit})
    ).mappings().all()

    nodes: list[dict[str, Any]] = [
        {
            "id": target_cusip,
            "name": target_name,
            "category": "holding",
            "symbolSize": 40,
        },
    ]
    edges: list[dict[str, Any]] = []
    for r in holder_rows:
        holder_cik = r["holder_cik"]
        firm_name = r["firm_name"] or f"CIK {holder_cik}"
        position_value = (
            int(r["position_value"]) if r["position_value"] is not None else None
        )
        nodes.append(
            {
                "id": holder_cik,
                "name": firm_name,
                "category": "holder",
                "symbolSize": 16,
                "value": position_value,
                "source": r["source"],
            },
        )
        edges.append({"source": holder_cik, "target": target_cusip})

    return {"nodes": nodes, "edges": edges, "target_cusip": target_cusip}
