"""Global table isolation enforcement — AUTH-03.

Static import-guard tests that enforce the following invariants:

1. Any module that directly imports a global-table ORM model must be in the
   ALLOWLISTED_GLOBAL_TABLE_CONSUMERS set.

2. Modules that use the ``get_db_with_rls`` FastAPI dependency (i.e., tenant-
   scoped route files) must NOT directly write to global tables.  Writing means
   calling session.add(), session.execute(INSERT/UPDATE/DELETE stmt) against a
   global-table model.  Reading is permitted (global tables have no RLS, so
   reads from a tenant-scoped session are safe and intentional).

3. Admin routes MUST use ``get_db_admin`` (or ``get_db_for_tenant``), never
   ``get_db_with_rls``, for any operation that mutates a global table or crosses
   tenant boundaries.

4. Background workers that access global tables MUST obtain their sessions via
   ``async_session_factory`` directly — never via the FastAPI RLS dependency
   (workers run outside the request lifecycle and have no actor context).

These checks are intentionally conservative:
  - They operate on source text / AST, not runtime behaviour.
  - A false-positive is far less dangerous than a silent authorisation bypass.
  - When you add a new legitimate consumer, add it to the allowlist with a
    comment explaining why it is safe.

No database connection is required — all checks are purely static.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Root of the backend source tree
# ---------------------------------------------------------------------------
BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
QUANT_ENGINE_ROOT = BACKEND_ROOT / "quant_engine"
DATA_PROVIDERS_ROOT = BACKEND_ROOT / "data_providers"

# ---------------------------------------------------------------------------
# Canonical set of global-table ORM model symbols and their import paths.
#
# A "global table" is any table listed in rls_audit.GLOBAL_TABLES.
# The models here are the ones directly importable in Python code.
# ---------------------------------------------------------------------------
GLOBAL_TABLE_MODELS: dict[str, set[str]] = {
    # macro_data
    "app.shared.models": {
        "MacroData", "MacroRegionalSnapshot", "MacroSnapshot",
        "SecManager", "SecManagerFund", "SecManagerTeam",
        "Sec13fHolding", "Sec13fDiff", "SecInstitutionalAllocation",
        "SecCusipTickerMap",
    },
    "app.domains.wealth.models.macro": {"MacroData"},
    # allocation_blocks
    "app.domains.wealth.models.block": {"AllocationBlock"},
    # benchmark_nav
    "app.domains.wealth.models.benchmark_nav": {"BenchmarkNav"},
    # vertical_config_defaults  (VerticalConfigOverride is tenant-scoped — NOT listed)
    "app.core.config.models": {"VerticalConfigDefault"},
    # admin_audit_log
    "app.domains.admin.models": {"AdminAuditLog"},
}

# Flat set of all global-table model class names for quick membership checks.
ALL_GLOBAL_MODEL_NAMES: frozenset[str] = frozenset(
    name
    for names in GLOBAL_TABLE_MODELS.values()
    for name in names
)

# ---------------------------------------------------------------------------
# Allowlist — modules permitted to import or use global-table models.
#
# Key:   path relative to BACKEND_ROOT, using forward slashes.
# Value: short rationale (required — forces reviewers to think before adding).
#
# Convention:
#   "read" — only SELECTs against global tables.
#   "write" — may INSERT/UPDATE/DELETE (workers or admin only).
#   "admin" — admin operation that requires cross-tenant context.
#   "service" — encapsulated service that accepts a session from the caller.
#   "model" — model definition file or re-export shim.
#   "migration" — Alembic migration (DDL only, not runtime data access).
#   "test" — test helper or test file.
# ---------------------------------------------------------------------------
ALLOWLISTED_GLOBAL_TABLE_CONSUMERS: dict[str, str] = {
    # ── Model definitions (canonical source) ────────────────────────────────
    "app/shared/models.py": "model — canonical definitions for MacroData, MacroRegionalSnapshot, MacroSnapshot, SecManager, SecManagerFund, SecManagerTeam, Sec13fHolding, Sec13fDiff, SecInstitutionalAllocation",
    "app/domains/wealth/models/macro.py": "model — backward-compat re-export shim for MacroData",
    "app/domains/wealth/models/block.py": "model — canonical definition for AllocationBlock",
    "app/domains/wealth/models/benchmark_nav.py": "model — canonical definition for BenchmarkNav",
    "app/core/config/models.py": "model — canonical definitions for VerticalConfigDefault and VerticalConfigOverride",
    "app/domains/admin/models.py": "model — canonical definition for AdminAuditLog and TenantAsset",
    "app/domains/wealth/models/__init__.py": "model — re-exports AllocationBlock, BenchmarkNav, MacroData for convenience imports",
    # ── Core DB (base classes and metadata) ─────────────────────────────────
    "app/core/db/base.py": "model — SQLAlchemy Base and mixins; imports all models for metadata",
    "app/core/db/rls_audit.py": "service — audit helper that references table names (strings only, no ORM imports)",
    # ── ConfigService — safe read of VerticalConfigDefault ──────────────────
    "app/core/config/config_service.py": "service — read-only SELECT on VerticalConfigDefault; safe with any session",
    "app/core/config/dependencies.py": "service — FastAPI dependency that constructs ConfigService",
    # ── Admin routes — use get_db_admin, cross-tenant access is intentional ─
    "app/domains/admin/routes/tenants.py": "admin — uses get_db_admin; reads VerticalConfigDefault for tenant seeding",
    "app/domains/admin/services/config_writer.py": "admin — uses session from caller (always get_db_admin in route layer); writes VerticalConfigDefault",
    # ── Wealth routes — read-only access to global reference data ───────────
    "app/domains/wealth/routes/attribution.py": "read — SELECT only on AllocationBlock and BenchmarkNav; no writes",
    "app/domains/wealth/routes/macro.py": "read — SELECT only on MacroRegionalSnapshot; no writes",
    "app/domains/wealth/services/blended_benchmark_service.py": "read — SELECT only on AllocationBlock and BenchmarkNav; no writes",
    "app/domains/wealth/routes/screener.py": "read — SELECT only on SecManager (and EsmaFund/EsmaManager) for global instrument search; no writes; global tables shared across tenants",
    "app/domains/wealth/routes/sec_analysis.py": "read — SELECT only on SecManager, Sec13fHolding, Sec13fDiff, SecManagerFund; no writes; global SEC data shared across tenants",
    # ── Background workers — use async_session_factory directly (no RLS) ────
    "app/domains/wealth/workers/macro_ingestion.py": "write — writes MacroData and MacroRegionalSnapshot via async_session_factory",
    "app/domains/wealth/workers/regime_fit.py": "read — reads MacroData via async_session_factory for regime fitting",
    "app/domains/wealth/workers/risk_calc.py": "read — reads MacroData via async_session_factory for CVaR computation",
    "app/domains/wealth/workers/benchmark_ingest.py": "write — writes AllocationBlock, BenchmarkNav via async_session_factory",
    "app/domains/wealth/workers/drift_check.py": "read — reads VerticalConfigDefault via async_session_factory for config",
    "app/domains/wealth/workers/portfolio_eval.py": "read — reads VerticalConfigDefault via async_session_factory for config",
    # ── Quant engine — pure functions that receive session from caller ───────
    "quant_engine/regime_service.py": "service — receives session as parameter; SELECTs MacroData only",
    # ── Main app (seed-data bootstrap only) ─────────────────────────────────
    "app/main.py": "service — reads VerticalConfigDefault at startup for seed-data check only",
    # ── AI domain (MacroSnapshot re-export reference) ────────────────────────
    "app/domains/credit/modules/ai/models.py": "model — imports MacroSnapshot from shared.models for ORM metadata registration",
    # ── Migrations (DDL only) ────────────────────────────────────────────────
    "app/core/db/migrations/versions/0002_wealth_domain.py": "migration — creates allocation_blocks DDL",
    "app/core/db/migrations/versions/0003_credit_domain.py": "migration — creates macro_data DDL",
    "app/core/db/migrations/versions/0004_vertical_configs.py": "migration — creates vertical_config_defaults DDL",
    "app/core/db/migrations/versions/0005_macro_regional_snapshots.py": "migration — creates macro_regional_snapshots DDL",
    "app/core/db/migrations/versions/0007_governance_policy_seed.py": "migration — seeds vertical_config_defaults rows",
    "app/core/db/migrations/versions/0009_admin_infrastructure.py": "migration — creates admin_audit_log DDL",
    "app/core/db/migrations/versions/0011_instruments_data_migration.py": "migration — data migration referencing global tables",
    "app/core/db/migrations/versions/0012_instruments_universe_additive.py": "migration — additive migration referencing global tables",
    "app/core/db/migrations/versions/0013_benchmark_nav.py": "migration — creates benchmark_nav DDL",
    "app/core/db/migrations/versions/0014_strategy_drift_alerts.py": "migration — may reference global tables",
    "app/core/db/migrations/versions/0015_admin_rls_bypass.py": "migration — admin RLS bypass DDL",
    # ── Prompts service (AdminAuditLog for audit trail) ──────────────────────
    "app/core/prompts/prompt_service.py": "admin — uses AdminAuditLog for audit trail; called from admin routes only",
    # ── Credit dashboard — read-only access to global macro data ────────────
    "app/domains/credit/dashboard/routes.py": "read — SELECT only on MacroData for dashboard aggregation; uses get_db_with_rls (read is safe, global tables have no RLS)",
    # ── Wealth N-PORT ingestion worker — reads SecManager for CIK resolution ─
    "app/domains/wealth/workers/nport_ingestion.py": "read — reads SecManager via async_session_factory for CIK resolution during N-PORT ingestion (no RLS)",
    "app/domains/wealth/workers/sec_13f_ingestion.py": "write — reads SecManager CIKs, delegates to ThirteenFService for 13F EDGAR ingestion via async_session_factory (no RLS)",
    # ── Data providers — background workers that upsert to global SEC tables ─
    "data_providers/sec/adv_service.py": "write — upserts SecManager and SecManagerFund via async_session_factory (bulk CSV ingestion, no RLS)",
    "data_providers/sec/thirteenf_service.py": "write — upserts Sec13fHolding and Sec13fDiff via async_session_factory (13F-HR ingestion, no RLS)",
    "data_providers/sec/institutional_service.py": "write — reads Sec13fHolding CUSIPs and upserts SecInstitutionalAllocation via async_session_factory (13F reverse lookup, no RLS)",
    "data_providers/sec/seed/populate_seed.py": "write — seed script upserts SecCusipTickerMap via async_session_factory (Phase 6 CUSIP→ticker mapping, no RLS)",
    # ── Tests ────────────────────────────────────────────────────────────────
    "tests/test_global_table_isolation.py": "test — this file",
    "tests/test_rls_audit.py": "test — imports GLOBAL_TABLES set (strings, not ORM models)",
    "tests/test_rls.py": "test — validates RLS table lists",
}

# ---------------------------------------------------------------------------
# Admin routes that MUST NOT use get_db_with_rls for global-table mutations.
# These paths are under app/domains/admin/ and should exclusively use
# get_db_admin.  We exclude branding.py which is a tenant-scoped read.
# ---------------------------------------------------------------------------
ADMIN_ROUTES_REQUIRING_DB_ADMIN: set[str] = {
    "app/domains/admin/routes/tenants.py",
    "app/domains/admin/routes/configs.py",
    "app/domains/admin/routes/prompts.py",
    "app/domains/admin/routes/health.py",
}

# ---------------------------------------------------------------------------
# Routes that use get_db_with_rls and access global tables (read-only).
# These are legitimate because:
#   a) Global tables have no RLS — any session can read them.
#   b) The access is SELECT-only (never INSERT/UPDATE/DELETE).
# ---------------------------------------------------------------------------
TENANT_ROUTES_WITH_GLOBAL_TABLE_READS: set[str] = {
    "app/domains/credit/dashboard/routes.py",
    "app/domains/wealth/routes/attribution.py",
    "app/domains/wealth/routes/macro.py",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _relative_path(path: Path) -> str:
    """Return posix path relative to BACKEND_ROOT."""
    return path.relative_to(BACKEND_ROOT).as_posix()


def _all_python_files(root: Path) -> list[Path]:
    """Recursively collect .py files, excluding __pycache__."""
    return [
        p for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def _source(path: Path) -> str:
    """Read source text of a Python file."""
    return path.read_text(encoding="utf-8")


def _imports_global_model(source_text: str) -> bool:
    """Return True if the source text imports any global-table model class."""
    for module_path, symbols in GLOBAL_TABLE_MODELS.items():
        for symbol in symbols:
            # from <module_path> import <symbol>
            pattern = rf"from\s+{re.escape(module_path)}\s+import\b[^#\n]*\b{re.escape(symbol)}\b"
            if re.search(pattern, source_text):
                return True
    return False


def _uses_get_db_with_rls(source_text: str) -> bool:
    """Return True if the source text imports or calls get_db_with_rls.

    Matches actual Python usage (import or Depends(get_db_with_rls)) but not
    appearances in comments or docstrings that only say "RLS".
    """
    return bool(re.search(r"\bget_db_with_rls\b", source_text))


def _uses_get_db_admin(source_text: str) -> bool:
    """Return True if the source text references get_db_admin."""
    return bool(re.search(r"\bget_db_admin\b", source_text))


def _uses_async_session_factory(source_text: str) -> bool:
    """Return True if source directly uses async_session_factory."""
    return bool(re.search(r"\basync_session_factory\b|\basync_session\b", source_text))


class _GlobalTableWriteVisitor(ast.NodeVisitor):
    """AST visitor that detects write operations against global-table models.

    A "write" is any call of the form:
      - db.add(<GlobalModel>(...))
      - db.execute(insert(GlobalModel) ...)   [pg_insert or sa insert]
      - db.execute(update(GlobalModel) ...)
      - db.execute(delete(GlobalModel) ...)

    We look for names from ALL_GLOBAL_MODEL_NAMES appearing as arguments to
    insert/update/delete constructors.  This is necessarily heuristic but
    catches the common patterns used across the codebase.
    """

    def __init__(self) -> None:
        self.write_operations: list[tuple[int, str]] = []  # (lineno, description)

    def _is_global_model_name(self, node: ast.expr) -> bool:
        """Return True if node is a Name or Attribute whose base is a global model."""
        if isinstance(node, ast.Name):
            return node.id in ALL_GLOBAL_MODEL_NAMES
        if isinstance(node, ast.Attribute):
            return isinstance(node.value, ast.Name) and node.value.id in ALL_GLOBAL_MODEL_NAMES
        return False

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Pattern: db.add(GlobalModel(...))
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "add"
            and node.args
            and isinstance(node.args[0], ast.Call)
            and self._is_global_model_name(node.args[0].func)
        ):
            model_name = (
                node.args[0].func.id
                if isinstance(node.args[0].func, ast.Name)
                else getattr(node.args[0].func, "attr", "?")
            )
            self.write_operations.append(
                (node.lineno, f"db.add({model_name}(...))")
            )

        # Pattern: insert(GlobalModel) / pg_insert(GlobalModel)
        # Pattern: update(GlobalModel)
        # Pattern: delete(GlobalModel) / sa_delete(GlobalModel)
        if isinstance(node.func, ast.Name) and node.func.id in ("insert", "pg_insert", "update", "delete", "sa_delete"):
            if node.args and self._is_global_model_name(node.args[0]):
                self.write_operations.append(
                    (node.lineno, f"{node.func.id}({node.args[0].id if isinstance(node.args[0], ast.Name) else '...'})")
                )

        self.generic_visit(node)


def _has_global_table_writes(source_text: str) -> list[tuple[int, str]]:
    """Return list of (lineno, description) for detected global-table write ops."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return []
    visitor = _GlobalTableWriteVisitor()
    visitor.visit(tree)
    return visitor.write_operations


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestGlobalTableImportAllowlist:
    """Any file importing a global-table model must be in the allowlist."""

    def test_no_unlisted_global_table_consumers(self):
        """Fail if an unlisted module imports a global-table ORM model.

        This is the primary CI gate for AUTH-03.  Add new consumers to
        ALLOWLISTED_GLOBAL_TABLE_CONSUMERS with a rationale comment.
        """
        violations: list[str] = []

        search_roots = [APP_ROOT, QUANT_ENGINE_ROOT, DATA_PROVIDERS_ROOT]
        for root in search_roots:
            if not root.exists():
                continue
            for py_file in _all_python_files(root):
                rel = _relative_path(py_file)
                if rel in ALLOWLISTED_GLOBAL_TABLE_CONSUMERS:
                    continue  # Explicitly allowed
                source = _source(py_file)
                if _imports_global_model(source):
                    violations.append(rel)

        assert not violations, (
            "The following modules import global-table ORM models but are NOT "
            "in ALLOWLISTED_GLOBAL_TABLE_CONSUMERS.\n\n"
            "If the access is intentional, add an entry with a rationale.\n"
            "If it is accidental, remove the import.\n\n"
            "Violations:\n" + "\n".join(f"  {v}" for v in sorted(violations))
        )

    def test_all_allowlisted_files_exist(self):
        """Every entry in the allowlist should correspond to an existing file.

        Catches stale allowlist entries after renames or deletions.
        """
        missing: list[str] = []
        for rel in ALLOWLISTED_GLOBAL_TABLE_CONSUMERS:
            # Skip migration entries with globs or partial paths
            if rel.startswith("tests/"):
                full = BACKEND_ROOT / rel
            else:
                full = BACKEND_ROOT / rel
            if not full.exists():
                missing.append(rel)

        assert not missing, (
            "The following allowlisted paths no longer exist — remove stale entries:\n"
            + "\n".join(f"  {m}" for m in sorted(missing))
        )

    def test_allowlist_has_rationale_for_all_entries(self):
        """Every allowlist entry must have a non-empty rationale string."""
        missing_rationale: list[str] = []
        for path, rationale in ALLOWLISTED_GLOBAL_TABLE_CONSUMERS.items():
            if not rationale or not rationale.strip():
                missing_rationale.append(path)
        assert not missing_rationale, (
            "Allowlist entries missing rationale:\n"
            + "\n".join(f"  {p}" for p in sorted(missing_rationale))
        )


class TestAdminRoutesDependencies:
    """Admin routes that mutate global tables must use get_db_admin."""

    @pytest.mark.parametrize("rel_path", sorted(ADMIN_ROUTES_REQUIRING_DB_ADMIN))
    def test_admin_route_uses_db_admin(self, rel_path: str):
        """Verify the admin route uses get_db_admin dependency."""
        full = BACKEND_ROOT / rel_path
        if not full.exists():
            pytest.skip(f"File not found: {rel_path}")
        source = _source(full)
        assert _uses_get_db_admin(source), (
            f"{rel_path}: admin route must use get_db_admin dependency. "
            "Using get_db_with_rls on a cross-tenant admin route leaks tenant isolation context."
        )

    def test_tenant_branding_route_uses_rls(self):
        """branding.py uses get_db_with_rls (tenant-scoped read) — verify it stays that way."""
        rel = "app/domains/admin/routes/branding.py"
        full = BACKEND_ROOT / rel
        if not full.exists():
            pytest.skip(f"File not found: {rel}")
        source = _source(full)
        assert _uses_get_db_with_rls(source), (
            f"{rel}: branding route must use get_db_with_rls (tenant-scoped asset lookup)."
        )


class TestTenantRoutesNoGlobalTableWrites:
    """Tenant routes (get_db_with_rls) must never WRITE to global tables."""

    @pytest.mark.parametrize("rel_path", sorted(TENANT_ROUTES_WITH_GLOBAL_TABLE_READS))
    def test_tenant_route_has_no_global_writes(self, rel_path: str):
        """Verify that routes using get_db_with_rls only READ global tables."""
        full = BACKEND_ROOT / rel_path
        if not full.exists():
            pytest.skip(f"File not found: {rel_path}")
        source = _source(full)

        # Must use get_db_with_rls (confirming it's a tenant-scoped route)
        assert _uses_get_db_with_rls(source), (
            f"{rel_path}: expected get_db_with_rls but it was not found."
        )

        # Must NOT write to global tables
        writes = _has_global_table_writes(source)
        assert not writes, (
            f"{rel_path}: tenant-scoped route performs write operations on global tables.\n"
            "Global tables have no RLS and must only be mutated by admin routes or workers.\n"
            "Detected writes:\n"
            + "\n".join(f"  line {ln}: {desc}" for ln, desc in writes)
        )

    def test_no_rls_route_writes_global_tables_broadly(self):
        """Broad scan: no route using get_db_with_rls writes to global tables.

        This covers ALL route files, not just the explicitly listed ones above.
        """
        violations: list[str] = []

        for py_file in _all_python_files(APP_ROOT):
            rel = _relative_path(py_file)
            # Only scan route files
            if "/routes/" not in rel and not rel.endswith("routes.py"):
                continue
            source = _source(py_file)
            if not _uses_get_db_with_rls(source):
                continue
            if not _imports_global_model(source):
                continue  # Doesn't import global models — can't write them
            writes = _has_global_table_writes(source)
            if writes:
                for ln, desc in writes:
                    violations.append(f"{rel}:{ln} — {desc}")

        assert not violations, (
            "Route files using get_db_with_rls perform write operations on global tables.\n"
            "Global tables must only be mutated by admin routes (get_db_admin) or workers.\n\n"
            "Violations:\n" + "\n".join(f"  {v}" for v in sorted(violations))
        )


class TestWorkerSessionIsolation:
    """Background workers that write to global tables must use async_session_factory."""

    WORKER_FILES_WITH_GLOBAL_WRITES: set[str] = {
        "app/domains/wealth/workers/macro_ingestion.py",
        "app/domains/wealth/workers/benchmark_ingest.py",
    }

    @pytest.mark.parametrize("rel_path", sorted(WORKER_FILES_WITH_GLOBAL_WRITES))
    def test_worker_uses_async_session_factory(self, rel_path: str):
        """Workers must use async_session_factory, not a FastAPI RLS dependency."""
        full = BACKEND_ROOT / rel_path
        if not full.exists():
            pytest.skip(f"File not found: {rel_path}")
        source = _source(full)

        assert _uses_async_session_factory(source), (
            f"{rel_path}: worker that writes global tables must use async_session_factory "
            "directly — not a FastAPI dependency injected via Depends()."
        )
        assert not _uses_get_db_with_rls(source), (
            f"{rel_path}: worker must not use get_db_with_rls — "
            "workers run outside the request lifecycle and have no actor context."
        )


class TestQuantEngineSessionIsolation:
    """quant_engine modules receive sessions from callers — must not import dependencies."""

    def test_regime_service_receives_session_as_param(self):
        """regime_service.py must not import get_db_with_rls or get_db_admin.

        It must receive the session as a function parameter from its caller.
        This enforces the 'session injection' pattern required by CLAUDE.md.
        """
        regime_svc = BACKEND_ROOT / "quant_engine" / "regime_service.py"
        if not regime_svc.exists():
            pytest.skip("quant_engine/regime_service.py not found")
        source = _source(regime_svc)
        assert not _uses_get_db_with_rls(source), (
            "quant_engine/regime_service.py must not import get_db_with_rls — "
            "session must be injected by the caller."
        )
        assert not _uses_get_db_admin(source), (
            "quant_engine/regime_service.py must not import get_db_admin — "
            "session must be injected by the caller."
        )

    def test_regime_service_reads_macro_data(self):
        """regime_service.py must import MacroData (confirms it accesses global data)."""
        regime_svc = BACKEND_ROOT / "quant_engine" / "regime_service.py"
        if not regime_svc.exists():
            pytest.skip("quant_engine/regime_service.py not found")
        source = _source(regime_svc)
        # MacroData is needed for get_latest_macro_values()
        assert "MacroData" in source, (
            "quant_engine/regime_service.py expected to reference MacroData ORM model."
        )


class TestConfigServiceGlobalAccess:
    """ConfigService reads VerticalConfigDefault — must be session-agnostic."""

    def test_config_service_does_not_import_rls_dependency(self):
        """ConfigService must not *import* get_db_with_rls or get_db_admin.

        It accepts a session as __init__ parameter and is used by both
        admin and tenant routes.  Importing a specific dependency would
        couple it to one caller type.

        Note: mentions of these names in docstrings or comments are allowed;
        we check actual import statements via AST.
        """
        config_svc = APP_ROOT / "core" / "config" / "config_service.py"
        if not config_svc.exists():
            pytest.skip("config_service.py not found")
        source = _source(config_svc)

        # Use import-statement regex — not a bare name regex — so docstring
        # mentions like "Uses a single DB session (get_db_with_rls)" don't fire.
        imports_rls = bool(re.search(
            r"^\s*(?:from\s+\S+\s+import\b[^#\n]*\bget_db_with_rls\b"
            r"|import\s+\S*get_db_with_rls\b)",
            source,
            re.MULTILINE,
        ))
        imports_admin = bool(re.search(
            r"^\s*(?:from\s+\S+\s+import\b[^#\n]*\bget_db_admin\b"
            r"|import\s+\S*get_db_admin\b)",
            source,
            re.MULTILINE,
        ))
        assert not imports_rls, (
            "ConfigService must not import get_db_with_rls — it is session-agnostic."
        )
        assert not imports_admin, (
            "ConfigService must not import get_db_admin — it is session-agnostic."
        )

    def test_config_service_reads_config_default(self):
        """ConfigService must import VerticalConfigDefault (confirms it's a consumer)."""
        config_svc = APP_ROOT / "core" / "config" / "config_service.py"
        if not config_svc.exists():
            pytest.skip("config_service.py not found")
        source = _source(config_svc)
        assert "VerticalConfigDefault" in source, (
            "ConfigService expected to reference VerticalConfigDefault."
        )


class TestGlobalTableSetConsistency:
    """Cross-check that the GLOBAL_TABLES set in rls_audit matches model coverage here."""

    def test_primary_global_tables_have_model_coverage(self):
        """The three primary global tables (CLAUDE.md) must have model entries here."""
        expected_model_names = {"MacroData", "AllocationBlock", "VerticalConfigDefault"}
        assert expected_model_names <= ALL_GLOBAL_MODEL_NAMES, (
            f"Missing model coverage for primary global tables. "
            f"Expected {expected_model_names}, got {ALL_GLOBAL_MODEL_NAMES}."
        )

    def test_benchmark_nav_has_model_coverage(self):
        """benchmark_nav (global reference data) must have an ORM model entry."""
        assert "BenchmarkNav" in ALL_GLOBAL_MODEL_NAMES

    def test_macro_regional_snapshot_has_model_coverage(self):
        """macro_regional_snapshots (global macro data) must have an ORM model entry."""
        assert "MacroRegionalSnapshot" in ALL_GLOBAL_MODEL_NAMES

    def test_admin_audit_log_has_model_coverage(self):
        """admin_audit_log (cross-tenant, no RLS) must have an ORM model entry."""
        assert "AdminAuditLog" in ALL_GLOBAL_MODEL_NAMES

    def test_no_tenant_table_models_in_global_map(self):
        """VerticalConfigOverride (tenant-scoped) must NOT appear in global model map."""
        for _module, symbols in GLOBAL_TABLE_MODELS.items():
            assert "VerticalConfigOverride" not in symbols, (
                "VerticalConfigOverride is tenant-scoped (has RLS) and must not appear "
                "in GLOBAL_TABLE_MODELS."
            )


class TestAdminAdminAuditLogAccess:
    """admin_audit_log must only be written by admin routes and workers."""

    def test_admin_routes_write_audit_log_via_db_admin(self):
        """Admin route tenant.py must use get_db_admin when writing AdminAuditLog."""
        rel = "app/domains/admin/routes/tenants.py"
        full = BACKEND_ROOT / rel
        if not full.exists():
            pytest.skip(f"File not found: {rel}")
        source = _source(full)
        assert _uses_get_db_admin(source), (
            f"{rel}: must use get_db_admin when writing AdminAuditLog."
        )
        assert "AdminAuditLog" in source, (
            f"{rel}: expected to write AdminAuditLog entries."
        )

    def test_no_tenant_route_writes_admin_audit_log(self):
        """No tenant-scoped route (get_db_with_rls) should write AdminAuditLog.

        AdminAuditLog is for cross-tenant admin operations only.
        """
        violations: list[str] = []
        for py_file in _all_python_files(APP_ROOT):
            rel = _relative_path(py_file)
            if "/routes/" not in rel and not rel.endswith("routes.py"):
                continue
            source = _source(py_file)
            if not _uses_get_db_with_rls(source):
                continue
            # Check for AdminAuditLog writes (db.add(AdminAuditLog(...)))
            writes = _has_global_table_writes(source)
            audit_writes = [
                (ln, desc) for ln, desc in writes if "AdminAuditLog" in desc
            ]
            if audit_writes:
                for ln, desc in audit_writes:
                    violations.append(f"{rel}:{ln} — {desc}")

        assert not violations, (
            "Tenant-scoped routes (get_db_with_rls) must not write AdminAuditLog.\n"
            "AdminAuditLog is a cross-tenant global table — write via admin routes only.\n\n"
            "Violations:\n" + "\n".join(f"  {v}" for v in sorted(violations))
        )
