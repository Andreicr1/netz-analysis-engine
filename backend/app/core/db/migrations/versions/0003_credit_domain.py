"""Credit domain: analytical tables, AI modules, RLS policies.

Creates ~60 credit domain tables + RLS policies on ALL tenant-scoped tables
(including wealth tables from 0002 that were missing RLS).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


# ── All tenant-scoped tables that need RLS ────────────────────────
_RLS_TABLES = [
    # From 0001
    "audit_events",
    # From 0002 (wealth)
    "funds_universe", "nav_timeseries", "fund_risk_metrics",
    "portfolio_snapshots", "strategic_allocation", "tactical_positions",
    "rebalance_events", "lipper_ratings", "backtest_runs",
    # From 0003 — credit core
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
    # From 0003 — AI / intelligence modules
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
]

_ENUM_TYPES = [
    "deal_type_enum", "deal_stage_enum", "rejection_code_enum",
    "asset_type_enum", "strategy_enum",
    "obligation_type_enum", "obligation_status_enum",
    "alert_type_enum", "alert_severity_enum", "action_status_enum",
    "reporting_frequency_enum",
    "document_domain_enum", "document_ingestion_status_enum",
    "report_pack_status_enum", "nav_snapshot_status_enum",
    "monthly_pack_type_enum", "valuation_method_enum", "report_section_type_enum",
    "intelligence_status_enum",
]


def _id() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True)


def _org() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True)


def _fund() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("fund_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("access_level", sa.String(32), server_default="internal", index=True),
    ]


def _audit() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
    ]


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    #  PHASE A: Enum types
    # ═══════════════════════════════════════════════════════════════
    bind = op.get_bind()

    sa.Enum("DIRECT_LOAN", "FUND_INVESTMENT", "EQUITY_STAKE", "SPV_NOTE",
            name="deal_type_enum").create(bind, checkfirst=True)
    sa.Enum("INTAKE", "QUALIFIED", "IC_REVIEW", "CONDITIONAL", "APPROVED",
            "CONVERTED_TO_ASSET", "REJECTED", "CLOSED",
            name="deal_stage_enum").create(bind, checkfirst=True)
    sa.Enum("OUT_OF_MANDATE", "TICKET_TOO_SMALL", "JURISDICTION_EXCLUDED",
            "INSUFFICIENT_RETURN", "WEAK_CREDIT_PROFILE", "NO_COLLATERAL",
            name="rejection_code_enum").create(bind, checkfirst=True)
    sa.Enum("DIRECT_LOAN", "FUND_INVESTMENT", "EQUITY_STAKE", "SPV_NOTE",
            name="asset_type_enum").create(bind, checkfirst=True)
    sa.Enum("CORE_DIRECT_LENDING", "OPPORTUNISTIC", "DISTRESSED", "VENTURE_DEBT", "FUND_OF_FUNDS",
            name="strategy_enum").create(bind, checkfirst=True)
    sa.Enum("NAV_REPORT", "COVENANT_TEST", "FINANCIAL_STATEMENT", "AUDIT_REPORT", "COMPLIANCE_CERT",
            name="obligation_type_enum").create(bind, checkfirst=True)
    sa.Enum("OPEN", "FULFILLED", "OVERDUE", "WAIVED",
            name="obligation_status_enum").create(bind, checkfirst=True)
    sa.Enum("OBLIGATION_OVERDUE", "COVENANT_BREACH", "NAV_DEVIATION", "MANUAL",
            name="alert_type_enum").create(bind, checkfirst=True)
    sa.Enum("LOW", "MEDIUM", "HIGH", "CRITICAL",
            name="alert_severity_enum").create(bind, checkfirst=True)
    sa.Enum("OPEN", "IN_PROGRESS", "CLOSED",
            name="action_status_enum").create(bind, checkfirst=True)
    sa.Enum("MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUAL",
            name="reporting_frequency_enum").create(bind, checkfirst=True)
    sa.Enum("OFFERING", "AUDIT", "BANK", "KYC", "MANDATES", "CORPORATE",
            "DEALS_MANAGERS", "MARKETING", "PROPOSALS", "ADMIN", "BOARD",
            "INVESTMENT_MANAGER", "FEEDER", "OTHER",
            name="document_domain_enum").create(bind, checkfirst=True)
    sa.Enum("PENDING", "PROCESSING", "INDEXED", "FAILED",
            name="document_ingestion_status_enum").create(bind, checkfirst=True)
    sa.Enum("DRAFT", "GENERATED", "PUBLISHED",
            name="report_pack_status_enum").create(bind, checkfirst=True)
    sa.Enum("DRAFT", "FINALIZED", "PUBLISHED",
            name="nav_snapshot_status_enum").create(bind, checkfirst=True)
    sa.Enum("INVESTOR_REPORT", "AUDITOR_PACK", "ADMIN_PACKAGE",
            name="monthly_pack_type_enum").create(bind, checkfirst=True)
    sa.Enum("AMORTIZED_COST", "FAIR_VALUE", "MARK_TO_MARKET", "THIRD_PARTY_APPRAISAL",
            name="valuation_method_enum").create(bind, checkfirst=True)
    sa.Enum("NAV_SUMMARY", "PORTFOLIO_EXPOSURE", "OBLIGATIONS", "ACTIONS",
            name="report_section_type_enum").create(bind, checkfirst=True)
    op.execute("CREATE TYPE intelligence_status_enum AS ENUM ('PENDING','PROCESSING','READY','FAILED')")

    # ═══════════════════════════════════════════════════════════════
    #  PHASE B: Independent tables
    # ═══════════════════════════════════════════════════════════════

    op.create_table("portfolio_assets", _id(), _org(), *_fund(),
        sa.Column("asset_type", postgresql.ENUM(name="asset_type_enum", create_type=False), nullable=False, index=True),
        sa.Column("strategy", postgresql.ENUM(name="strategy_enum", create_type=False), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False, index=True), *_audit())

    op.create_table("alerts", _id(), _org(),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("obligation_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("alert_type", postgresql.ENUM(name="alert_type_enum", create_type=False), nullable=False),
        sa.Column("severity", postgresql.ENUM(name="alert_severity_enum", create_type=False), nullable=False), *_audit())

    op.create_table("asset_obligations", _id(), _org(),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("obligation_type", postgresql.ENUM(name="obligation_type_enum", create_type=False), nullable=False),
        sa.Column("status", postgresql.ENUM(name="obligation_status_enum", create_type=False), nullable=False, server_default="OPEN"),
        sa.Column("due_date", sa.Date(), nullable=False), *_audit())

    op.create_table("deal_qualifications", _id(), _org(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False), *_audit())

    op.create_table("ic_memos", _id(), _org(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("risks", sa.Text(), nullable=True),
        sa.Column("mitigants", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.String(20), nullable=True),
        sa.Column("conditions", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("memo_blob_url", sa.Text(), nullable=True),
        sa.Column("condition_history", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("adobe_sign_agreement_id", sa.String(255), nullable=True),
        sa.Column("committee_members", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("committee_votes", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("esignature_status", sa.String(32), nullable=True), *_audit())

    op.create_table("evidence_documents", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("action_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("report_pack_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("blob_uri", sa.String(500), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True), *_audit())

    op.create_table("nav_snapshots", _id(), _org(), *_fund(),
        sa.Column("period_month", sa.String(7), nullable=False, index=True),
        sa.Column("nav_total_usd", sa.Numeric(20, 2), nullable=False),
        sa.Column("cash_balance_usd", sa.Numeric(20, 2), nullable=False),
        sa.Column("assets_value_usd", sa.Numeric(20, 2), nullable=False),
        sa.Column("liabilities_usd", sa.Numeric(20, 2), nullable=False),
        sa.Column("status", postgresql.ENUM(name="nav_snapshot_status_enum", create_type=False), nullable=False, index=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by", sa.String(128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(128), nullable=True), *_audit(),
        sa.Index("ix_nav_snapshots_fund_period", "fund_id", "period_month"),
        sa.Index("ix_nav_snapshots_fund_status", "fund_id", "status"))

    op.create_table("investor_statements", _id(), _org(), *_fund(),
        sa.Column("investor_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("period_month", sa.String(7), nullable=False, index=True),
        sa.Column("commitment", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("capital_called", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("distributions", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("ending_balance", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("blob_path", sa.String(800), nullable=False), *_audit(),
        sa.Index("ix_investor_statements_fund_period", "fund_id", "period_month"))

    op.create_table("report_schedules", _id(), _org(), *_fund(),
        sa.Column("name", sa.String(300), nullable=False, index=True),
        sa.Column("report_type", sa.String(64), nullable=False, index=True),
        sa.Column("frequency", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.True_(), index=True),
        sa.Column("next_run_date", sa.Date(), nullable=True, index=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(32), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("auto_distribute", sa.Boolean(), nullable=False, server_default=sa.False_()),
        sa.Column("distribution_list", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True), *_audit(),
        sa.Index("ix_report_schedules_fund_active", "fund_id", "is_active"),
        sa.Index("ix_report_schedules_next_run", "next_run_date", "is_active"))

    op.create_table("report_runs", _id(), _org(), *_fund(),
        sa.Column("schedule_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("report_type", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_blob_uri", sa.String(800), nullable=True),
        sa.Column("output_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("distributed_to", postgresql.JSONB(), nullable=True),
        sa.Column("distributed_at", sa.DateTime(timezone=True), nullable=True), *_audit(),
        sa.Index("ix_report_runs_schedule", "schedule_id", "started_at"),
        sa.Index("ix_report_runs_fund_type", "fund_id", "report_type"))

    # ═══════════════════════════════════════════════════════════════
    #  PHASE C: Documents + Pipeline foundations
    # ═══════════════════════════════════════════════════════════════

    op.create_table("documents", _id(), _org(), *_fund(),
        sa.Column("source", sa.String(32), nullable=True, index=True),
        sa.Column("document_type", sa.String(100), nullable=False, index=True),
        sa.Column("title", sa.String(300), nullable=False, index=True),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False, index=True),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("root_folder", sa.String(200), nullable=True, index=True),
        sa.Column("folder_path", sa.String(800), nullable=True, index=True),
        sa.Column("domain", postgresql.ENUM(name="document_domain_enum", create_type=False), nullable=True, index=True),
        sa.Column("blob_uri", sa.String(800), nullable=True),
        sa.Column("content_type", sa.String(200), nullable=True),
        sa.Column("original_filename", sa.String(512), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True, index=True), *_audit(),
        sa.UniqueConstraint("fund_id", "root_folder", "folder_path", "title", name="uq_documents_fund_folder_title"))
    op.create_index("ix_documents_fund_type", "documents", ["fund_id", "document_type"])

    op.create_table("document_root_folders", _id(), _org(), *_fund(),
        sa.Column("name", sa.String(200), nullable=False, index=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true", index=True), *_audit(),
        sa.UniqueConstraint("fund_id", "name", name="uq_document_root_folders_fund_name"))

    op.create_table("pipeline_qualification_rules", _id(), _org(), *_fund(),
        sa.Column("name", sa.String(200), nullable=False, index=True),
        sa.Column("version", sa.String(32), server_default="v1", nullable=False, index=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true", index=True),
        sa.Column("rule_config", sa.JSON(), nullable=False), *_audit())

    # pipeline_deals — approved_deal_id deferred (circular with deals)
    op.create_table("pipeline_deals", _id(), _org(), *_fund(),
        sa.Column("deal_name", sa.String(300), nullable=True, index=True),
        sa.Column("sponsor_name", sa.String(300), nullable=True, index=True),
        sa.Column("lifecycle_stage", sa.String(32), nullable=True, index=True),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("deal_folder_path", sa.String(800), nullable=True, index=True),
        sa.Column("transition_target_container", sa.String(120), nullable=True),
        sa.Column("intelligence_history", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(300), nullable=False, index=True),
        sa.Column("borrower_name", sa.String(300), nullable=True, index=True),
        sa.Column("requested_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("stage", sa.String(64), nullable=False, index=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false", index=True),
        sa.Column("rejection_reason_code", sa.String(64), nullable=True, index=True),
        sa.Column("rejection_rationale", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_risk_flags", postgresql.JSONB(), nullable=True),
        sa.Column("ai_key_terms", postgresql.JSONB(), nullable=True),
        sa.Column("research_output", postgresql.JSONB(), nullable=True),
        sa.Column("marketing_thesis", postgresql.JSONB(), nullable=True),
        sa.Column("intelligence_status", postgresql.ENUM(name="intelligence_status_enum", create_type=False),
                  nullable=False, server_default="PENDING", index=True),
        sa.Column("intelligence_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_deal_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column("approval_notes", sa.Text(), nullable=True), *_audit())
    op.create_index("ix_pipeline_deals_fund_stage", "pipeline_deals", ["fund_id", "stage"])

    # deals — pipeline_deal_id deferred (circular with pipeline_deals)
    op.create_table("deals", _id(), _org(), *_fund(),
        sa.Column("deal_type", postgresql.ENUM(name="deal_type_enum", create_type=False), nullable=False),
        sa.Column("stage", postgresql.ENUM(name="deal_stage_enum", create_type=False), nullable=False, server_default="INTAKE"),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sponsor_name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rejection_code", postgresql.ENUM(name="rejection_code_enum", create_type=False), nullable=True),
        sa.Column("rejection_notes", sa.Text(), nullable=True),
        sa.Column("monitoring_output", postgresql.JSONB(), nullable=True),
        sa.Column("marketing_thesis", postgresql.JSONB(), nullable=True),
        sa.Column("pipeline_deal_id", sa.Uuid(as_uuid=True), nullable=True, index=True), *_audit())

    # ═══════════════════════════════════════════════════════════════
    #  PHASE D: FK-dependent tables
    # ═══════════════════════════════════════════════════════════════

    op.create_table("document_versions", _id(), _org(), *_fund(),
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False, index=True),
        sa.Column("blob_uri", sa.String(800), nullable=True),
        sa.Column("checksum", sa.String(128), nullable=True),
        sa.Column("file_size_bytes", sa.Numeric(20, 0), nullable=True),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default="false", index=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("content_type", sa.String(200), nullable=True),
        sa.Column("extracted_text_blob_uri", sa.String(800), nullable=True),
        sa.Column("ingest_status", sa.String(32), nullable=False, server_default="PENDING", index=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingest_error", sa.JSON(), nullable=True),
        sa.Column("blob_path", sa.String(800), nullable=True, index=True),
        sa.Column("uploaded_by", sa.String(200), nullable=True, index=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("ingestion_status", postgresql.ENUM(name="document_ingestion_status_enum", create_type=False),
                  nullable=False, server_default="PENDING", index=True), *_audit())
    op.create_index("ix_doc_versions_doc_ver", "document_versions", ["document_id", "version_number"], unique=True)

    op.create_table("document_access_policies", _id(), _org(), *_fund(),
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(32), nullable=True, index=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true", index=True),
        sa.Column("rules", sa.JSON(), nullable=True), *_audit())

    op.create_table("document_reviews", _id(), _org(), *_fund(),
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("document_version_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("title", sa.String(500), nullable=False, index=True),
        sa.Column("document_type", sa.String(100), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="SUBMITTED", index=True),
        sa.Column("priority", sa.String(16), nullable=False, server_default="MEDIUM", index=True),
        sa.Column("submitted_by", sa.String(200), nullable=False, index=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True, index=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("final_decision", sa.String(32), nullable=True),
        sa.Column("decided_by", sa.String(200), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("routing_basis", sa.String(200), nullable=True),
        sa.Column("classification_confidence", sa.Float(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True), *_audit())
    op.create_index("ix_doc_reviews_fund_status", "document_reviews", ["fund_id", "status"])
    op.create_index("ix_doc_reviews_fund_doc", "document_reviews", ["fund_id", "document_id"])
    op.create_index("ix_doc_reviews_submitted_by", "document_reviews", ["submitted_by", "status"])

    op.create_table("monthly_report_packs", _id(), _org(), *_fund(),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("nav_snapshot_id", sa.Uuid(as_uuid=True), sa.ForeignKey("nav_snapshots.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("blob_path", sa.String(800), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("generated_by", sa.String(128), nullable=True),
        sa.Column("pack_type", postgresql.ENUM(name="monthly_pack_type_enum", create_type=False), nullable=True, index=True),
        sa.Column("status", postgresql.ENUM(name="report_pack_status_enum", create_type=False), nullable=False, server_default="DRAFT"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=False, server_default="Monthly Report Pack"), *_audit())

    op.create_table("actions", _id(), _org(),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("alert_id", sa.Uuid(as_uuid=True), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", postgresql.ENUM(name="action_status_enum", create_type=False), nullable=False, server_default="OPEN"),
        sa.Column("evidence_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("evidence_notes", sa.String(500), nullable=True), *_audit())

    op.create_table("fund_investments",
        sa.Column("asset_id", sa.Uuid(as_uuid=True), sa.ForeignKey("portfolio_assets.id", ondelete="CASCADE"), primary_key=True),
        _org(),
        sa.Column("manager_name", sa.String(255), nullable=False),
        sa.Column("underlying_fund_name", sa.String(255), nullable=False),
        sa.Column("reporting_frequency", postgresql.ENUM(name="reporting_frequency_enum", create_type=False), nullable=False),
        sa.Column("nav_source", sa.String(255), nullable=True), *_audit())

    op.create_table("pipeline_deal_documents", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("document_type", sa.String(64), nullable=False, index=True),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("status", sa.String(32), server_default="registered", nullable=False, index=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("blob_container", sa.Text(), nullable=True),
        sa.Column("blob_path", sa.Text(), nullable=True),
        sa.Column("authority", sa.Text(), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True), *_audit())
    op.create_index("uq_deal_doc_blob_path", "pipeline_deal_documents", ["deal_id", "blob_path"], unique=True)

    op.create_table("pipeline_deal_stage_history", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("from_stage", sa.String(64), nullable=True),
        sa.Column("to_stage", sa.String(64), nullable=False, index=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("rationale", sa.Text(), nullable=True), *_audit())

    op.create_table("pipeline_deal_decisions", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("outcome", sa.String(32), nullable=False, index=True),
        sa.Column("reason_code", sa.String(64), nullable=True, index=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True), *_audit())

    op.create_table("pipeline_qualification_results", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rule_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_qualification_rules.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("result", sa.String(16), nullable=False, index=True),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True), *_audit())

    op.create_table("deal_cashflows", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("deals.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("flow_type", sa.String(64), nullable=False, index=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("flow_date", sa.Date(), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference", sa.String(120), nullable=True), *_audit())
    op.create_index("ix_deal_cashflows_deal_fund", "deal_cashflows", ["deal_id", "fund_id"])
    op.create_index("ix_deal_cashflows_flow_date_type", "deal_cashflows", ["flow_date", "flow_type"])

    op.create_table("deal_events", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("pipeline_deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("event_type", sa.String(64), nullable=False, index=True),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True), *_audit())
    op.create_index("ix_deal_events_fund_type", "deal_events", ["fund_id", "event_type"])
    op.create_index("ix_deal_events_created", "deal_events", ["created_at"])

    # ═══════════════════════════════════════════════════════════════
    #  PHASE E: Deeper FK-dependent tables
    # ═══════════════════════════════════════════════════════════════

    op.create_table("document_chunks", _id(), _org(), *_fund(),
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False, index=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding_vector", sa.JSON(), nullable=True),
        sa.Column("version_checksum", sa.String(128), nullable=True, index=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True), *_audit(),
        sa.UniqueConstraint("version_id", "chunk_index", name="uq_document_chunks_version_chunk_index"))
    op.create_index("ix_document_chunks_fund_doc_ver", "document_chunks", ["fund_id", "document_id", "version_id"])

    op.create_table("review_assignments", _id(), _org(), *_fund(),
        sa.Column("review_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_reviews.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("reviewer_actor_id", sa.String(200), nullable=False, index=True),
        sa.Column("reviewer_role", sa.String(64), nullable=True, index=True),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("decision", sa.String(32), nullable=True, index=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True), *_audit())
    op.create_index("ix_review_assign_reviewer", "review_assignments", ["reviewer_actor_id", "decision"])
    op.create_index("ix_review_assign_review_round", "review_assignments", ["review_id", "round_number"])

    op.create_table("review_checklist_items", _id(), _org(), *_fund(),
        sa.Column("review_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_reviews.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category", sa.String(100), nullable=True, index=True),
        sa.Column("label", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_checked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("checked_by", sa.String(200), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ai_finding", postgresql.JSONB(), nullable=True), *_audit())
    op.create_index("ix_review_checklist_review", "review_checklist_items", ["review_id", "sort_order"])

    # review_events — NO AuditMeta, own created_at
    op.create_table("review_events", _id(), _org(), *_fund(),
        sa.Column("review_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_reviews.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("event_type", sa.String(64), nullable=False, index=True),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_review_events_review", "review_events", ["review_id", "created_at"])

    # report_pack_sections — Org only, NO Fund
    op.create_table("report_pack_sections", _id(), _org(),
        sa.Column("report_pack_id", sa.Uuid(as_uuid=True), sa.ForeignKey("monthly_report_packs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("section_type", postgresql.ENUM(name="report_section_type_enum", create_type=False), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False), *_audit())

    op.create_table("asset_valuation_snapshots", _id(), _org(), *_fund(),
        sa.Column("nav_snapshot_id", sa.Uuid(as_uuid=True), sa.ForeignKey("nav_snapshots.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("asset_type", sa.String(64), nullable=False, index=True),
        sa.Column("valuation_usd", sa.Numeric(20, 2), nullable=False),
        sa.Column("valuation_method", postgresql.ENUM(name="valuation_method_enum", create_type=False), nullable=False, index=True),
        sa.Column("supporting_document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="RESTRICT"), nullable=True, index=True), *_audit())
    op.create_index("ix_asset_valuation_snapshots_fund_nav", "asset_valuation_snapshots", ["fund_id", "nav_snapshot_id"])
    op.create_index("ix_asset_valuation_snapshots_nav_asset", "asset_valuation_snapshots", ["nav_snapshot_id", "asset_id"])

    # ═══════════════════════════════════════════════════════════════
    #  PHASE F: AI / Intelligence module tables
    # ═══════════════════════════════════════════════════════════════

    op.create_table("ai_queries", _id(), _org(), *_fund(),
        sa.Column("actor_id", sa.String(200), nullable=False, index=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False, index=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True), *_audit())

    op.create_table("ai_questions", _id(), _org(), *_fund(),
        sa.Column("actor_id", sa.String(200), nullable=False, index=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("root_folder", sa.String(200), nullable=True, index=True),
        sa.Column("top_k", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("request_id", sa.String(64), nullable=False, index=True),
        sa.Column("retrieved_chunk_ids", sa.JSON(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True), *_audit())

    op.create_table("document_registry", _id(), _org(), *_fund(),
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("version_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("blob_path", sa.String(800), nullable=False),
        sa.Column("container_name", sa.String(120), nullable=False, index=True),
        sa.Column("domain_tag", sa.String(80), nullable=False, index=True),
        sa.Column("authority", sa.String(20), nullable=False, index=True),
        sa.Column("shareability", sa.String(40), nullable=False, index=True),
        sa.Column("detected_doc_type", sa.String(64), nullable=True, index=True),
        sa.Column("lifecycle_stage", sa.String(20), nullable=False, index=True),
        sa.Column("last_ingested_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("checksum", sa.String(128), nullable=True),
        sa.Column("etag", sa.String(200), nullable=True),
        sa.Column("last_modified_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("root_folder", sa.String(200), nullable=True, index=True),
        sa.Column("folder_path", sa.String(800), nullable=True, index=True),
        sa.Column("title", sa.String(300), nullable=False, index=True),
        sa.Column("institutional_type", sa.String(64), nullable=False, index=True),
        sa.Column("source_signals", sa.JSON(), nullable=True),
        sa.Column("classifier_version", sa.String(80), nullable=False, server_default="wave-ai1-v1"),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("data_latency", sa.Integer(), nullable=True),
        sa.Column("data_quality", sa.String(16), nullable=True, server_default="OK"), *_audit())
    op.create_index("ix_document_registry_fund_type", "document_registry", ["fund_id", "institutional_type"])
    op.create_index("ix_document_registry_fund_version", "document_registry", ["fund_id", "version_id"], unique=True)
    op.create_index("ix_document_registry_fund_container_blob", "document_registry", ["fund_id", "container_name", "blob_path"], unique=True)

    op.create_table("knowledge_entities", _id(), _org(), *_fund(),
        sa.Column("entity_type", sa.String(32), nullable=False, index=True),
        sa.Column("canonical_name", sa.String(300), nullable=False, index=True), *_audit())
    op.create_index("ix_knowledge_entities_fund_type_name", "knowledge_entities", ["fund_id", "entity_type", "canonical_name"], unique=True)

    op.create_table("manager_profiles", _id(), _org(), *_fund(),
        sa.Column("name", sa.String(200), nullable=False, index=True),
        sa.Column("strategy", sa.String(200), nullable=False),
        sa.Column("region", sa.String(120), nullable=False),
        sa.Column("vehicle_type", sa.String(120), nullable=False),
        sa.Column("declared_target_return", sa.String(40), nullable=True),
        sa.Column("reporting_cadence", sa.String(80), nullable=False),
        sa.Column("key_risks_declared", sa.JSON(), nullable=True),
        sa.Column("last_document_update", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_documents", sa.JSON(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("data_latency", sa.Integer(), nullable=True),
        sa.Column("data_quality", sa.String(16), nullable=True, server_default="OK"), *_audit())
    op.create_index("ix_manager_profiles_fund_name", "manager_profiles", ["fund_id", "name"], unique=True)

    op.create_table("obligation_register", _id(), _org(), *_fund(),
        sa.Column("obligation_id", sa.String(64), nullable=False, index=True),
        sa.Column("source", sa.String(40), nullable=False, index=True),
        sa.Column("obligation_text", sa.Text(), nullable=False),
        sa.Column("frequency", sa.String(40), nullable=False, index=True),
        sa.Column("due_rule", sa.String(300), nullable=False),
        sa.Column("responsible_party", sa.String(120), nullable=False),
        sa.Column("evidence_expected", sa.String(300), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, index=True),
        sa.Column("source_documents", sa.JSON(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("data_latency", sa.Integer(), nullable=True),
        sa.Column("data_quality", sa.String(16), nullable=True, server_default="OK"), *_audit())
    op.create_index("ix_obligation_register_fund_obligation_id", "obligation_register", ["fund_id", "obligation_id"], unique=True)

    op.create_table("governance_alerts", _id(), _org(), *_fund(),
        sa.Column("alert_id", sa.String(80), nullable=False, index=True),
        sa.Column("domain", sa.String(40), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, index=True),
        sa.Column("entity_ref", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("actionable_next_step", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("data_latency", sa.Integer(), nullable=True),
        sa.Column("data_quality", sa.String(16), nullable=True, server_default="OK"), *_audit())
    op.create_index("ix_governance_alerts_fund_alert_id", "governance_alerts", ["fund_id", "alert_id"], unique=True)

    op.create_table("ai_responses", _id(), _org(), *_fund(),
        sa.Column("query_id", sa.Uuid(as_uuid=True), sa.ForeignKey("ai_queries.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("model_version", sa.String(80), nullable=False, index=True),
        sa.Column("prompt", sa.JSON(), nullable=False),
        sa.Column("retrieval_sources", sa.JSON(), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True), *_audit())
    op.create_index("ix_ai_responses_fund_query", "ai_responses", ["fund_id", "query_id"])

    op.create_table("ai_answers", _id(), _org(), *_fund(),
        sa.Column("question_id", sa.Uuid(as_uuid=True), sa.ForeignKey("ai_questions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("model_version", sa.String(80), nullable=False, index=True),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("prompt", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True), *_audit())
    op.create_index("ix_ai_answers_fund_question", "ai_answers", ["fund_id", "question_id"])

    op.create_table("ai_answer_citations", _id(), _org(), *_fund(),
        sa.Column("answer_id", sa.Uuid(as_uuid=True), sa.ForeignKey("ai_answers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("chunk_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("source_blob", sa.String(800), nullable=True), *_audit())
    op.create_index("ix_ai_answer_citations_fund_answer", "ai_answer_citations", ["fund_id", "answer_id"])

    op.create_table("document_classifications", _id(), _org(), *_fund(),
        sa.Column("doc_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_registry.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("doc_type", sa.String(64), nullable=False, index=True),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("classification_basis", sa.String(120), nullable=False), *_audit())
    op.create_index("ix_document_classifications_fund_doc", "document_classifications", ["fund_id", "doc_id"], unique=True)

    op.create_table("document_governance_profile", _id(), _org(), *_fund(),
        sa.Column("doc_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_registry.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("resolved_authority", sa.String(20), nullable=False, index=True),
        sa.Column("binding_scope", sa.String(40), nullable=False, index=True),
        sa.Column("shareability_final", sa.String(40), nullable=False),
        sa.Column("jurisdiction", sa.String(120), nullable=True), *_audit())
    op.create_index("ix_document_governance_profile_fund_doc", "document_governance_profile", ["fund_id", "doc_id"], unique=True)

    op.create_table("knowledge_anchors", _id(), _org(), *_fund(),
        sa.Column("doc_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_registry.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("anchor_type", sa.String(80), nullable=False, index=True),
        sa.Column("anchor_value", sa.String(500), nullable=False),
        sa.Column("source_snippet", sa.Text(), nullable=True),
        sa.Column("page_reference", sa.String(80), nullable=True), *_audit())
    op.create_index("ix_knowledge_anchors_fund_doc", "knowledge_anchors", ["fund_id", "doc_id"])

    op.create_table("knowledge_links", _id(), _org(), *_fund(),
        sa.Column("source_document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_registry.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("target_entity_id", sa.Uuid(as_uuid=True), sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("link_type", sa.String(40), nullable=False, index=True),
        sa.Column("authority_tier", sa.String(20), nullable=False, index=True),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("evidence_snippet", sa.Text(), nullable=True), *_audit())
    op.create_index("ix_knowledge_links_fund_source_target_type", "knowledge_links",
                    ["fund_id", "source_document_id", "target_entity_id", "link_type"], unique=True)

    op.create_table("obligation_evidence_map", _id(), _org(), *_fund(),
        sa.Column("obligation_id", sa.Uuid(as_uuid=True), sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("evidence_document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_registry.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("satisfaction_status", sa.String(20), nullable=False, index=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False, index=True), *_audit())
    op.create_index("ix_obligation_evidence_map_fund_obligation", "obligation_evidence_map", ["fund_id", "obligation_id"], unique=True)

    op.create_table("deal_documents", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("doc_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_registry.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("doc_type", sa.String(64), nullable=False, index=True),
        sa.Column("confidence_score", sa.Integer(), nullable=False), *_audit())
    op.create_index("ix_deal_documents_fund_deal_doc", "deal_documents", ["fund_id", "deal_id", "doc_id"], unique=True)

    op.create_table("deal_intelligence_profiles", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("strategy_type", sa.String(80), nullable=False, index=True),
        sa.Column("geography", sa.String(120), nullable=True),
        sa.Column("sector_focus", sa.String(160), nullable=True),
        sa.Column("target_return", sa.String(60), nullable=True),
        sa.Column("risk_band", sa.String(20), nullable=False, index=True),
        sa.Column("liquidity_profile", sa.String(80), nullable=True),
        sa.Column("capital_structure_type", sa.String(80), nullable=True),
        sa.Column("key_risks", sa.JSON(), nullable=True),
        sa.Column("differentiators", sa.JSON(), nullable=True),
        sa.Column("summary_ic_ready", sa.Text(), nullable=False),
        sa.Column("last_ai_refresh", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True), *_audit())
    op.create_index("ix_deal_intelligence_profiles_fund_deal", "deal_intelligence_profiles", ["fund_id", "deal_id"], unique=True)

    op.create_table("deal_risk_flags", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("risk_type", sa.String(40), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, index=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("source_document", sa.String(800), nullable=True), *_audit())
    op.create_index("ix_deal_risk_flags_fund_deal", "deal_risk_flags", ["fund_id", "deal_id"])

    op.create_table("deal_ic_briefs", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("opportunity_overview", sa.Text(), nullable=False),
        sa.Column("return_profile", sa.Text(), nullable=False),
        sa.Column("downside_case", sa.Text(), nullable=False),
        sa.Column("risk_summary", sa.Text(), nullable=False),
        sa.Column("comparison_peer_funds", sa.Text(), nullable=False),
        sa.Column("recommendation_signal", sa.String(20), nullable=False, index=True), *_audit())
    op.create_index("ix_deal_ic_briefs_fund_deal", "deal_ic_briefs", ["fund_id", "deal_id"], unique=True)

    op.create_table("pipeline_alerts", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("alert_type", sa.String(64), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resolved_flag", sa.Boolean(), nullable=False, server_default="false"), *_audit())
    op.create_index("ix_pipeline_alerts_fund_deal", "pipeline_alerts", ["fund_id", "deal_id"])

    op.create_table("active_investments", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("deals.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("primary_document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_registry.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("investment_name", sa.String(300), nullable=False, index=True),
        sa.Column("manager_name", sa.String(300), nullable=True, index=True),
        sa.Column("lifecycle_status", sa.String(40), nullable=False, index=True),
        sa.Column("source_container", sa.String(120), nullable=False, index=True),
        sa.Column("source_folder", sa.String(400), nullable=False, index=True),
        sa.Column("strategy_type", sa.String(120), nullable=True),
        sa.Column("target_return", sa.String(60), nullable=True),
        sa.Column("committed_capital_usd", sa.Float(), nullable=True),
        sa.Column("deployed_capital_usd", sa.Float(), nullable=True),
        sa.Column("current_nav_usd", sa.Float(), nullable=True),
        sa.Column("last_monitoring_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("transition_log", sa.JSON(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("data_latency", sa.Integer(), nullable=True),
        sa.Column("data_quality", sa.String(16), nullable=True, server_default="OK"), *_audit())
    op.create_index("ix_active_investments_fund_name", "active_investments", ["fund_id", "investment_name"])
    op.create_index("ix_active_investments_fund_source_folder", "active_investments", ["fund_id", "source_folder"], unique=True)

    op.create_table("investment_memorandum_drafts", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version_tag", sa.String(40), nullable=False, index=True),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("opportunity_overview", sa.Text(), nullable=False),
        sa.Column("investment_terms_section", sa.Text(), nullable=False),
        sa.Column("corporate_structure_section", sa.Text(), nullable=False),
        sa.Column("return_profile_section", sa.Text(), nullable=False),
        sa.Column("downside_case_section", sa.Text(), nullable=False),
        sa.Column("risk_summary_section", sa.Text(), nullable=False),
        sa.Column("peer_comparison_section", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.String(20), nullable=False, index=True),
        sa.Column("recommendation_rationale", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="false", index=True), *_audit())
    op.create_index("ix_im_drafts_fund_deal", "investment_memorandum_drafts", ["fund_id", "deal_id"])

    op.create_table("memo_evidence_packs", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version_tag", sa.String(40), nullable=False, index=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="false", index=True), *_audit())
    op.create_index("ix_memo_evidence_packs_fund_deal", "memo_evidence_packs", ["fund_id", "deal_id"])

    op.create_table("deal_underwriting_artifacts", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("evidence_pack_hash", sa.String(128), nullable=True),
        sa.Column("recommendation", sa.String(20), nullable=False, index=True),
        sa.Column("confidence_level", sa.String(20), nullable=False, index=True),
        sa.Column("risk_band", sa.String(20), nullable=False, index=True),
        sa.Column("missing_documents", sa.JSON(), nullable=True),
        sa.Column("critic_findings", sa.JSON(), nullable=True),
        sa.Column("policy_breaches", sa.JSON(), nullable=True),
        sa.Column("chapters_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true", index=True), *_audit())
    op.create_index("ix_underwriting_artifacts_fund_deal", "deal_underwriting_artifacts", ["fund_id", "deal_id"])
    op.create_index("ix_underwriting_artifacts_active", "deal_underwriting_artifacts", ["deal_id", "is_active"])

    # ═══════════════════════════════════════════════════════════════
    #  PHASE G: Deeper dependent tables
    # ═══════════════════════════════════════════════════════════════

    op.create_table("memo_chapters", _id(), _org(), *_fund(),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("evidence_pack_id", sa.Uuid(as_uuid=True), sa.ForeignKey("memo_evidence_packs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("chapter_tag", sa.String(60), nullable=False),
        sa.Column("chapter_title", sa.String(200), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("version_tag", sa.String(40), nullable=False, index=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("token_count_input", sa.Integer(), nullable=True),
        sa.Column("token_count_output", sa.Integer(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="false", index=True), *_audit(),
        sa.UniqueConstraint("deal_id", "version_tag", "chapter_number", name="uq_chapter_deal_version_num"))
    op.create_index("ix_memo_chapters_fund_deal_num", "memo_chapters", ["fund_id", "deal_id", "chapter_number"])

    op.create_table("performance_drift_flags", _id(), _org(), *_fund(),
        sa.Column("investment_id", sa.Uuid(as_uuid=True), sa.ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("metric_name", sa.String(120), nullable=False, index=True),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("current_value", sa.Float(), nullable=True),
        sa.Column("drift_pct", sa.Float(), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False, index=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN", index=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True), *_audit())
    op.create_index("ix_performance_drift_flags_fund_investment", "performance_drift_flags", ["fund_id", "investment_id"])

    # covenant_status_register — stale FKs to covenants/tests/breaches removed
    op.create_table("covenant_status_register", _id(), _org(), *_fund(),
        sa.Column("investment_id", sa.Uuid(as_uuid=True), sa.ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("covenant_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("covenant_test_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("breach_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("covenant_name", sa.String(200), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, index=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_test_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True), *_audit())
    op.create_index("ix_covenant_status_register_fund_investment", "covenant_status_register", ["fund_id", "investment_id"])

    # cash_impact_flags — stale FK to cash_transactions removed
    op.create_table("cash_impact_flags", _id(), _org(), *_fund(),
        sa.Column("investment_id", sa.Uuid(as_uuid=True), sa.ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("transaction_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("impact_type", sa.String(80), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, index=True),
        sa.Column("estimated_impact_usd", sa.Float(), nullable=True),
        sa.Column("liquidity_days", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("resolved_flag", sa.Boolean(), nullable=False, server_default="false", index=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True), *_audit())
    op.create_index("ix_cash_impact_flags_fund_investment", "cash_impact_flags", ["fund_id", "investment_id"])

    op.create_table("investment_risk_registry", _id(), _org(), *_fund(),
        sa.Column("investment_id", sa.Uuid(as_uuid=True), sa.ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("risk_type", sa.String(80), nullable=False, index=True),
        sa.Column("risk_level", sa.String(20), nullable=False, index=True),
        sa.Column("trend", sa.String(20), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("source_evidence", sa.JSON(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True), *_audit())
    op.create_index("ix_investment_risk_registry_fund_investment", "investment_risk_registry", ["fund_id", "investment_id"])

    op.create_table("board_monitoring_briefs", _id(), _org(), *_fund(),
        sa.Column("investment_id", sa.Uuid(as_uuid=True), sa.ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("performance_view", sa.Text(), nullable=False),
        sa.Column("covenant_view", sa.Text(), nullable=False),
        sa.Column("liquidity_view", sa.Text(), nullable=False),
        sa.Column("risk_reclassification_view", sa.Text(), nullable=False),
        sa.Column("recommended_actions", sa.JSON(), nullable=True),
        sa.Column("last_generated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True), *_audit())
    op.create_index("ix_board_monitoring_briefs_fund_investment", "board_monitoring_briefs", ["fund_id", "investment_id"], unique=True)

    op.create_table("periodic_review_reports", _id(), _org(), *_fund(),
        sa.Column("investment_id", sa.Uuid(as_uuid=True), sa.ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_type", sa.String(32), nullable=False, index=True),
        sa.Column("overall_rating", sa.String(20), nullable=False, index=True),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("performance_assessment", sa.Text(), nullable=False),
        sa.Column("covenant_compliance", sa.Text(), nullable=False),
        sa.Column("material_changes", sa.JSON(), nullable=True),
        sa.Column("risk_evolution", sa.Text(), nullable=False),
        sa.Column("liquidity_assessment", sa.Text(), nullable=False),
        sa.Column("valuation_view", sa.Text(), nullable=False),
        sa.Column("recommended_actions", sa.JSON(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("model_version", sa.String(80), nullable=False), *_audit())
    op.create_index("ix_periodic_reviews_fund_investment", "periodic_review_reports", ["fund_id", "investment_id"])

    op.create_table("deal_conversion_events", _id(), _org(), *_fund(),
        sa.Column("pipeline_deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("portfolio_deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("active_investment_id", sa.Uuid(as_uuid=True), sa.ForeignKey("active_investments.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column("approval_notes", sa.Text(), nullable=True),
        sa.Column("conversion_metadata", postgresql.JSONB(), nullable=True), *_audit())
    op.create_index("ix_deal_conversion_events_fund_created", "deal_conversion_events", ["fund_id", "created_at"])

    # ═══════════════════════════════════════════════════════════════
    #  PHASE H: Global tables (no org_id, no RLS)
    # ═══════════════════════════════════════════════════════════════

    op.create_table("macro_snapshots", _id(),
        sa.Column("as_of_date", sa.Date(), nullable=False, unique=True, index=True),
        sa.Column("data_json", sa.JSON(), nullable=False),
        *_audit())

    op.create_table("deep_review_validation_runs", _id(),
        sa.Column("fund_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("v3_version_tag", sa.String(80), nullable=True),
        sa.Column("v4_version_tag", sa.String(80), nullable=True),
        sa.Column("delta_json", sa.JSON(), nullable=False),
        sa.Column("winner", sa.String(10), nullable=False, index=True),
        sa.Column("engine_score_json", sa.JSON(), nullable=True),
        sa.Column("aggregate_winner", sa.String(10), nullable=True),
        sa.Column("institutional_decision", sa.Text(), nullable=True), *_audit())
    op.create_index("ix_validation_runs_run_deal", "deep_review_validation_runs", ["run_id", "deal_id"])

    op.create_table("eval_runs", _id(),
        sa.Column("fund_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False, index=True),
        sa.Column("run_mode", sa.String(40), nullable=False, index=True),
        sa.Column("golden_set_name", sa.String(120), nullable=False, index=True),
        sa.Column("baseline_kind", sa.String(20), nullable=False, server_default="none"),
        sa.Column("baseline_run_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("prompt_manifest_hash", sa.String(128), nullable=True, index=True),
        sa.Column("model_manifest_hash", sa.String(128), nullable=True, index=True),
        sa.Column("provider_manifest_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, index=True, server_default="completed"),
        sa.Column("classification", sa.String(20), nullable=False, index=True, server_default="DATA_ISSUE"),
        sa.Column("classification_reason", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, index=True), *_audit())
    op.create_index("ix_eval_runs_run_id", "eval_runs", ["run_id"], unique=True)
    op.create_index("ix_eval_runs_fund_started", "eval_runs", ["fund_id", "started_at"])

    op.create_table("eval_chapter_scores", _id(),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("fund_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("deal_id", sa.Uuid(as_uuid=True), sa.ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("deal_name", sa.String(300), nullable=True),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("chapter_tag", sa.String(60), nullable=False, index=True),
        sa.Column("chapter_title", sa.String(200), nullable=False),
        sa.Column("is_applicable_layer1", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_applicable_layer2", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("layer1_json", sa.JSON(), nullable=True),
        sa.Column("layer2_json", sa.JSON(), nullable=True),
        sa.Column("layer3_json", sa.JSON(), nullable=True),
        sa.Column("layer4_json", sa.JSON(), nullable=True),
        sa.Column("aggregate_score_json", sa.JSON(), nullable=True),
        sa.Column("classification", sa.String(20), nullable=False, index=True, server_default="DATA_ISSUE"),
        sa.Column("classification_reason", sa.Text(), nullable=True),
        sa.Column("golden_version", sa.String(80), nullable=True),
        sa.Column("memo_version_tag", sa.String(80), nullable=True, index=True),
        sa.Column("model_version", sa.String(80), nullable=True, index=True),
        sa.Column("provider_info_json", sa.JSON(), nullable=True), *_audit(),
        sa.UniqueConstraint("run_id", "deal_id", "chapter_tag", name="uq_eval_run_deal_chapter"))
    op.create_index("ix_eval_chapter_scores_run_deal", "eval_chapter_scores", ["run_id", "deal_id"])
    op.create_index("ix_eval_chapter_scores_run_chapter", "eval_chapter_scores", ["run_id", "chapter_tag"])

    # ═══════════════════════════════════════════════════════════════
    #  PHASE I: Deferred FKs (circular references)
    # ═══════════════════════════════════════════════════════════════

    op.create_foreign_key("fk_pipeline_deals_approved_deal", "pipeline_deals", "deals",
                          ["approved_deal_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_deals_pipeline_deal", "deals", "pipeline_deals",
                          ["pipeline_deal_id"], ["id"], ondelete="SET NULL")

    # ═══════════════════════════════════════════════════════════════
    #  PHASE J: Row-Level Security policies
    # ═══════════════════════════════════════════════════════════════

    for t in _RLS_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY org_isolation ON {t} "
            f"USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid)) "
            f"WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))"
        )


def downgrade() -> None:
    for t in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")

    op.drop_constraint("fk_deals_pipeline_deal", "deals", type_="foreignkey")
    op.drop_constraint("fk_pipeline_deals_approved_deal", "pipeline_deals", type_="foreignkey")

    _drop = [
        "eval_chapter_scores", "eval_runs", "deep_review_validation_runs", "macro_snapshots",
        "deal_conversion_events",
        "periodic_review_reports", "board_monitoring_briefs",
        "investment_risk_registry", "cash_impact_flags", "covenant_status_register",
        "performance_drift_flags", "memo_chapters",
        "deal_underwriting_artifacts", "memo_evidence_packs", "investment_memorandum_drafts",
        "active_investments", "pipeline_alerts", "deal_ic_briefs", "deal_risk_flags",
        "deal_intelligence_profiles", "deal_documents",
        "obligation_evidence_map", "knowledge_links", "knowledge_anchors",
        "document_governance_profile", "document_classifications",
        "ai_answer_citations", "ai_answers", "ai_responses",
        "governance_alerts", "obligation_register", "manager_profiles",
        "knowledge_entities", "document_registry",
        "ai_questions", "ai_queries",
        "asset_valuation_snapshots", "report_pack_sections",
        "review_events", "review_checklist_items", "review_assignments",
        "document_chunks",
        "deal_events", "deal_cashflows",
        "pipeline_qualification_results", "pipeline_deal_decisions",
        "pipeline_deal_stage_history", "pipeline_deal_documents",
        "fund_investments", "actions",
        "monthly_report_packs", "document_reviews",
        "document_access_policies", "document_versions",
        "deals", "pipeline_deals", "pipeline_qualification_rules",
        "document_root_folders", "documents",
        "report_runs", "report_schedules", "investor_statements",
        "nav_snapshots", "evidence_documents",
        "ic_memos", "deal_qualifications",
        "asset_obligations", "alerts", "portfolio_assets",
    ]
    for t in _drop:
        op.drop_table(t)

    for e in _ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {e}")
