"""Wealth domain: funds universe, NAV timeseries, risk metrics, portfolio,
allocation, blocks, rebalance, macro, lipper, backtest."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── allocation_blocks (global, no organization_id) ──────────────
    op.create_table(
        "allocation_blocks",
        sa.Column("block_id", sa.String(80), primary_key=True),
        sa.Column("geography", sa.String(50), nullable=False),
        sa.Column("asset_class", sa.String(50), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("benchmark_ticker", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
    )

    # ── funds_universe ──────────────────────────────────────────────
    op.create_table(
        "funds_universe",
        sa.Column("fund_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("isin", sa.String(12), unique=True, nullable=True),
        sa.Column("ticker", sa.String(20), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("manager_name", sa.String(255), nullable=True),
        sa.Column("fund_type", sa.String(50), nullable=True),
        sa.Column("geography", sa.String(50), nullable=True, index=True),
        sa.Column("asset_class", sa.String(50), nullable=True),
        sa.Column("sub_category", sa.String(80), nullable=True),
        sa.Column("block_id", sa.String(80), sa.ForeignKey("allocation_blocks.block_id"), nullable=True, index=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("domicile", sa.String(50), nullable=True),
        sa.Column("liquidity_days", sa.Integer(), nullable=True),
        sa.Column("aum_usd", sa.Numeric(18, 2), nullable=True),
        sa.Column("inception_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("data_source", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # ── nav_timeseries (TimescaleDB hypertable) ─────────────────────
    op.create_table(
        "nav_timeseries",
        sa.Column("fund_id", sa.Uuid(as_uuid=True), sa.ForeignKey("funds_universe.fund_id"), primary_key=True),
        sa.Column("nav_date", sa.Date(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("nav", sa.Numeric(18, 6), nullable=True),
        sa.Column("return_1d", sa.Numeric(12, 8), nullable=True),
        sa.Column("aum_usd", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("source", sa.String(30), nullable=True),
        sa.Column("return_type", sa.String(10), nullable=False, server_default="arithmetic"),
    )
    op.execute("SELECT create_hypertable('nav_timeseries', 'nav_date', migrate_data => true)")

    # ── fund_risk_metrics (TimescaleDB hypertable) ──────────────────
    op.create_table(
        "fund_risk_metrics",
        sa.Column("fund_id", sa.Uuid(as_uuid=True), sa.ForeignKey("funds_universe.fund_id"), primary_key=True),
        sa.Column("calc_date", sa.Date(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        # CVaR windows
        sa.Column("cvar_95_1m", sa.Numeric(10, 6), nullable=True),
        sa.Column("cvar_95_3m", sa.Numeric(10, 6), nullable=True),
        sa.Column("cvar_95_6m", sa.Numeric(10, 6), nullable=True),
        sa.Column("cvar_95_12m", sa.Numeric(10, 6), nullable=True),
        # VaR windows
        sa.Column("var_95_1m", sa.Numeric(10, 6), nullable=True),
        sa.Column("var_95_3m", sa.Numeric(10, 6), nullable=True),
        sa.Column("var_95_6m", sa.Numeric(10, 6), nullable=True),
        sa.Column("var_95_12m", sa.Numeric(10, 6), nullable=True),
        # Return metrics
        sa.Column("return_1m", sa.Numeric(10, 6), nullable=True),
        sa.Column("return_3m", sa.Numeric(10, 6), nullable=True),
        sa.Column("return_6m", sa.Numeric(10, 6), nullable=True),
        sa.Column("return_1y", sa.Numeric(10, 6), nullable=True),
        sa.Column("return_3y_ann", sa.Numeric(10, 6), nullable=True),
        # Risk metrics
        sa.Column("volatility_1y", sa.Numeric(10, 6), nullable=True),
        sa.Column("max_drawdown_1y", sa.Numeric(10, 6), nullable=True),
        sa.Column("max_drawdown_3y", sa.Numeric(10, 6), nullable=True),
        sa.Column("sharpe_1y", sa.Numeric(10, 6), nullable=True),
        sa.Column("sharpe_3y", sa.Numeric(10, 6), nullable=True),
        sa.Column("sortino_1y", sa.Numeric(10, 6), nullable=True),
        # Relative metrics
        sa.Column("alpha_1y", sa.Numeric(10, 6), nullable=True),
        sa.Column("beta_1y", sa.Numeric(10, 6), nullable=True),
        sa.Column("information_ratio_1y", sa.Numeric(10, 6), nullable=True),
        sa.Column("tracking_error_1y", sa.Numeric(10, 6), nullable=True),
        # Composite score
        sa.Column("manager_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("score_components", postgresql.JSONB(), nullable=True),
        # DTW drift
        sa.Column("dtw_drift_score", sa.Numeric(10, 6), nullable=True),
    )
    op.execute("SELECT create_hypertable('fund_risk_metrics', 'calc_date', migrate_data => true)")

    # ── portfolio_snapshots ─────────────────────────────────────────
    op.create_table(
        "portfolio_snapshots",
        sa.Column("snapshot_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("weights", postgresql.JSONB(), nullable=False),
        sa.Column("fund_selection", postgresql.JSONB(), nullable=True),
        sa.Column("cvar_current", sa.Numeric(10, 6), nullable=True),
        sa.Column("cvar_limit", sa.Numeric(10, 6), nullable=True),
        sa.Column("cvar_utilized_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("trigger_status", sa.String(20), nullable=True),
        sa.Column("consecutive_breach_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("regime", sa.String(20), nullable=True),
        sa.Column("core_weight", sa.Numeric(6, 4), nullable=True),
        sa.Column("satellite_weight", sa.Numeric(6, 4), nullable=True),
        sa.Column("regime_probs", postgresql.JSONB(), nullable=True),
        sa.Column("cvar_lower_5", sa.Numeric(10, 6), nullable=True),
        sa.Column("cvar_upper_95", sa.Numeric(10, 6), nullable=True),
        sa.UniqueConstraint("profile", "snapshot_date"),
    )
    op.create_index("ix_portfolio_snapshots_profile_snapshot_date", "portfolio_snapshots", ["profile", "snapshot_date"])

    # ── strategic_allocation ────────────────────────────────────────
    op.create_table(
        "strategic_allocation",
        sa.Column("allocation_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("block_id", sa.String(80), sa.ForeignKey("allocation_blocks.block_id"), nullable=False),
        sa.Column("target_weight", sa.Numeric(6, 4), nullable=False),
        sa.Column("min_weight", sa.Numeric(6, 4), nullable=False),
        sa.Column("max_weight", sa.Numeric(6, 4), nullable=False),
        sa.Column("risk_budget", sa.Numeric(6, 4), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("actor_source", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── tactical_positions ──────────────────────────────────────────
    op.create_table(
        "tactical_positions",
        sa.Column("position_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("block_id", sa.String(80), sa.ForeignKey("allocation_blocks.block_id"), nullable=False),
        sa.Column("overweight", sa.Numeric(6, 4), nullable=False),
        sa.Column("conviction_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("signal_source", sa.String(50), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("actor_source", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── rebalance_events ────────────────────────────────────────────
    op.create_table(
        "rebalance_events",
        sa.Column("event_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("trigger_reason", sa.Text(), nullable=True),
        sa.Column("weights_before", postgresql.JSONB(), nullable=True),
        sa.Column("weights_after", postgresql.JSONB(), nullable=True),
        sa.Column("cvar_before", sa.Numeric(10, 6), nullable=True),
        sa.Column("cvar_after", sa.Numeric(10, 6), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("actor_source", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rebalance_events_profile_event_date", "rebalance_events", ["profile", "event_date"])

    # ── macro_data (global, no organization_id) ─────────────────────
    op.create_table(
        "macro_data",
        sa.Column("series_id", sa.String(30), primary_key=True),
        sa.Column("obs_date", sa.Date(), primary_key=True),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("source", sa.String(30), server_default="fred", nullable=True),
        sa.Column("is_derived", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
    )

    # ── lipper_ratings ──────────────────────────────────────────────
    op.create_table(
        "lipper_ratings",
        sa.Column("fund_id", sa.Uuid(as_uuid=True), sa.ForeignKey("funds_universe.fund_id"), primary_key=True),
        sa.Column("rating_date", sa.Date(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("overall_rating", sa.Integer(), nullable=True),
        sa.Column("consistent_return", sa.Integer(), nullable=True),
        sa.Column("preservation", sa.Integer(), nullable=True),
        sa.Column("total_return", sa.Integer(), nullable=True),
        sa.Column("expense", sa.Integer(), nullable=True),
        sa.Column("tax_efficiency", sa.Integer(), nullable=True),
        sa.Column("fund_classification", sa.String(80), nullable=True),
        sa.Column("source", sa.String(30), server_default="lipper", nullable=True),
    )

    # ── backtest_runs ───────────────────────────────────────────────
    op.create_table(
        "backtest_runs",
        sa.Column("run_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("results", postgresql.JSONB(), nullable=True),
        sa.Column("cv_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("backtest_runs")
    op.drop_table("lipper_ratings")
    op.drop_table("macro_data")
    op.drop_table("rebalance_events")
    op.drop_table("tactical_positions")
    op.drop_table("strategic_allocation")
    op.drop_table("portfolio_snapshots")
    op.drop_table("fund_risk_metrics")
    op.drop_table("nav_timeseries")
    op.drop_table("funds_universe")
    op.drop_table("allocation_blocks")
