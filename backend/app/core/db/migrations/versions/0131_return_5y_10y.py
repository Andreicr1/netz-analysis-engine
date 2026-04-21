"""Add return_5y_ann and return_10y_ann to fund_risk_metrics.

Supports long-horizon annualized return computation by global_risk_metrics
worker. ~82% of instruments have 5Y+ NAV history, ~60% have 10Y+.

Also recreates mv_fund_risk_latest to include the new columns plus
dtw_drift_score (now computed globally by strategy_label).

Revision ID: 0131_return_5y_10y
Revises: 0130_macro_regime_snapshot
Create Date: 2026-04-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0131_return_5y_10y"
down_revision = "0130_macro_regime_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fund_risk_metrics",
        sa.Column("return_5y_ann", sa.Numeric(12, 8), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("return_10y_ann", sa.Numeric(12, 8), nullable=True),
    )

    # Recreate mv_fund_risk_latest with new columns
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
            return_5y_ann,
            return_10y_ann,
            dtw_drift_score,
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


def downgrade() -> None:
    # Recreate mv_fund_risk_latest without the new columns (revert to 0125 version)
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
            weighted_avg_maturity_days,
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

    op.drop_column("fund_risk_metrics", "return_10y_ann")
    op.drop_column("fund_risk_metrics", "return_5y_ann")
