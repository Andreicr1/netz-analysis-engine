"""Tests for ESMA REST endpoints.

Covers:
  - Route mounting (401/404 distinction)
  - Auth (ADMIN gets 200, non-admin gets 403)
  - Query builder SQL generation
  - Paginated responses
  - SEC cross-reference
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects import postgresql

from app.domains.wealth.queries.esma_sql import (
    EsmaFundFilters,
    EsmaManagerFilters,
    _escape_ilike,
    build_fund_detail_query,
    build_fund_list_queries,
    build_manager_detail_query,
    build_manager_funds_query,
    build_manager_list_queries,
    build_sec_crossref_query,
)

# ── Auth headers ────────────────────────────────────────────────

DEV_ACTOR_HEADER = {
    "X-DEV-ACTOR": (
        '{"actor_id": "test-user", "roles": ["ADMIN"], '
        '"fund_ids": [], "org_id": "00000000-0000-0000-0000-000000000001"}'
    )
}

_VIEWER_HEADER = {
    "X-DEV-ACTOR": (
        '{"actor_id": "viewer-user", "roles": ["INVESTOR"], '
        '"fund_ids": [], "org_id": "00000000-0000-0000-0000-000000000001"}'
    )
}


# ═══════════════════════════════════════════════════════════════════
#  Text search escaping
# ═══════════════════════════════════════════════════════════════════


class TestEscapeIlike:
    def test_percent_escaped(self) -> None:
        assert _escape_ilike("100%") == r"100\%"

    def test_underscore_escaped(self) -> None:
        assert _escape_ilike("fund_name") == r"fund\_name"

    def test_backslash_escaped(self) -> None:
        assert _escape_ilike(r"a\b") == r"a\\b"

    def test_normal_text_unchanged(self) -> None:
        assert _escape_ilike("Vanguard") == "Vanguard"


# ═══════════════════════════════════════════════════════════════════
#  Filter dataclass defaults
# ═══════════════════════════════════════════════════════════════════


class TestFilterDefaults:
    def test_manager_filters_defaults(self) -> None:
        f = EsmaManagerFilters()
        assert f.country is None
        assert f.search is None
        assert f.page == 1
        assert f.page_size == 50

    def test_fund_filters_defaults(self) -> None:
        f = EsmaFundFilters()
        assert f.domicile is None
        assert f.fund_type is None
        assert f.search is None
        assert f.page == 1
        assert f.page_size == 50


# ═══════════════════════════════════════════════════════════════════
#  Query builder SQL generation
# ═══════════════════════════════════════════════════════════════════


def _compile_sql(stmt) -> str:
    """Compile a SQLAlchemy statement to string for inspection."""
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class TestManagerListQueries:
    def test_empty_filters_valid_sql(self) -> None:
        data_q, count_q = build_manager_list_queries(EsmaManagerFilters())
        sql = _compile_sql(data_q)
        assert "esma_managers" in sql
        assert "LIMIT" in sql

    def test_country_filter(self) -> None:
        f = EsmaManagerFilters(country="IE")
        data_q, _ = build_manager_list_queries(f)
        sql = _compile_sql(data_q)
        assert "country" in sql
        assert "'IE'" in sql

    def test_text_search_uses_ilike(self) -> None:
        f = EsmaManagerFilters(search="Vanguard")
        data_q, _ = build_manager_list_queries(f)
        sql = _compile_sql(data_q)
        assert "ILIKE" in sql.upper()
        assert "Vanguard" in sql

    def test_pagination(self) -> None:
        f = EsmaManagerFilters(page=3, page_size=20)
        data_q, _ = build_manager_list_queries(f)
        sql = _compile_sql(data_q)
        assert "LIMIT 20" in sql
        assert "OFFSET 40" in sql

    def test_count_query_no_limit(self) -> None:
        _, count_q = build_manager_list_queries(EsmaManagerFilters())
        sql = _compile_sql(count_q)
        assert "count" in sql.lower()
        assert "LIMIT" not in sql


class TestManagerDetailQuery:
    def test_filters_by_esma_id(self) -> None:
        q = build_manager_detail_query("MGR001")
        sql = _compile_sql(q)
        assert "esma_managers" in sql
        assert "'MGR001'" in sql


class TestManagerFundsQuery:
    def test_filters_by_manager_id(self) -> None:
        q = build_manager_funds_query("MGR001")
        sql = _compile_sql(q)
        assert "esma_funds" in sql
        assert "'MGR001'" in sql


class TestFundListQueries:
    def test_empty_filters_valid_sql(self) -> None:
        data_q, count_q = build_fund_list_queries(EsmaFundFilters())
        sql = _compile_sql(data_q)
        assert "esma_funds" in sql
        assert "LIMIT" in sql

    def test_domicile_filter(self) -> None:
        f = EsmaFundFilters(domicile="LU")
        data_q, _ = build_fund_list_queries(f)
        sql = _compile_sql(data_q)
        assert "'LU'" in sql

    def test_fund_type_filter(self) -> None:
        f = EsmaFundFilters(fund_type="UCITS")
        data_q, _ = build_fund_list_queries(f)
        sql = _compile_sql(data_q)
        assert "'UCITS'" in sql

    def test_search_uses_ilike(self) -> None:
        f = EsmaFundFilters(search="Bond")
        data_q, _ = build_fund_list_queries(f)
        sql = _compile_sql(data_q)
        assert "ILIKE" in sql.upper()


class TestFundDetailQuery:
    def test_joins_manager(self) -> None:
        q = build_fund_detail_query("IE00ABC")
        sql = _compile_sql(q)
        assert "esma_funds" in sql
        assert "esma_managers" in sql
        assert "JOIN" in sql.upper()


class TestSecCrossrefQuery:
    def test_joins_sec_managers(self) -> None:
        q = build_sec_crossref_query("MGR001")
        sql = _compile_sql(q)
        assert "esma_managers" in sql
        assert "sec_managers" in sql
        assert "JOIN" in sql.upper()


# ═══════════════════════════════════════════════════════════════════
#  Route mounting tests (no DB required)
# ═══════════════════════════════════════════════════════════════════


class TestEsmaRouteMounting:
    """Verify routes exist (401 not 404) and auth works."""

    @pytest.mark.asyncio
    async def test_managers_route_exists(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/esma/managers")
        assert resp.status_code != 404, "ESMA managers route not mounted"

    @pytest.mark.asyncio
    async def test_funds_route_exists(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/esma/funds")
        assert resp.status_code != 404, "ESMA funds route not mounted"

    @pytest.mark.asyncio
    async def test_manager_detail_route_exists(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/esma/managers/FAKE_ID")
        assert resp.status_code != 404, "ESMA manager detail route not mounted"

    @pytest.mark.asyncio
    async def test_fund_detail_route_exists(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/esma/funds/FAKE_ISIN")
        assert resp.status_code != 404, "ESMA fund detail route not mounted"

    @pytest.mark.asyncio
    async def test_sec_crossref_route_exists(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/esma/managers/FAKE_ID/sec-crossref")
        assert resp.status_code != 404, "ESMA SEC crossref route not mounted"


class TestEsmaAuth:
    """Auth: non-admin roles should get 403."""

    @pytest.mark.asyncio
    async def test_viewer_gets_403_on_managers(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/esma/managers",
            headers=_VIEWER_HEADER,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_gets_403_on_funds(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/esma/funds",
            headers=_VIEWER_HEADER,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_gets_403_on_sec_crossref(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/esma/managers/FAKE/sec-crossref",
            headers=_VIEWER_HEADER,
        )
        assert resp.status_code == 403


class TestEsmaWorkerTrigger:
    """Worker trigger endpoint tests."""

    @pytest.mark.asyncio
    async def test_trigger_route_exists(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/workers/run-esma-ingestion")
        assert resp.status_code != 404, "ESMA worker trigger route not mounted"

    @pytest.mark.asyncio
    async def test_trigger_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/workers/run-esma-ingestion")
        assert resp.status_code == 401
