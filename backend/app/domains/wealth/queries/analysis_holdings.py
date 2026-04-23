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
  ``market_value``, ``series_id`` (nullable — migration 0059+).
* ``sec_13f_holdings``: ``cik`` (NOT ``filer_cik``), ``report_date``, ``cusip``,
  ``issuer_name``, ``market_value`` (NOT ``value``).
* ``sec_managers``: PK is ``crd_number`` — the foreign ``cik`` column is
  nullable but used to join 13F filers back to firm names.

Branch #1 fix: ``fetch_top_holdings`` and ``fetch_style_drift`` now
accept an optional ``series_id`` filter so umbrella-trust CIKs (e.g.
Invesco CIK 277751 with 49 series, BlackRock with 343) don't melt into
a cross-series top-25. When ``series_id`` is supplied, the SQL is
branched at construction time — we do NOT use a ``:param IS NULL OR``
predicate because asyncpg/SQLAlchemy mis-renders the inline ``::text``
cast when the same bind appears twice.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_top_holdings(
    db: AsyncSession,
    cik: str,
    series_id: str | None = None,
) -> dict[str, Any]:
    """Top 25 positions + sector breakdown from the latest N-PORT report.

    Args:
        db: Async SQLAlchemy session (RLS not required — table is global).
        cik: Fund CIK (matches ``sec_nport_holdings.cik``).
        series_id: Optional series_id to filter umbrella-trust CIKs.
            When non-null, adds ``AND series_id = :series_id`` to each
            query and narrows the result to a single series within the
            CIK. When null, behavior is unchanged (back-compat).

    Returns:
        ``{"top_holdings": [...], "sector_breakdown": [...], "as_of": date|None}``.
        Lists are empty when no N-PORT filing exists for the CIK/series.
    """
    # Branch SQL at construction time so we never ship a bound param
    # twice with an inline cast (asyncpg + SQLAlchemy mis-render that).
    series_clause = "AND series_id = :series_id" if series_id else ""
    params: dict[str, Any] = {"cik": cik}
    if series_id:
        params["series_id"] = series_id

    as_of_sql = text(
        f"""
        SELECT MAX(report_date) AS as_of
        FROM sec_nport_holdings
        WHERE cik = :cik
          {series_clause}
        """,  # noqa: S608 — series_clause is a static literal, not user input
    )
    as_of_row = (await db.execute(as_of_sql, params)).mappings().first()
    as_of = as_of_row["as_of"] if as_of_row else None

    if as_of is None:
        return {"top_holdings": [], "sector_breakdown": [], "as_of": None}

    params_dated = {**params, "as_of": as_of}

    top_sql = text(
        f"""
        SELECT
            issuer_name,
            cusip,
            COALESCE(sector, 'Unknown') AS sector,
            pct_of_nav,
            market_value
        FROM sec_nport_holdings
        WHERE cik = :cik
          AND report_date = :as_of
          {series_clause}
        ORDER BY pct_of_nav DESC NULLS LAST
        LIMIT 25
        """,  # noqa: S608
    )
    top_rows = (await db.execute(top_sql, params_dated)).mappings().all()

    sector_sql = text(
        f"""
        SELECT
            COALESCE(sector, 'Unknown') AS sector,
            SUM(pct_of_nav) AS weight,
            COUNT(*) AS holdings_count
        FROM sec_nport_holdings
        WHERE cik = :cik
          AND report_date = :as_of
          {series_clause}
        GROUP BY COALESCE(sector, 'Unknown')
        ORDER BY weight DESC NULLS LAST
        """,  # noqa: S608
    )
    sector_rows = (await db.execute(sector_sql, params_dated)).mappings().all()

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
    db: AsyncSession,
    cik: str,
    quarters: int = 8,
    series_id: str | None = None,
) -> dict[str, Any]:
    """Sector weight history across the last ``quarters`` N-PORT reports.

    Args:
        db: Async SQLAlchemy session.
        cik: Fund CIK.
        quarters: Number of N-PORT reports to walk back.
        series_id: Optional series_id filter for umbrella trusts — see
            :func:`fetch_top_holdings` for rationale.
    """
    series_clause_inner = "AND series_id = :series_id" if series_id else ""
    series_clause_outer = "AND h.series_id = :series_id" if series_id else ""
    params: dict[str, Any] = {"cik": cik, "quarters": quarters}
    if series_id:
        params["series_id"] = series_id

    sql = text(
        f"""
        WITH q AS (
            SELECT DISTINCT report_date
            FROM sec_nport_holdings
            WHERE cik = :cik
              {series_clause_inner}
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
          {series_clause_outer}
        GROUP BY h.report_date, COALESCE(h.sector, 'Unknown')
        ORDER BY h.report_date ASC, weight DESC NULLS LAST
        """,  # noqa: S608
    )
    rows = (await db.execute(sql, params)).mappings().all()

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
            CASE
                WHEN c.source = 'nport' THEN COALESCE(rf.fund_name, m.firm_name, 'Fund ' || RIGHT(c.holder_cik, 6))
                ELSE COALESCE(m.firm_name, rf.fund_name, 'Manager ' || RIGHT(c.holder_cik, 6))
            END AS holder_name
        FROM combined c
        LEFT JOIN sec_managers m ON m.cik = c.holder_cik
        LEFT JOIN sec_registered_funds rf ON rf.cik = c.holder_cik
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
        holder_name = r["holder_name"] or f"Holder {str(holder_cik)[-6:]}"
        position_value = (
            int(r["position_value"]) if r["position_value"] is not None else None
        )
        nodes.append(
            {
                "id": holder_cik,
                "name": holder_name,
                "category": "holder",
                "symbolSize": 16,
                "value": position_value,
                "source": r["source"],
            },
        )
        edges.append({"source": holder_cik, "target": target_cusip})

    return {"nodes": nodes, "edges": edges, "target_cusip": target_cusip}
