"""Instruments universe: polymorphic instrument model + screening infrastructure.

Creates instruments_universe (replaces funds_universe for new instruments),
instrument_screening_metrics, screening_runs, screening_results tables.
Expands config_type CHECK to V4 (adds screening_layer1/2/3).
All new tenant-scoped tables get RLS. funds_universe is NOT dropped here —
see future migration (separate PR with bake period).

depends_on: 0010 (tenant_asset_slug_rls_fix).
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0010"
branch_labels = None
depends_on = None

# ── New tables that need RLS ──────────────────────────────────────
_NEW_RLS_TABLES = [
    "instruments_universe",
    "instrument_screening_metrics",
    "screening_runs",
    "screening_results",
]

# ── Config type expansion (V3 → V4) ──────────────────────────────
_CONFIG_TYPES_V4 = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
    "'evaluation', 'macro_intelligence', 'governance_policy', 'branding', "
    "'screening_layer1', 'screening_layer2', 'screening_layer3'"
)


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    #  PHASE A: Create instruments_universe table
    # ═══════════════════════════════════════════════════════════════
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.create_table(
        "instruments_universe",
        sa.Column("instrument_id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("instrument_type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("isin", sa.String(12)),
        sa.Column("ticker", sa.String(20)),
        sa.Column("bloomberg_ticker", sa.String(30)),
        sa.Column("asset_class", sa.String(50), nullable=False),
        sa.Column("geography", sa.String(50), nullable=False, index=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("block_id", sa.String(80), sa.ForeignKey("allocation_blocks.block_id"), index=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("approval_status", sa.String(20), server_default="pending"),
        sa.Column("attributes", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Instrument type CHECK
    op.execute("""
        ALTER TABLE instruments_universe
        ADD CONSTRAINT chk_instrument_type
        CHECK (instrument_type IN ('fund', 'bond', 'equity'))
    """)

    # Approval status CHECK
    op.execute("""
        ALTER TABLE instruments_universe
        ADD CONSTRAINT chk_instrument_approval_status
        CHECK (approval_status IN (
            'pending', 'pending_dd', 'dd_complete', 'approved', 'rejected', 'watchlist'
        ))
    """)

    # Org-scoped partial unique on ISIN
    op.create_index(
        "uq_instruments_universe_org_isin",
        "instruments_universe",
        ["organization_id", "isin"],
        unique=True,
        postgresql_where=sa.text("isin IS NOT NULL"),
    )

    # Partial index for active instruments per type per org (screener hot path)
    op.create_index(
        "ix_iu_active_type_org",
        "instruments_universe",
        ["organization_id", "instrument_type", "asset_class"],
        postgresql_where=sa.text("is_active = true"),
    )

    # ── JSONB indexing ────────────────────────────────────────────
    # GIN with jsonb_path_ops for containment queries (@>)
    op.execute("""
        CREATE INDEX idx_iu_attrs_gin
        ON instruments_universe USING gin (attributes jsonb_path_ops)
    """)

    # Partial expression B-tree indexes per type (screener hot paths)
    op.execute("""
        CREATE INDEX idx_iu_fund_aum
        ON instruments_universe (((attributes->>'aum_usd')::numeric))
        WHERE instrument_type = 'fund' AND is_active
    """)
    op.execute("""
        CREATE INDEX idx_iu_bond_rating
        ON instruments_universe ((attributes->>'credit_rating_sp'))
        WHERE instrument_type = 'bond' AND is_active
    """)
    op.execute("""
        CREATE INDEX idx_iu_equity_mcap
        ON instruments_universe (((attributes->>'market_cap_usd')::numeric))
        WHERE instrument_type = 'equity' AND is_active
    """)

    # ── CHECK constraints for required JSONB fields per type ─────
    op.execute("""
        ALTER TABLE instruments_universe ADD CONSTRAINT chk_fund_attrs
        CHECK (instrument_type != 'fund' OR (attributes ?& ARRAY['aum_usd', 'manager_name', 'inception_date']))
    """)
    op.execute("""
        ALTER TABLE instruments_universe ADD CONSTRAINT chk_bond_attrs
        CHECK (instrument_type != 'bond' OR (attributes ?& ARRAY['maturity_date', 'coupon_rate_pct', 'issuer_name']))
    """)
    op.execute("""
        ALTER TABLE instruments_universe ADD CONSTRAINT chk_equity_attrs
        CHECK (instrument_type != 'equity' OR (attributes ?& ARRAY['market_cap_usd', 'sector', 'exchange']))
    """)

    # ═══════════════════════════════════════════════════════════════
    #  PHASE B: Create instrument_screening_metrics table
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "instrument_screening_metrics",
        sa.Column("instrument_id", sa.Uuid(as_uuid=True), sa.ForeignKey("instruments_universe.instrument_id"), nullable=False),
        sa.Column("calc_date", sa.Date(), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("metrics", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("data_period_days", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("instrument_id", "calc_date"),
    )

    # Source CHECK
    op.execute("""
        ALTER TABLE instrument_screening_metrics
        ADD CONSTRAINT chk_screening_metrics_source
        CHECK (source IN ('yahoo_finance', 'csv', 'computed'))
    """)

    # ═══════════════════════════════════════════════════════════════
    #  PHASE C: Create screening_runs + screening_results tables
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "screening_runs",
        sa.Column("run_id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("run_type", sa.String(20), nullable=False),
        sa.Column("instrument_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
    )

    op.execute("""
        ALTER TABLE screening_runs
        ADD CONSTRAINT chk_run_type
        CHECK (run_type IN ('batch', 'on_demand'))
    """)
    op.execute("""
        ALTER TABLE screening_runs
        ADD CONSTRAINT chk_run_status
        CHECK (status IN ('running', 'completed', 'failed'))
    """)

    op.create_table(
        "screening_results",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("instrument_id", sa.Uuid(as_uuid=True), sa.ForeignKey("instruments_universe.instrument_id"), nullable=False, index=True),
        sa.Column("run_id", sa.Uuid(as_uuid=True), sa.ForeignKey("screening_runs.run_id"), nullable=False, index=True),
        sa.Column("overall_status", sa.String(20), nullable=False),
        sa.Column("score", sa.Numeric(5, 4)),
        sa.Column("failed_at_layer", sa.SmallInteger()),
        sa.Column("layer_results", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("required_analysis_type", sa.String(20), nullable=False, server_default="dd_report"),
        sa.Column("screened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="true"),
    )

    op.execute("""
        ALTER TABLE screening_results
        ADD CONSTRAINT chk_screening_status
        CHECK (overall_status IN ('PASS', 'FAIL', 'WATCHLIST'))
    """)
    op.execute("""
        ALTER TABLE screening_results
        ADD CONSTRAINT chk_analysis_type
        CHECK (required_analysis_type IN ('dd_report', 'bond_brief', 'none'))
    """)

    # Partial unique index: only one current result per instrument per org
    op.create_index(
        "uq_screening_results_current",
        "screening_results",
        ["organization_id", "instrument_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    # Index for latest-run query pattern
    op.create_index(
        "ix_screening_runs_org_completed",
        "screening_runs",
        ["organization_id", "completed_at"],
        postgresql_where=sa.text("status = 'completed'"),
    )

    # ═══════════════════════════════════════════════════════════════
    #  PHASE D: Expand config_type CHECK constraint (V3 → V4)
    # ═══════════════════════════════════════════════════════════════
    for table in ("vertical_config_defaults", "vertical_config_overrides"):
        constraint = f"ck_{'defaults' if 'defaults' in table else 'overrides'}_config_type"
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK (config_type IN ({_CONFIG_TYPES_V4}))")

    # ═══════════════════════════════════════════════════════════════
    #  PHASE E: RLS on all new tables
    # ═══════════════════════════════════════════════════════════════
    for table in _NEW_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_org_isolation ON {table}
            USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
        """)


def downgrade() -> None:
    # ── Remove RLS ────────────────────────────────────────────────
    for table in reversed(_NEW_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # ── Restore config_type V3 ────────────────────────────────────
    _CONFIG_TYPES_V3 = (
        "'calibration', 'scoring', 'blocks', 'chapters', "
        "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
        "'evaluation', 'macro_intelligence', 'governance_policy', 'branding'"
    )
    for table in ("vertical_config_defaults", "vertical_config_overrides"):
        constraint = f"ck_{'defaults' if 'defaults' in table else 'overrides'}_config_type"
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK (config_type IN ({_CONFIG_TYPES_V3}))")

    # ── Drop tables in reverse dependency order ───────────────────
    op.drop_table("screening_results")
    op.drop_table("screening_runs")
    op.drop_table("instrument_screening_metrics")
    op.drop_table("instruments_universe")
