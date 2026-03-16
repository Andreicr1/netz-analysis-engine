"""Wealth analytical models: DD reports, chapters, universe approvals, model portfolios.

Creates 4 new tenant-scoped tables with RLS. Fixes pre-existing data integrity
issues on funds_universe.isin (cross-tenant unique) and portfolio_snapshots
(missing organization_id in unique constraint). Adds approval_status to
funds_universe for DD workflow integration.

depends_on: 0007 (governance_policy_seed).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# ── New tables that need RLS ──────────────────────────────────────
_NEW_RLS_TABLES = [
    "dd_reports",
    "dd_chapters",
    "universe_approvals",
    "model_portfolios",
]


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    #  PHASE A: Fix pre-existing data integrity issues
    # ═══════════════════════════════════════════════════════════════

    # A1: Drop global unique on funds_universe.isin — two orgs tracking
    # the same fund (e.g., BlackRock iShares) must not collide.
    # Replace with org-scoped partial unique index.
    op.drop_constraint("funds_universe_isin_key", "funds_universe", type_="unique")
    op.create_index(
        "uq_funds_universe_org_isin",
        "funds_universe",
        ["organization_id", "isin"],
        unique=True,
        postgresql_where=sa.text("isin IS NOT NULL"),
    )

    # A2: Fix portfolio_snapshots unique constraint — must include
    # organization_id so two orgs can have snapshots on the same date.
    op.drop_constraint(
        "portfolio_snapshots_profile_snapshot_date_key",
        "portfolio_snapshots",
        type_="unique",
    )
    op.create_index(
        "uq_portfolio_snapshots_org_profile_date",
        "portfolio_snapshots",
        ["organization_id", "profile", "snapshot_date"],
        unique=True,
    )

    # A3: Add approval_status to funds_universe for DD workflow.
    # server_default + nullable avoids ACCESS EXCLUSIVE lock on large tables.
    op.add_column(
        "funds_universe",
        sa.Column(
            "approval_status",
            sa.String(20),
            nullable=True,
            server_default="pending_dd",
        ),
    )
    op.execute("""
        ALTER TABLE funds_universe
        ADD CONSTRAINT chk_fund_approval_status
        CHECK (approval_status IN (
            'pending_dd', 'dd_complete', 'approved', 'rejected', 'watchlist'
        ))
    """)

    # A4: Partial index for peer comparison queries (fix #49)
    op.create_index(
        "ix_funds_universe_peer_lookup",
        "funds_universe",
        ["block_id", "is_active", "approval_status", "aum_usd"],
        postgresql_where=sa.text(
            "is_active = true AND approval_status = 'approved'"
        ),
    )

    # ═══════════════════════════════════════════════════════════════
    #  PHASE B: New tables
    # ═══════════════════════════════════════════════════════════════

    # ── dd_reports ────────────────────────────────────────────────
    op.create_table(
        "dd_reports",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True
        ),
        sa.Column(
            "fund_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("funds_universe.fund_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("decision_anchor", sa.String(20), nullable=True),
        sa.Column(
            "is_current", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(128), nullable=True),
    )

    # CHECK: status enum
    op.execute("""
        ALTER TABLE dd_reports
        ADD CONSTRAINT chk_dd_report_status
        CHECK (status IN (
            'draft', 'generating', 'critic_review',
            'pending_approval', 'approved', 'rejected'
        ))
    """)

    # CHECK: decision_anchor enum
    op.execute("""
        ALTER TABLE dd_reports
        ADD CONSTRAINT chk_dd_report_decision_anchor
        CHECK (decision_anchor IS NULL OR decision_anchor IN (
            'APPROVE', 'CONDITIONAL', 'REJECT'
        ))
    """)

    # Composite unique for dd_chapters composite FK
    op.create_index(
        "uq_dd_reports_id_org",
        "dd_reports",
        ["id", "organization_id"],
        unique=True,
    )

    # Version uniqueness per fund per org
    op.create_index(
        "uq_dd_reports_org_fund_version",
        "dd_reports",
        ["organization_id", "fund_id", "version"],
        unique=True,
    )

    # Only one current report per fund per org
    op.create_index(
        "uq_dd_reports_org_fund_current",
        "dd_reports",
        ["organization_id", "fund_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    # ── dd_chapters ──────────────────────────────────────────────
    op.create_table(
        "dd_chapters",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Direct organization_id for independent RLS (not join-based)
        sa.Column(
            "organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True
        ),
        sa.Column(
            "dd_report_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("chapter_tag", sa.String(50), nullable=False),
        sa.Column("chapter_order", sa.Integer(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=True),
        sa.Column("quant_data", postgresql.JSONB(), nullable=True),
        sa.Column(
            "critic_iterations",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "critic_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        # Composite FK: prevents cross-tenant FK references
        sa.ForeignKeyConstraint(
            ["dd_report_id", "organization_id"],
            ["dd_reports.id", "dd_reports.organization_id"],
            name="fk_dd_chapters_report_org",
        ),
    )

    # CHECK: critic_status enum
    op.execute("""
        ALTER TABLE dd_chapters
        ADD CONSTRAINT chk_dd_chapter_critic_status
        CHECK (critic_status IN ('pending', 'accepted', 'revised', 'escalated'))
    """)

    # Unique chapter per report
    op.create_index(
        "uq_dd_chapters_report_tag",
        "dd_chapters",
        ["dd_report_id", "chapter_tag"],
        unique=True,
    )

    # ── universe_approvals ───────────────────────────────────────
    op.create_table(
        "universe_approvals",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True
        ),
        # fund_id is NON-nullable (no bond polymorphism — fix #30)
        sa.Column(
            "fund_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("funds_universe.fund_id"),
            nullable=False,
            index=True,
        ),
        # dd_report_id is NON-nullable (fund approvals require DD Report)
        sa.Column(
            "dd_report_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("dd_reports.id"),
            nullable=False,
        ),
        sa.Column(
            "decision",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("decided_by", sa.String(128), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_current", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # CHECK: decision enum
    op.execute("""
        ALTER TABLE universe_approvals
        ADD CONSTRAINT chk_universe_approval_decision
        CHECK (decision IN ('approved', 'rejected', 'watchlist', 'pending'))
    """)

    # Only one current approval per fund per org
    op.create_index(
        "uq_universe_approvals_org_fund_current",
        "universe_approvals",
        ["organization_id", "fund_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    # ── model_portfolios ─────────────────────────────────────────
    op.create_table(
        "model_portfolios",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True
        ),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("benchmark_composite", sa.String(255), nullable=True),
        sa.Column("inception_date", sa.Date(), nullable=True),
        sa.Column("backtest_start_date", sa.Date(), nullable=True),
        sa.Column(
            "inception_nav",
            sa.Numeric(12, 4),
            nullable=False,
            server_default="1000.0",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("fund_selection_schema", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(128), nullable=True),
    )

    # CHECK: status enum
    op.execute("""
        ALTER TABLE model_portfolios
        ADD CONSTRAINT chk_model_portfolio_status
        CHECK (status IN ('draft', 'backtesting', 'live', 'archived'))
    """)

    # One active portfolio per profile per org
    op.create_index(
        "uq_model_portfolios_org_profile_active",
        "model_portfolios",
        ["organization_id", "profile"],
        unique=True,
        postgresql_where=sa.text("status IN ('draft', 'backtesting', 'live')"),
    )

    # ═══════════════════════════════════════════════════════════════
    #  PHASE C: RLS on all new tables
    # ═══════════════════════════════════════════════════════════════
    for table in _NEW_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # MUST use subselect pattern — see CLAUDE.md "RLS subselect" rule
        op.execute(f"""
            CREATE POLICY org_isolation ON {table}
                USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
                WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
        """)


def downgrade() -> None:
    # ── Remove RLS from new tables ───────────────────────────────
    for table in reversed(_NEW_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # ── Drop new tables (children first) ─────────────────────────
    op.drop_table("dd_chapters")
    op.drop_table("universe_approvals")
    op.drop_table("dd_reports")
    op.drop_table("model_portfolios")

    # ── Revert funds_universe changes ────────────────────────────
    op.drop_index("ix_funds_universe_peer_lookup", table_name="funds_universe")
    op.execute("""
        ALTER TABLE funds_universe
        DROP CONSTRAINT IF EXISTS chk_fund_approval_status
    """)
    op.drop_column("funds_universe", "approval_status")

    # ── Restore original unique constraints ──────────────────────
    # Restore global isin unique
    op.drop_index("uq_funds_universe_org_isin", table_name="funds_universe")
    op.create_unique_constraint(
        "funds_universe_isin_key", "funds_universe", ["isin"]
    )

    # Restore original portfolio_snapshots unique (without org_id)
    op.drop_index(
        "uq_portfolio_snapshots_org_profile_date",
        table_name="portfolio_snapshots",
    )
    op.create_unique_constraint(
        "portfolio_snapshots_profile_snapshot_date_key",
        "portfolio_snapshots",
        ["profile", "snapshot_date"],
    )
