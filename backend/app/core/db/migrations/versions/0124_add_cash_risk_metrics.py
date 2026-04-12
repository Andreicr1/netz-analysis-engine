"""Add cash/MMF risk metrics columns to fund_risk_metrics.

Adds 5 new columns for Cash analytics (7-day yield, fed funds rate,
NAV per share, weekly liquidity, WAM) used by the cash scoring model.
Recreates mv_fund_risk_latest to include cash columns.

Revision ID: 0124_add_cash_risk_metrics
Revises: 0123_add_fixed_income_risk_metrics
Create Date: 2026-04-12
"""

from alembic import op

revision = "0124_add_cash_risk_metrics"
down_revision = "0123_add_fixed_income_risk_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1. Add Cash analytics columns to fund_risk_metrics ---
    op.execute("""
        ALTER TABLE fund_risk_metrics
            ADD COLUMN IF NOT EXISTS seven_day_net_yield NUMERIC(8, 4),
            ADD COLUMN IF NOT EXISTS fed_funds_rate_at_calc NUMERIC(8, 4),
            ADD COLUMN IF NOT EXISTS nav_per_share_mmf NUMERIC(12, 6),
            ADD COLUMN IF NOT EXISTS pct_weekly_liquid NUMERIC(8, 4),
            ADD COLUMN IF NOT EXISTS weighted_avg_maturity_days INTEGER
    """)

    # --- 2. Recreate mv_fund_risk_latest with Cash columns ---
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
            scoring_model,
            -- Cash analytics columns
            seven_day_net_yield,
            fed_funds_rate_at_calc,
            nav_per_share_mmf,
            pct_weekly_liquid,
            weighted_avg_maturity_days
        FROM fund_risk_metrics
        WHERE organization_id IS NULL
        ORDER BY instrument_id, calc_date DESC
        WITH NO DATA
    """)

    # Recreate indexes
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
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_scoring_model
        ON mv_fund_risk_latest (scoring_model)
    """)

    op.execute("REFRESH MATERIALIZED VIEW mv_fund_risk_latest")


def downgrade() -> None:
    # Recreate MV without Cash columns (restore 0123 definition)
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
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_scoring_model
        ON mv_fund_risk_latest (scoring_model)
    """)

    op.execute("REFRESH MATERIALIZED VIEW mv_fund_risk_latest")

    # Drop Cash columns
    op.execute("""
        ALTER TABLE fund_risk_metrics
            DROP COLUMN IF EXISTS seven_day_net_yield,
            DROP COLUMN IF EXISTS fed_funds_rate_at_calc,
            DROP COLUMN IF EXISTS nav_per_share_mmf,
            DROP COLUMN IF EXISTS pct_weekly_liquid,
            DROP COLUMN IF EXISTS weighted_avg_maturity_days
    """)
