"""Keyset query builders for Discovery FCL lists.

Col1 (managers) is aggregated on top of ``mv_unified_funds`` and joined
to ``sec_managers`` so AUM ordering comes from the reported Form ADV
figure rather than the sum of fund-level AUMs (which is noisy for
private funds). Keyset pagination uses the composite key
``(sm.aum_total, g.manager_id)`` sorted ``DESC NULLS LAST, ASC``.

Col2 (funds) is a direct keyset over ``mv_unified_funds`` keyed on
``(aum_usd, external_id)`` with the same ordering.

Both queries are parameterized for SQLAlchemy ``text()`` and return the
raw SQL + parameter dict so the route layer can apply RLS/caching.
"""

from __future__ import annotations

from typing import Any

from app.domains.wealth.schemas.discovery import (
    DiscoveryFilters,
    FundCursor,
    ManagerCursor,
)


def build_managers_query(
    filters: DiscoveryFilters,
    cursor: ManagerCursor | None,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    """Build the Col1 managers query with keyset pagination.

    The outer SELECT joins against ``sec_managers`` so the caller gets
    the authoritative firm name + AUM. The ``region`` filter is applied
    at the inner ``filtered`` CTE because the heuristic
    (``manager_id`` looks like a CRD integer for US managers) is cheap
    to evaluate on that narrow projection.
    """
    params: dict[str, Any] = {
        "strategies": filters.strategies,
        "geos": filters.geographies,
        "fund_types": filters.fund_types,
        "min_aum": filters.min_aum_usd,
        "max_er": filters.max_expense_ratio_pct,
        "cursor_aum": cursor.aum if cursor else None,
        "cursor_id": cursor.crd if cursor else None,
        "limit": limit,
    }
    region_clause = ""
    if filters.region == "US":
        region_clause = "AND f.manager_id ~ '^[0-9]+$'"
    elif filters.region == "EU":
        region_clause = "AND (f.manager_id IS NULL OR f.manager_id !~ '^[0-9]+$')"

    sql = f"""
    WITH filtered AS (
        SELECT manager_id, manager_name, series_id, external_id,
               ticker, fund_type, aum_usd, strategy_label,
               investment_geography, expense_ratio_pct
        FROM mv_unified_funds f
        WHERE manager_id IS NOT NULL
          {region_clause}
          AND (CAST(:strategies AS text[]) IS NULL OR strategy_label = ANY(CAST(:strategies AS text[])))
          AND (CAST(:geos AS text[]) IS NULL OR investment_geography = ANY(CAST(:geos AS text[])))
          AND (CAST(:fund_types AS text[]) IS NULL OR fund_type = ANY(CAST(:fund_types AS text[])))
          AND (CAST(:min_aum AS numeric) IS NULL OR aum_usd >= CAST(:min_aum AS numeric))
          AND (CAST(:max_er AS numeric) IS NULL OR expense_ratio_pct <= CAST(:max_er AS numeric))
    ), grouped AS (
        SELECT
            f.manager_id,
            MAX(f.manager_name) AS manager_name,
            COUNT(DISTINCT COALESCE(f.series_id, f.external_id)) AS fund_count,
            ARRAY_AGG(DISTINCT f.fund_type) FILTER (WHERE f.fund_type IS NOT NULL) AS fund_types,
            MODE() WITHIN GROUP (ORDER BY f.strategy_label) AS strategy_label_top
        FROM filtered f
        GROUP BY f.manager_id
    )
    SELECT
        g.manager_id,
        COALESCE(g.manager_name, sm.firm_name, g.manager_id) AS manager_name,
        g.fund_count,
        COALESCE(g.fund_types, ARRAY[]::text[]) AS fund_types,
        g.strategy_label_top,
        sm.aum_total,
        sm.firm_name,
        sm.cik
    FROM grouped g
    LEFT JOIN sec_managers sm ON g.manager_id = sm.crd_number
    WHERE (
        CAST(:cursor_aum AS numeric) IS NULL
        OR (sm.aum_total, g.manager_id) < (CAST(:cursor_aum AS numeric), CAST(:cursor_id AS text))
    )
    ORDER BY sm.aum_total DESC NULLS LAST, g.manager_id ASC
    LIMIT :limit
    """
    return sql, params


def build_funds_query(
    manager_id: str,
    cursor: FundCursor | None,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    """Build the Col2 funds-by-manager query with keyset pagination."""
    params: dict[str, Any] = {
        "manager_id": manager_id,
        "cursor_aum": cursor.aum if cursor else None,
        "cursor_ext": cursor.external_id if cursor else None,
        "limit": limit,
    }
    sql = """
    SELECT
        external_id, universe, name, ticker, isin,
        fund_type, strategy_label, aum_usd, currency, domicile,
        series_id, has_holdings, has_nav,
        expense_ratio_pct, avg_annual_return_1y, avg_annual_return_10y
    FROM mv_unified_funds
    WHERE manager_id = :manager_id
      AND (
          CAST(:cursor_aum AS numeric) IS NULL
          OR (aum_usd, external_id) < (CAST(:cursor_aum AS numeric), CAST(:cursor_ext AS text))
      )
    ORDER BY aum_usd DESC NULLS LAST, external_id ASC
    LIMIT :limit
    """
    return sql, params
