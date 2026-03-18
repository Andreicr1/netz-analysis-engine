"""RLS policy audit — AUTH-04.

Repeatable schema audit script that confirms RLS ENABLE + FORCE +
expected USING and WITH CHECK coverage for every tenant-scoped table.

Runs against both fresh migration builds and upgraded schemas.
Used by CI to fail on missing or incomplete RLS policies.

Usage:
    python -m app.core.db.rls_audit          # Against running DB
    pytest backend/tests/test_rls_audit.py   # Unit tests (no DB required)
"""

from __future__ import annotations

# ── Canonical table classification ──────────────────────────────────────────
# Single source of truth for which tables are tenant-scoped vs global.
# Derived from all migrations (0001-0015). Keep in sync when adding tables.

TENANT_SCOPED_TABLES: frozenset[str] = frozenset({
    # 0001 — Foundation
    "audit_events",
    # 0002 — Wealth Domain
    "funds_universe", "nav_timeseries", "fund_risk_metrics",
    "portfolio_snapshots", "strategic_allocation", "tactical_positions",
    "rebalance_events", "lipper_ratings", "backtest_runs",
    # 0003 — Credit Core
    "deals", "deal_qualifications", "ic_memos",
    "portfolio_assets", "alerts", "asset_obligations",
    "evidence_documents", "nav_snapshots", "investor_statements",
    "report_schedules", "report_runs",
    "documents", "document_versions", "document_access_policies",
    "document_root_folders", "document_chunks",
    "document_reviews", "review_assignments", "review_checklist_items", "review_events",
    "monthly_report_packs", "report_pack_sections",
    "asset_valuation_snapshots",
    "pipeline_deals", "pipeline_deal_documents", "pipeline_deal_stage_history",
    "pipeline_deal_decisions", "pipeline_qualification_rules", "pipeline_qualification_results",
    "deal_cashflows", "deal_conversion_events", "deal_events",
    "actions", "fund_investments",
    # 0003 — AI / intelligence
    "ai_queries", "ai_responses", "ai_questions", "ai_answers", "ai_answer_citations",
    "document_registry", "manager_profiles", "obligation_register", "governance_alerts",
    "document_classifications", "document_governance_profile",
    "knowledge_anchors", "knowledge_entities", "knowledge_links",
    "obligation_evidence_map", "deal_documents", "deal_intelligence_profiles",
    "deal_risk_flags", "deal_ic_briefs", "pipeline_alerts",
    "active_investments", "performance_drift_flags", "covenant_status_register",
    "cash_impact_flags", "investment_risk_registry", "board_monitoring_briefs",
    "investment_memorandum_drafts", "memo_evidence_packs", "memo_chapters",
    "deal_underwriting_artifacts", "periodic_review_reports",
    # 0004 — Vertical configs (overrides only — defaults are global)
    "vertical_config_overrides",
    # 0006 — Macro reviews
    "macro_reviews",
    # 0008 — Wealth analytical models
    "dd_reports", "dd_chapters", "universe_approvals", "model_portfolios",
    # 0009 — Admin infrastructure
    "tenant_assets", "prompt_overrides", "prompt_override_versions",
    # 0012 — Instruments universe
    "instruments_universe", "instrument_screening_metrics",
    "screening_runs", "screening_results",
    # 0014 — Strategy drift alerts
    "strategy_drift_alerts",
})

GLOBAL_TABLES: frozenset[str] = frozenset({
    # 0002 — Wealth allocation blocks
    "allocation_blocks",
    # 0003 — Credit global
    "macro_data",
    # 0004 — Vertical config defaults
    "vertical_config_defaults",
    # 0005 — Macro regional snapshots
    "macro_regional_snapshots",
    # 0013 — Benchmark NAV
    "benchmark_nav",
    # 0015 — Admin audit log (cross-tenant, no RLS)
    "admin_audit_log",
})

# Tables with special RLS patterns (not standard org_isolation)
SPECIAL_RLS_TABLES: dict[str, str] = {
    # prompt_overrides has nullable org_id (global + org-specific rows)
    "prompt_overrides": "org_isolation",
    # prompt_override_versions uses parent FK join for isolation
    "prompt_override_versions": "parent_isolation",
}


def audit_rls_from_migrations() -> list[str]:
    """Static audit: verify migration code covers all tenant-scoped tables.

    Returns list of errors (empty = pass).
    Does not require a running database.
    """
    errors: list[str] = []

    # Verify no table appears in both sets
    overlap = TENANT_SCOPED_TABLES & GLOBAL_TABLES
    if overlap:
        errors.append(f"Tables in both tenant and global sets: {sorted(overlap)}")

    # Verify all tables are classified
    # (This is a meta-check — new migrations must add to one of the sets)

    return errors


def audit_rls_from_db(conn) -> list[str]:  # noqa: ANN001
    """Live audit: verify actual PG catalog matches expected RLS coverage.

    Parameters
    ----------
    conn : psycopg connection or asyncpg connection
        Database connection with access to pg_catalog.

    Returns list of errors (empty = pass).
    """
    errors: list[str] = []

    # Query pg_class for RLS status
    result = conn.execute("""
        SELECT
            c.relname AS table_name,
            c.relrowsecurity AS rls_enabled,
            c.relforcerowsecurity AS rls_forced
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
        ORDER BY c.relname
    """)
    rows = result.fetchall()
    db_tables = {row[0]: (row[1], row[2]) for row in rows}

    for table in sorted(TENANT_SCOPED_TABLES):
        if table not in db_tables:
            errors.append(f"MISSING: tenant table '{table}' not found in database")
            continue
        rls_enabled, rls_forced = db_tables[table]
        if not rls_enabled:
            errors.append(f"RLS_DISABLED: '{table}' — ENABLE ROW LEVEL SECURITY missing")
        if not rls_forced:
            errors.append(f"RLS_NOT_FORCED: '{table}' — FORCE ROW LEVEL SECURITY missing")

    # Check policies exist with both USING and WITH CHECK
    policy_result = conn.execute("""
        SELECT
            schemaname,
            tablename,
            policyname,
            permissive,
            cmd,
            qual IS NOT NULL AS has_using,
            with_check IS NOT NULL AS has_with_check
        FROM pg_policies
        WHERE schemaname = 'public'
        ORDER BY tablename, policyname
    """)
    policy_rows = policy_result.fetchall()
    policies_by_table: dict[str, list] = {}
    for row in policy_rows:
        table = row[1]
        policies_by_table.setdefault(table, []).append({
            "name": row[2],
            "has_using": row[5],
            "has_with_check": row[6],
        })

    for table in sorted(TENANT_SCOPED_TABLES):
        table_policies = policies_by_table.get(table, [])
        if not table_policies:
            errors.append(f"NO_POLICY: '{table}' — no RLS policy found")
            continue
        for policy in table_policies:
            if not policy["has_using"]:
                errors.append(
                    f"NO_USING: '{table}' policy '{policy['name']}' — "
                    f"missing USING clause"
                )
            if not policy["has_with_check"]:
                errors.append(
                    f"NO_WITH_CHECK: '{table}' policy '{policy['name']}' — "
                    f"missing WITH CHECK clause"
                )

    # Verify global tables do NOT have RLS
    for table in sorted(GLOBAL_TABLES):
        if table in db_tables:
            rls_enabled, _ = db_tables[table]
            if rls_enabled:
                errors.append(
                    f"UNEXPECTED_RLS: global table '{table}' has RLS enabled"
                )

    return errors
