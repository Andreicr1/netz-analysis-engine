"""Tests for universe sanitization filter in catalog_sql.build_catalog_query.

Verifies that the default catalog query excludes non-institutional rows
via ``mv_unified_funds.is_institutional = true`` and that admin queries
may opt in via ``CatalogFilters.include_non_institutional=True``.
"""
from __future__ import annotations

from app.domains.wealth.queries.catalog_sql import (
    CatalogFilters,
    build_catalog_query,
)


def _rendered_sql(filters: CatalogFilters) -> str:
    stmt = build_catalog_query(filters)
    assert stmt is not None
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_default_catalog_query_filters_non_institutional() -> None:
    sql = _rendered_sql(CatalogFilters())
    assert "is_institutional IS true" in sql or "is_institutional IS TRUE" in sql


def test_include_non_institutional_disables_filter() -> None:
    sql = _rendered_sql(CatalogFilters(include_non_institutional=True))
    # When opt-out is set, no ``is_institutional IS true`` predicate is
    # emitted (the column may still appear in SELECT projections).
    assert "is_institutional IS true" not in sql
    assert "is_institutional IS TRUE" not in sql


def test_filter_coexists_with_other_conditions() -> None:
    sql = _rendered_sql(CatalogFilters(region="US", aum_min=1_000_000))
    # Institutional filter still applied when additional filters present.
    assert "is_institutional IS true" in sql or "is_institutional IS TRUE" in sql
    assert "region" in sql
