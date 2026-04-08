"""Unit tests for Discovery FCL keyset query builders.

Pure unit tests — no database. Verifies SQL shape + param bindings so
regressions in the cursor encoding or filter plumbing get caught before
they reach integration.
"""

from __future__ import annotations

from app.domains.wealth.queries.discovery_keyset import (
    build_funds_query,
    build_managers_query,
)
from app.domains.wealth.schemas.discovery import (
    DiscoveryFilters,
    FundCursor,
    ManagerCursor,
)


def test_managers_query_no_cursor_no_filters() -> None:
    sql, params = build_managers_query(DiscoveryFilters(), cursor=None, limit=50)
    assert "ORDER BY sm.aum_total DESC NULLS LAST" in sql
    assert "LIMIT" in sql
    assert params["limit"] == 50
    assert params["cursor_aum"] is None


def test_managers_query_with_strategy_filter() -> None:
    sql, params = build_managers_query(
        DiscoveryFilters(strategies=["Private Credit", "Buyout"]),
        cursor=None,
        limit=50,
    )
    assert "strategy_label = ANY" in sql
    assert params["strategies"] == ["Private Credit", "Buyout"]


def test_managers_query_with_keyset_cursor() -> None:
    sql, params = build_managers_query(
        DiscoveryFilters(),
        cursor=ManagerCursor(aum=500_000_000, crd="123456"),
        limit=50,
    )
    assert "(sm.aum_total, g.manager_id) <" in sql
    assert params["cursor_aum"] == 500_000_000
    assert params["cursor_id"] == "123456"


def test_funds_query_by_manager_aum_sort() -> None:
    sql, params = build_funds_query(
        manager_id="123456", cursor=None, limit=50,
    )
    assert "WHERE manager_id = :manager_id" in sql
    assert "ORDER BY aum_usd DESC NULLS LAST" in sql
    assert params["manager_id"] == "123456"


def test_funds_query_with_cursor() -> None:
    sql, params = build_funds_query(
        manager_id="123456",
        cursor=FundCursor(aum=100_000_000, external_id="S000012345"),
        limit=25,
    )
    assert "(aum_usd, external_id) <" in sql
    assert params["cursor_aum"] == 100_000_000
    assert params["cursor_ext"] == "S000012345"
    assert params["limit"] == 25
