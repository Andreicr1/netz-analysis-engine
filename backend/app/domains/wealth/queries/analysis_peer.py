"""Peer comparison + institutional reveal queries for Discovery Analysis (Phase 7).

DB-only hot path. Reads from global tables (no ``organization_id`` filter):

* ``mv_unified_funds`` — polymorphic fund catalog (external_id, ticker, strategy_label,
  aum_usd, expense_ratio_pct).
* ``instruments_universe`` — bridge between ticker and ``instrument_id`` used by
  ``fund_risk_metrics``.
* ``fund_risk_metrics`` — global risk metrics hypertable, multi-row per instrument
  by ``calc_date``; we read the latest row via DISTINCT ON.
* ``sec_nport_holdings`` — subject fund holdings (cik, report_date, cusip,
  issuer_name, pct_of_nav).
* ``sec_13f_holdings`` — 13F filers' positions (cik, report_date, cusip,
  market_value). Column is ``cik`` (not ``filer_cik``).
* ``curated_institutions`` — manual seed of endowments, family offices,
  foundations, sovereign funds (added by migration 0097).

Schema deviations from plan (documented):

* ``fund_risk_metrics`` uses ``cvar_95_12m`` (numeric(10,6)), not ``cvar_95``.
* Multiple calc_dates per instrument → DISTINCT ON (instrument_id) ORDER BY
  calc_date DESC to pick the latest row.
* Subject fund strategy is resolved by the route before calling
  :func:`fetch_peer_comparison`, so the query accepts ``strategy`` directly.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_peer_comparison(
    db: AsyncSession,
    subject_external_id: str,
    strategy: str | None,
    limit: int = 40,
) -> dict[str, Any]:
    """Return peers sharing the subject's ``strategy_label`` plus risk metrics.

    Args:
        db: Async SQLAlchemy session.
        subject_external_id: ``mv_unified_funds.external_id`` of the subject fund.
        strategy: Strategy label to filter peers by; ``None`` means no strategy
            filter (return any fund with risk metrics).
        limit: Max peers returned (subject is guaranteed to appear when it has
            metrics and matches the filter).

    Returns:
        ``{"peers": [...], "subject": dict|None}``. ``is_subject`` flag on each
        peer row lets the frontend highlight the subject. Sorted so the subject
        is first, then by Sharpe descending.
    """
    sql = """
        SELECT
            f.external_id,
            f.name,
            f.ticker,
            f.strategy_label,
            f.aum_usd,
            f.expense_ratio_pct,
            rm.volatility_1y,
            rm.sharpe_1y,
            rm.max_drawdown_1y,
            rm.cvar_95_12m AS cvar_95,
            (f.external_id = :subject_ext) AS is_subject
        FROM mv_unified_funds f
        LEFT JOIN instruments_universe i ON i.ticker = f.ticker
        LEFT JOIN LATERAL (
            SELECT volatility_1y, sharpe_1y, max_drawdown_1y, cvar_95_12m
            FROM fund_risk_metrics
            WHERE instrument_id = i.instrument_id
            ORDER BY calc_date DESC
            LIMIT 1
        ) rm ON TRUE
        WHERE (CAST(:strategy AS text) IS NULL OR f.strategy_label = CAST(:strategy AS text))
          AND f.aum_usd IS NOT NULL
          AND rm.volatility_1y IS NOT NULL
        ORDER BY (f.external_id = :subject_ext) DESC, rm.sharpe_1y DESC NULLS LAST
        LIMIT :limit
    """
    rows = (
        await db.execute(
            text(sql),
            {
                "strategy": strategy,
                "subject_ext": subject_external_id,
                "limit": limit,
            },
        )
    ).mappings().all()

    def _row(r: Any) -> dict[str, Any]:
        return {
            "external_id": r["external_id"],
            "name": r["name"],
            "ticker": r["ticker"],
            "strategy_label": r["strategy_label"],
            "aum_usd": float(r["aum_usd"]) if r["aum_usd"] is not None else None,
            "expense_ratio_pct": (
                float(r["expense_ratio_pct"])
                if r["expense_ratio_pct"] is not None
                else None
            ),
            "volatility_1y": (
                float(r["volatility_1y"]) if r["volatility_1y"] is not None else None
            ),
            "sharpe_1y": (
                float(r["sharpe_1y"]) if r["sharpe_1y"] is not None else None
            ),
            "max_drawdown_1y": (
                float(r["max_drawdown_1y"])
                if r["max_drawdown_1y"] is not None
                else None
            ),
            "cvar_95": float(r["cvar_95"]) if r["cvar_95"] is not None else None,
            "is_subject": bool(r["is_subject"]),
        }

    peers = [_row(r) for r in rows]
    subject = next((p for p in peers if p["is_subject"]), None)
    return {"peers": peers, "subject": subject}


async def fetch_institutional_reveal(
    db: AsyncSession,
    fund_cik: str,
    category_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Cross-reference subject fund's top holdings against curated institutions.

    Steps:
      1. Pull top 25 CUSIPs from subject's latest ``sec_nport_holdings`` report
         (by ``pct_of_nav``).
      2. Load active curated institutions with ``cik IS NOT NULL`` (optionally
         filtered by category).
      3. For each institution × subject-cusip, sum ``market_value`` in that
         institution's latest 13F report.
      4. Compose overlap_matrix + per-institution totals.

    Graceful degradation:

    * No N-PORT filings for the fund → ``{"institutions": [], "overlap_matrix":
      {}, "holdings": []}``.
    * No curated institutions with CIK (backfill not run) → still return the
      ``holdings`` list so the UI can render the subject side of the matrix.
    """
    holdings_sql = text(
        """
        WITH latest AS (
            SELECT MAX(report_date) AS rd
            FROM sec_nport_holdings
            WHERE cik = :cik
        )
        SELECT cusip, issuer_name, pct_of_nav
        FROM sec_nport_holdings
        WHERE cik = :cik
          AND report_date = (SELECT rd FROM latest)
          AND cusip IS NOT NULL
        ORDER BY pct_of_nav DESC NULLS LAST
        LIMIT 25
        """,
    )
    holding_rows = (
        await db.execute(holdings_sql, {"cik": fund_cik})
    ).mappings().all()

    holdings = [
        {
            "cusip": r["cusip"],
            "issuer_name": r["issuer_name"],
            "pct_of_nav": (
                float(r["pct_of_nav"]) if r["pct_of_nav"] is not None else None
            ),
        }
        for r in holding_rows
    ]

    if not holdings:
        return {"institutions": [], "overlap_matrix": {}, "holdings": []}

    inst_sql = text(
        """
        SELECT institution_id, name, cik, category, country, display_order
        FROM curated_institutions
        WHERE active = TRUE
          AND cik IS NOT NULL
          AND (
              CAST(:cats AS text[]) IS NULL
              OR category = ANY(CAST(:cats AS text[]))
          )
        ORDER BY display_order ASC
        """,
    )
    inst_rows = (
        await db.execute(inst_sql, {"cats": category_filter})
    ).mappings().all()

    if not inst_rows:
        return {
            "institutions": [],
            "overlap_matrix": {},
            "holdings": holdings,
        }

    target_cusips = [h["cusip"] for h in holdings]
    institution_ciks = [r["cik"] for r in inst_rows]

    overlap_sql = text(
        """
        WITH latest AS (
            SELECT cik, MAX(report_date) AS rd
            FROM sec_13f_holdings
            WHERE cik = ANY(CAST(:inst_ciks AS text[]))
            GROUP BY cik
        )
        SELECT
            h.cik AS inst_cik,
            h.cusip,
            SUM(h.market_value) AS position_value
        FROM sec_13f_holdings h
        JOIN latest l ON l.cik = h.cik AND l.rd = h.report_date
        WHERE h.cik = ANY(CAST(:inst_ciks AS text[]))
          AND h.cusip = ANY(CAST(:target_cusips AS text[]))
        GROUP BY h.cik, h.cusip
        """,
    )
    overlap_rows = (
        await db.execute(
            overlap_sql,
            {"inst_ciks": institution_ciks, "target_cusips": target_cusips},
        )
    ).mappings().all()

    # overlap_matrix: {institution_id: {cusip: position_value}}
    cik_to_inst_id = {r["cik"]: r["institution_id"] for r in inst_rows}
    overlap_matrix: dict[str, dict[str, int]] = {}
    for r in overlap_rows:
        inst_id = cik_to_inst_id.get(r["inst_cik"])
        if inst_id is None:
            continue
        pv = r["position_value"]
        overlap_matrix.setdefault(inst_id, {})[r["cusip"]] = (
            int(pv) if pv is not None else 0
        )

    institutions: list[dict[str, Any]] = []
    for r in inst_rows:
        inst_id = r["institution_id"]
        matrix_row = overlap_matrix.get(inst_id, {})
        total_value = sum(matrix_row.values()) if matrix_row else 0
        institutions.append(
            {
                "institution_id": inst_id,
                "name": r["name"],
                "cik": r["cik"],
                "category": r["category"],
                "country": r["country"],
                "total_overlap": len(matrix_row),
                "total_value": total_value,
            },
        )

    return {
        "institutions": institutions,
        "overlap_matrix": overlap_matrix,
        "holdings": holdings,
    }
