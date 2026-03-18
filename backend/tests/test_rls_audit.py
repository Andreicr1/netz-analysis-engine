"""Tests for RLS policy audit (AUTH-04).

Validates:
1. Every tenant-scoped table is classified in TENANT_SCOPED_TABLES
2. Every global table is classified in GLOBAL_TABLES
3. No table appears in both sets
4. Migration code matches expected RLS patterns
5. CI can fail on missing RLS coverage
"""

from __future__ import annotations

import importlib

import pytest

from app.core.db.rls_audit import (
    GLOBAL_TABLES,
    SPECIAL_RLS_TABLES,
    TENANT_SCOPED_TABLES,
    audit_rls_from_migrations,
)


def _import_migration(name: str):
    """Import a migration module by its filename (handles numeric prefixes)."""
    return importlib.import_module(f"app.core.db.migrations.versions.{name}")


class TestTableClassification:
    """All tables must be classified as tenant-scoped or global."""

    def test_no_overlap(self):
        """No table can be both tenant-scoped and global."""
        overlap = TENANT_SCOPED_TABLES & GLOBAL_TABLES
        assert not overlap, f"Tables in both sets: {sorted(overlap)}"

    def test_tenant_tables_not_empty(self):
        assert len(TENANT_SCOPED_TABLES) > 50  # 67 tables as of 0015

    def test_global_tables_not_empty(self):
        assert len(GLOBAL_TABLES) >= 5

    def test_known_global_tables(self):
        """Explicitly named global tables from CLAUDE.md."""
        expected_globals = {"macro_data", "allocation_blocks", "vertical_config_defaults"}
        assert expected_globals <= GLOBAL_TABLES

    def test_known_tenant_tables(self):
        """Spot-check key tenant-scoped tables."""
        expected_tenant = {
            "deals", "ic_memos", "documents", "funds_universe",
            "instruments_universe", "strategy_drift_alerts",
            "vertical_config_overrides",
        }
        assert expected_tenant <= TENANT_SCOPED_TABLES

    def test_config_defaults_is_global(self):
        assert "vertical_config_defaults" in GLOBAL_TABLES
        assert "vertical_config_defaults" not in TENANT_SCOPED_TABLES

    def test_config_overrides_is_tenant(self):
        assert "vertical_config_overrides" in TENANT_SCOPED_TABLES
        assert "vertical_config_overrides" not in GLOBAL_TABLES


class TestMigrationRLSPatterns:
    """Validate RLS patterns in migration code (static analysis)."""

    def test_0003_tables_in_registry(self):
        """All 0003 _RLS_TABLES must be in TENANT_SCOPED_TABLES."""
        m = _import_migration("0003_credit_domain")
        missing = set(m._RLS_TABLES) - TENANT_SCOPED_TABLES
        assert not missing, f"0003 tables missing from registry: {sorted(missing)}"

    def test_0008_tables_in_registry(self):
        """All 0008 _NEW_RLS_TABLES must be in TENANT_SCOPED_TABLES."""
        m = _import_migration("0008_wealth_analytical_models")
        missing = set(m._NEW_RLS_TABLES) - TENANT_SCOPED_TABLES
        assert not missing, f"0008 tables missing from registry: {sorted(missing)}"

    def test_0012_tables_in_registry(self):
        """All 0012 _NEW_RLS_TABLES must be in TENANT_SCOPED_TABLES."""
        m = _import_migration("0012_instruments_universe_additive")
        missing = set(m._NEW_RLS_TABLES) - TENANT_SCOPED_TABLES
        assert not missing, f"0012 tables missing from registry: {sorted(missing)}"

    def test_0016_fixes_0012_tables(self):
        """Migration 0016 must fix all tables from 0012."""
        m12 = _import_migration("0012_instruments_universe_additive")
        m16 = _import_migration("0016_fix_instruments_rls")
        assert set(m16._TABLES_TO_FIX) == set(m12._NEW_RLS_TABLES), (
            f"0016 must fix exactly the tables from 0012. "
            f"Missing: {set(m12._NEW_RLS_TABLES) - set(m16._TABLES_TO_FIX)}, "
            f"Extra: {set(m16._TABLES_TO_FIX) - set(m12._NEW_RLS_TABLES)}"
        )

    def test_0016_revision_chain(self):
        """0016 must follow 0015 in the revision chain."""
        m = _import_migration("0016_fix_instruments_rls")
        assert m.revision == "0016"
        assert m.down_revision == "0015"


class TestStaticAudit:
    """Static migration audit must pass."""

    def test_static_audit_passes(self):
        errors = audit_rls_from_migrations()
        assert errors == [], f"Static RLS audit failures: {errors}"


class TestSpecialRLSTables:
    """Tables with non-standard RLS patterns are documented."""

    def test_prompt_overrides_documented(self):
        assert "prompt_overrides" in SPECIAL_RLS_TABLES

    def test_prompt_override_versions_documented(self):
        assert "prompt_override_versions" in SPECIAL_RLS_TABLES

    def test_special_tables_are_tenant_scoped(self):
        for table in SPECIAL_RLS_TABLES:
            assert table in TENANT_SCOPED_TABLES, (
                f"Special RLS table '{table}' must be in TENANT_SCOPED_TABLES"
            )


class TestAdminAuditLogIsGlobal:
    """admin_audit_log must be global (cross-tenant, no RLS)."""

    def test_in_global_set(self):
        assert "admin_audit_log" in GLOBAL_TABLES

    def test_not_in_tenant_set(self):
        assert "admin_audit_log" not in TENANT_SCOPED_TABLES


class TestBenchmarkNavIsGlobal:
    """benchmark_nav must be global (shared reference data)."""

    def test_in_global_set(self):
        assert "benchmark_nav" in GLOBAL_TABLES


class TestMacroRegionalSnapshotsIsGlobal:
    """macro_regional_snapshots must be global (shared macro data)."""

    def test_in_global_set(self):
        assert "macro_regional_snapshots" in GLOBAL_TABLES
