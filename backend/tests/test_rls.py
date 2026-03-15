"""RLS policy validation tests.

These tests verify that the migration 0003 RLS policies are correctly
defined by checking the migration code structure. Full DB-level RLS
isolation tests require `make up` + `make migrate`.
"""

from __future__ import annotations

import importlib

import pytest

# Module name starts with a digit — must use importlib
_mod = importlib.import_module("app.core.db.migrations.versions.0003_credit_domain")
_RLS_TABLES: list[str] = _mod._RLS_TABLES  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_rls_table_list_includes_wealth_tables():
    """Wealth tables from migration 0002 must be in RLS list."""
    wealth_tables = {
        "funds_universe", "nav_timeseries", "fund_risk_metrics",
        "portfolio_snapshots", "strategic_allocation", "tactical_positions",
        "rebalance_events", "lipper_ratings", "backtest_runs",
    }
    assert wealth_tables.issubset(set(_RLS_TABLES))


@pytest.mark.asyncio
async def test_rls_table_list_includes_credit_core():
    """Core credit tables must be in RLS list."""
    credit_core = {"deals", "pipeline_deals", "documents", "portfolio_assets",
                   "alerts", "actions", "ic_memos", "document_reviews"}
    assert credit_core.issubset(set(_RLS_TABLES))


@pytest.mark.asyncio
async def test_global_tables_excluded_from_rls():
    """Global tables (no org_id) must NOT be in the RLS list."""
    global_tables = {"macro_snapshots", "deep_review_validation_runs",
                     "eval_runs", "eval_chapter_scores",
                     "allocation_blocks", "macro_data"}
    assert global_tables.isdisjoint(set(_RLS_TABLES))


@pytest.mark.asyncio
async def test_audit_events_has_rls():
    """audit_events from migration 0001 must have RLS applied."""
    assert "audit_events" in _RLS_TABLES
