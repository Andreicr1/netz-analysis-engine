"""Add alternatives risk metrics columns to fund_risk_metrics.

Adds 7 new columns for Alternatives analytics (equity correlation,
capture ratios, crisis alpha, Calmar ratio, inflation beta) used by
the alternatives scoring model.  Adds 2 new allocation blocks
(alt_hedge_fund, alt_managed_futures) to blocks seed data.
Recreates mv_fund_risk_latest to include alternatives columns.

Revision ID: 0125_add_alternatives_risk_metrics
Revises: 0124_add_cash_risk_metrics
Create Date: 2026-04-12
"""

from alembic import op

revision = "0125_add_alternatives_risk_metrics"
down_revision = "0124_add_cash_risk_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1. Add Alternatives analytics columns to fund_risk_metrics ---
    op.execute("""
        ALTER TABLE fund_risk_metrics
            ADD COLUMN IF NOT EXISTS equity_correlation_252d NUMERIC(6, 4),
            ADD COLUMN IF NOT EXISTS downside_capture_1y NUMERIC(8, 4),
            ADD COLUMN IF NOT EXISTS upside_capture_1y NUMERIC(8, 4),
            ADD COLUMN IF NOT EXISTS crisis_alpha_score NUMERIC(10, 6),
            ADD COLUMN IF NOT EXISTS calmar_ratio_3y NUMERIC(8, 4),
            ADD COLUMN IF NOT EXISTS inflation_beta NUMERIC(8, 4),
            ADD COLUMN IF NOT EXISTS inflation_beta_r2 NUMERIC(6, 4)
    """)

    # --- 2. Recreate mv_fund_risk_latest with Alternatives columns ---
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
            weighted_avg_maturity_days,
            -- Alternatives analytics columns
            equity_correlation_252d,
            downside_capture_1y,
            upside_capture_1y,
            crisis_alpha_score,
            calmar_ratio_3y,
            inflation_beta,
            inflation_beta_r2
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
    # Recreate MV without Alternatives columns (restore 0124 definition)
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
            scoring_model,
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

    # Drop Alternatives columns
    op.execute("""
        ALTER TABLE fund_risk_metrics
            DROP COLUMN IF EXISTS equity_correlation_252d,
            DROP COLUMN IF EXISTS downside_capture_1y,
            DROP COLUMN IF EXISTS upside_capture_1y,
            DROP COLUMN IF EXISTS crisis_alpha_score,
            DROP COLUMN IF EXISTS calmar_ratio_3y,
            DROP COLUMN IF EXISTS inflation_beta,
            DROP COLUMN IF EXISTS inflation_beta_r2
    """)
