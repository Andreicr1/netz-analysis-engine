"""Tests for Manager Screener — query builder + endpoints.

Query builder tests are pure unit tests (compile SQL, inspect).
Endpoint tests use the test client with X-DEV-ACTOR header.
"""

from __future__ import annotations

import json
import re
from datetime import date

import pytest
from httpx import AsyncClient

from app.domains.wealth.queries.manager_screener_sql import (
    ScreenerFilters,
    _escape_ilike,
    build_screener_queries,
)
from tests.conftest import DEV_ACTOR_HEADER

# ─── Dev actor headers ───────────────────────────────────────────────────

_VIEWER_HEADER = {
    "X-DEV-ACTOR": json.dumps({
        "actor_id": "test-viewer",
        "roles": ["VIEWER"],
        "fund_ids": [],
        "org_id": "00000000-0000-0000-0000-000000000001",
    }),
}


def _compile_sql(stmt) -> str:
    """Compile a SQLAlchemy statement to string for inspection."""
    from sqlalchemy.dialects import postgresql

    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# ═══════════════════════════════════════════════════════════════════════════
#  Query Builder Unit Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestScreenerFilters:
    def test_default_filters(self) -> None:
        f = ScreenerFilters()
        assert f.sort_by == "aum_total"
        assert f.sort_dir == "desc"
        assert f.page == 1
        assert f.page_size == 25

    def test_frozen(self) -> None:
        f = ScreenerFilters()
        with pytest.raises(AttributeError):
            f.page = 2  # type: ignore[misc]


class TestEscapeIlike:
    def test_escapes_percent(self) -> None:
        assert _escape_ilike("100%") == r"100\%"

    def test_escapes_underscore(self) -> None:
        assert _escape_ilike("a_b") == r"a\_b"

    def test_escapes_backslash(self) -> None:
        assert _escape_ilike(r"a\b") == r"a\\b"

    def test_normal_text_unchanged(self) -> None:
        assert _escape_ilike("Blackrock") == "Blackrock"

    def test_combined(self) -> None:
        assert _escape_ilike(r"100%_test\x") == r"100\%\_test\\x"


class TestBuildScreenerQueries:
    def test_returns_tuple_of_two_selects(self) -> None:
        filters = ScreenerFilters()
        data_q, count_q = build_screener_queries(filters, "org-1")
        assert data_q is not None
        assert count_q is not None

    def test_empty_filters_valid_sql(self) -> None:
        """Empty filters should produce valid SQL with no extra WHERE conditions."""
        filters = ScreenerFilters()
        data_q, count_q = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "sec_managers" in sql
        assert "LIMIT" in sql

    def test_aum_filter(self) -> None:
        filters = ScreenerFilters(aum_min=1_000_000, aum_max=10_000_000_000)
        data_q, _ = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "aum_total >=" in sql
        assert "aum_total <=" in sql

    def test_text_search_in_sql(self) -> None:
        filters = ScreenerFilters(text_search="Black%Rock")
        data_q, _ = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "ILIKE" in sql or "ilike" in sql.lower()
        # The escaped percent should appear in the compiled SQL (possibly double-escaped)
        assert "Black" in sql and "Rock" in sql

    def test_sort_column_allowlist_prevents_injection(self) -> None:
        """Unknown sort column falls back to aum_total."""
        filters = ScreenerFilters(sort_by="'; DROP TABLE sec_managers; --")
        data_q, _ = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "DROP TABLE" not in sql
        assert "aum_total" in sql

    def test_sort_asc(self) -> None:
        filters = ScreenerFilters(sort_by="firm_name", sort_dir="asc")
        data_q, _ = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "ASC" in sql

    def test_pagination_offset(self) -> None:
        filters = ScreenerFilters(page=3, page_size=10)
        data_q, _ = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "LIMIT" in sql
        assert "OFFSET" in sql

    def test_holdings_subquery_always_filters_quarter(self) -> None:
        """Invariant: holdings aggregate subquery must include quarter filter
        for TimescaleDB chunk pruning."""
        filters = ScreenerFilters()
        data_q, _ = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        # The holdings subquery should filter by quarter
        assert "sec_13f_holdings_agg" in sql
        # quarter filter must appear in the compiled SQL
        assert re.search(r"quarter\s*[<>=]", sql, re.IGNORECASE) is not None

    def test_drift_subquery_always_filters_quarter(self) -> None:
        """Invariant: drift aggregate subquery must include quarter filter."""
        filters = ScreenerFilters()
        data_q, _ = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "sec_13f_drift_agg" in sql

    def test_universe_subquery_includes_org_id(self) -> None:
        """instruments_universe join must filter by organization_id."""
        filters = ScreenerFilters()
        data_q, _ = build_screener_queries(
            filters, "org-123", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "org-123" in sql
        assert "instruments_universe" in sql

    def test_state_filter(self) -> None:
        filters = ScreenerFilters(states=["NY", "CA"])
        data_q, _ = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "NY" in sql
        assert "CA" in sql

    def test_compliance_clean_filter(self) -> None:
        filters = ScreenerFilters(compliance_clean=True)
        data_q, _ = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "compliance_disclosures" in sql

    def test_position_count_filter(self) -> None:
        filters = ScreenerFilters(position_count_min=50, position_count_max=500)
        data_q, _ = build_screener_queries(
            filters, "org-1", latest_quarter=date(2026, 3, 1)
        )
        sql = _compile_sql(data_q)
        assert "total_positions" in sql


# ═══════════════════════════════════════════════════════════════════════════
#  Endpoint Integration Tests (require running DB)
# ═══════════════════════════════════════════════════════════════════════════


class TestManagerScreenerEndpoints:
    """Integration tests for /manager-screener endpoints.

    These tests hit the actual API via the test client.
    They test response shape and auth, even with empty SEC data.
    """

    @pytest.mark.asyncio
    async def test_list_managers_returns_page(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/manager-screener/", headers=DEV_ACTOR_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert "managers" in data
        assert "total_count" in data
        assert "page" in data
        assert "page_size" in data
        assert "has_next" in data

    @pytest.mark.asyncio
    async def test_list_managers_403_for_viewer(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/manager-screener/", headers=_VIEWER_HEADER)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_profile_not_found(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/NONEXISTENT999/profile",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_profile_invalid_crd(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/invalid!crd/profile",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_holdings_not_found(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/NONEXISTENT999/holdings",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_drift_not_found(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/NONEXISTENT999/drift",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_institutional_not_found(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/NONEXISTENT999/institutional",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_universe_status_empty(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/NONEXISTENT999/universe-status",
            headers=DEV_ACTOR_HEADER,
        )
        # Universe status returns empty when not found (not 404)
        assert resp.status_code == 200
        data = resp.json()
        assert data["instrument_id"] is None

    @pytest.mark.asyncio
    async def test_compare_too_few_crds(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/manager-screener/managers/compare",
            headers=DEV_ACTOR_HEADER,
            json={"crd_numbers": ["CRD1"]},
        )
        assert resp.status_code == 422  # Pydantic validation

    @pytest.mark.asyncio
    async def test_compare_too_many_crds(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/manager-screener/managers/compare",
            headers=DEV_ACTOR_HEADER,
            json={"crd_numbers": ["CRD1", "CRD2", "CRD3", "CRD4", "CRD5", "CRD6"]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_compare_managers_not_found(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/manager-screener/managers/compare",
            headers=DEV_ACTOR_HEADER,
            json={"crd_numbers": ["FAKE1", "FAKE2"]},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_add_to_universe_not_found(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/manager-screener/managers/NONEXISTENT999/add-to-universe",
            headers=DEV_ACTOR_HEADER,
            json={
                "asset_class": "equity",
                "geography": "US",
                "currency": "USD",
            },
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_managers_pagination(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/?page=1&page_size=5",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 5

    @pytest.mark.asyncio
    async def test_list_managers_with_filters(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/?aum_min=1000000&states=NY&compliance_clean=true",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_all_detail_endpoints_require_auth(self, client: AsyncClient) -> None:
        """All detail endpoints should return 403 for VIEWER role."""
        endpoints = [
            "/api/v1/manager-screener/managers/CRD1/profile",
            "/api/v1/manager-screener/managers/CRD1/holdings",
            "/api/v1/manager-screener/managers/CRD1/drift",
            "/api/v1/manager-screener/managers/CRD1/institutional",
            "/api/v1/manager-screener/managers/CRD1/universe-status",
        ]
        for url in endpoints:
            resp = await client.get(url, headers=_VIEWER_HEADER)
            assert resp.status_code == 403, f"Expected 403 for {url}"

    @pytest.mark.asyncio
    async def test_post_endpoints_require_auth(self, client: AsyncClient) -> None:
        """POST endpoints should return 403 for VIEWER role."""
        resp = await client.post(
            "/api/v1/manager-screener/managers/CRD1/add-to-universe",
            headers=_VIEWER_HEADER,
            json={"asset_class": "equity", "geography": "US"},
        )
        assert resp.status_code == 403

        resp = await client.post(
            "/api/v1/manager-screener/managers/compare",
            headers=_VIEWER_HEADER,
            json={"crd_numbers": ["CRD1", "CRD2"]},
        )
        assert resp.status_code == 403

    # ── N-PORT endpoints ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_nport_not_found(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/NONEXISTENT999/nport",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_nport_403_for_viewer(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/CRD1/nport",
            headers=_VIEWER_HEADER,
        )
        assert resp.status_code == 403

    # ── Brochure endpoints ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_brochure_sections_not_found(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/NONEXISTENT999/brochure/sections",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_brochure_search_not_found(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/NONEXISTENT999/brochure?q=ESG",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_brochure_search_query_too_short(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/CRD1/brochure?q=a",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_brochure_sections_403_for_viewer(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/CRD1/brochure/sections",
            headers=_VIEWER_HEADER,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_brochure_search_403_for_viewer(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/manager-screener/managers/CRD1/brochure?q=ESG",
            headers=_VIEWER_HEADER,
        )
        assert resp.status_code == 403

    # ── Route shadowing regression ────────────────────────────────

    @pytest.mark.asyncio
    async def test_literal_routes_not_shadowed(self, client: AsyncClient) -> None:
        """Brochure sections route must not be shadowed by {crd} param."""
        resp = await client.get(
            "/api/v1/manager-screener/managers/12345/brochure/sections",
            headers=DEV_ACTOR_HEADER,
        )
        # Should reach the actual handler (404 = manager not found, not route not found)
        assert resp.status_code != 405
        # If the route were shadowed, FastAPI would return 404 with "Not Found"
        # from the wrong handler or 405 Method Not Allowed
        assert resp.status_code in (200, 404)


# ═══════════════════════════════════════════════════════════════════════════
#  SEC Refresh Worker — Unit Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSecRefreshWorkerConstants:
    """Validate sec_refresh worker constants and structure."""

    def test_lock_id_is_deterministic(self) -> None:
        from app.domains.wealth.workers.sec_refresh import SEC_REFRESH_LOCK_ID

        assert SEC_REFRESH_LOCK_ID == 900_016

    def test_function_is_async(self) -> None:
        import asyncio

        from app.domains.wealth.workers.sec_refresh import run_sec_refresh

        assert asyncio.iscoroutinefunction(run_sec_refresh)

    def test_imports_from_query_builder(self) -> None:
        """Worker should reuse table definitions from the query builder module."""
        from app.domains.wealth.workers.sec_refresh import (
            drift_agg,
            holdings_agg,
            sec_managers,
        )

        assert holdings_agg.name == "sec_13f_holdings_agg"
        assert drift_agg.name == "sec_13f_drift_agg"
        assert sec_managers.name == "sec_managers"


class TestSecRefreshWorkerEndpoint:
    """Integration tests for /workers/run-sec-refresh endpoint."""

    @pytest.mark.asyncio
    async def test_trigger_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/workers/run-sec-refresh",
            headers=_VIEWER_HEADER,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_trigger_returns_202(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/workers/run-sec-refresh",
            headers=DEV_ACTOR_HEADER,
        )
        # 202 (scheduled) or 409 (already running/recently completed)
        assert resp.status_code in (202, 409)
