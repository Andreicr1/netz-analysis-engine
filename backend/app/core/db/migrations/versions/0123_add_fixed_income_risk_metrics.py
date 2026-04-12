"""Add fixed income risk metrics columns to fund_risk_metrics.

Adds 7 new columns for FI analytics (empirical duration, credit beta,
yield proxy, duration-adjusted drawdown) and scoring_model audit trail.
Recreates mv_fund_risk_latest to include scoring_model and FI columns.

Revision ID: 0123_add_fixed_income_risk_metrics
Revises: 0122_add_fi_benchmark_blocks
Create Date: 2026-04-12
"""

from alembic import op

revision = "0123_add_fixed_income_risk_metrics"
down_revision = "0122_add_fi_benchmark_blocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1. Add FI analytics columns to fund_risk_metrics ---
    op.execute("""
        ALTER TABLE fund_risk_metrics
            ADD COLUMN IF NOT EXISTS empirical_duration NUMERIC(8, 4),
            ADD COLUMN IF NOT EXISTS empirical_duration_r2 NUMERIC(6, 4),
            ADD COLUMN IF NOT EXISTS credit_beta NUMERIC(8, 4),
            ADD COLUMN IF NOT EXISTS credit_beta_r2 NUMERIC(6, 4),
            ADD COLUMN IF NOT EXISTS yield_proxy_12m NUMERIC(10, 6),
            ADD COLUMN IF NOT EXISTS duration_adj_drawdown_1y NUMERIC(10, 6),
            ADD COLUMN IF NOT EXISTS scoring_model VARCHAR(20) DEFAULT 'equity'
    """)

    # --- 2. Backfill scoring_model for existing rows ---
    op.execute("""
        UPDATE fund_risk_metrics
        SET scoring_model = 'equity'
        WHERE scoring_model IS NULL
    """)

    # --- 3. Recreate mv_fund_risk_latest with FI columns ---
    # Drop existing view + indexes
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_fund_risk_latest CASCADE")

    op.execute("""
        CREATE MATERIALIZED VIEW mv_fund_risk_latest AS
        SELECT DISTINCT ON (instrument_id)
            instrument_id,
            calc_date,
            manager_score,
            score_components,
            sharpe_1y,
            sortino_1y,
            volatility_1y,
            volatility_garch,
            cvar_95_12m,
            cvar_95_conditional,
            max_drawdown_1y,
            return_1y,
            blended_momentum_score,
            peer_strategy_label,
            peer_sharpe_pctl,
            peer_sortino_pctl,
            peer_return_pctl,
            peer_drawdown_pctl,
            peer_count,
            elite_flag,
            elite_rank_within_strategy,
            elite_target_count_per_strategy,
            -- FI analytics columns
            empirical_duration,
            empirical_duration_r2,
            credit_beta,
            credit_beta_r2,
            yield_proxy_12m,
            duration_adj_drawdown_1y,
            scoring_model
        FROM fund_risk_metrics
        WHERE organization_id IS NULL
        ORDER BY instrument_id, calc_date DESC
        WITH NO DATA
    """)

    # Recreate indexes (same as migration 0116)
    op.execute("""
        CREATE UNIQUE INDEX uq_mv_fund_risk_latest_instrument
        ON mv_fund_risk_latest (instrument_id)
    """)
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_elite
        ON mv_fund_risk_latest (instrument_id)
        WHERE elite_flag = true
    """)
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_sharpe
        ON mv_fund_risk_latest (sharpe_1y DESC NULLS LAST)
    """)
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_manager_score
        ON mv_fund_risk_latest (manager_score DESC NULLS LAST)
    """)
    # New index for FI scoring model filter
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_scoring_model
        ON mv_fund_risk_latest (scoring_model)
    """)

    op.execute("REFRESH MATERIALIZED VIEW mv_fund_risk_latest")


def downgrade() -> None:
    # Recreate MV without FI columns (restore 0116 definition)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_fund_risk_latest CASCADE")

    op.execute("""
        CREATE MATERIALIZED VIEW mv_fund_risk_latest AS
        SELECT DISTINCT ON (instrument_id)
            instrument_id,
            calc_date,
            manager_score,
            sharpe_1y,
            sortino_1y,
            volatility_1y,
            volatility_garch,
            cvar_95_12m,
            cvar_95_conditional,
            max_drawdown_1y,
            return_1y,
            blended_momentum_score,
            peer_strategy_label,
            peer_sharpe_pctl,
            peer_sortino_pctl,
            peer_return_pctl,
            peer_drawdown_pctl,
            peer_count,
            elite_flag,
            elite_rank_within_strategy,
            elite_target_count_per_strategy
        FROM fund_risk_metrics
        WHERE organization_id IS NULL
        ORDER BY instrument_id, calc_date DESC
        WITH NO DATA
    """)

    op.execute("""
        CREATE UNIQUE INDEX uq_mv_fund_risk_latest_instrument
        ON mv_fund_risk_latest (instrument_id)
    """)
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_elite
        ON mv_fund_risk_latest (instrument_id)
        WHERE elite_flag = true
    """)
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_sharpe
        ON mv_fund_risk_latest (sharpe_1y DESC NULLS LAST)
    """)
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_manager_score
        ON mv_fund_risk_latest (manager_score DESC NULLS LAST)
    """)

    op.execute("REFRESH MATERIALIZED VIEW mv_fund_risk_latest")

    # Drop FI columns
    op.execute("""
        ALTER TABLE fund_risk_metrics
            DROP COLUMN IF EXISTS empirical_duration,
            DROP COLUMN IF EXISTS empirical_duration_r2,
            DROP COLUMN IF EXISTS credit_beta,
            DROP COLUMN IF EXISTS credit_beta_r2,
            DROP COLUMN IF EXISTS yield_proxy_12m,
            DROP COLUMN IF EXISTS duration_adj_drawdown_1y,
            DROP COLUMN IF EXISTS scoring_model
    """)
