import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Date, ForeignKey, Numeric, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class FundRiskMetrics(Base):
    __tablename__ = "fund_risk_metrics"

    # Composite identity: (instrument_id, calc_date, organization_id).
    # organization_id is part of the identity tuple so global rows
    # (org_id=NULL, written by run_global_risk_metrics) coexist with
    # tenant-scoped rows (written by run_risk_calc with DTW drift).
    # The DB-level constraint is a UNIQUE INDEX … NULLS NOT DISTINCT
    # (migration 0093) — PRIMARY KEY cannot include nullable columns,
    # but SQLAlchemy's ORM identity map only needs the tuple to be
    # collision-free, which the unique index guarantees.
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("instruments_universe.instrument_id"), primary_key=True,
    )
    calc_date: Mapped[date] = mapped_column(Date, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        primary_key=True,
        index=True,
    )

    # CVaR windows (95% confidence)
    cvar_95_1m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    cvar_95_3m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    cvar_95_6m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    cvar_95_12m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # VaR windows (symmetric with CVaR)
    var_95_1m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    var_95_3m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    var_95_6m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    var_95_12m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # Return metrics
    return_1m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    return_3m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    return_6m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    return_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    return_3y_ann: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # Risk metrics
    volatility_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    max_drawdown_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    max_drawdown_3y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    sharpe_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    sharpe_3y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    sortino_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # Relative metrics
    alpha_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    beta_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    information_ratio_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    tracking_error_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # Composite score
    manager_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    score_components: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Momentum signals (pre-computed by risk_calc worker)
    rsi_14: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    bb_position: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    nav_momentum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    flow_momentum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    blended_momentum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # GARCH(1,1) conditional volatility (annualized, 1-step-ahead forecast)
    volatility_garch: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    vol_model: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # CVaR conditional on stress regime (BL-9)
    cvar_95_conditional: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    # DTW drift signal (derivative DTW vs block benchmark, length-normalized)
    dtw_drift_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # Fixed income analytics (pre-computed by risk_calc FI analytics pass)
    empirical_duration: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    empirical_duration_r2: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    credit_beta: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    credit_beta_r2: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    yield_proxy_12m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    duration_adj_drawdown_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    scoring_model: Mapped[str | None] = mapped_column(String(20), server_default="equity", nullable=True)

    # Cash/MMF analytics (pre-computed by risk_calc cash analytics pass)
    seven_day_net_yield: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    fed_funds_rate_at_calc: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    nav_per_share_mmf: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    pct_weekly_liquid: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    weighted_avg_maturity_days: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # Audit & data quality flags
    data_quality_flags: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=True)

    # Peer group percentile rankings (pre-computed by risk_calc worker)
    peer_strategy_label: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    peer_sharpe_pctl: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    peer_sortino_pctl: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    peer_return_pctl: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    peer_drawdown_pctl: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    peer_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # ELITE ranking (populated by risk_calc ELITE ranking pass, lock 900_071).
    # elite_flag marks funds in the top-N of their strategy bucket where N is
    # round(300 * strategy_weight) and strategy weights come from the global
    # default allocation (liquid_funds.portfolio_profiles.moderate aggregated
    # per asset_class). See vertical_engines.wealth.elite_ranking.
    elite_flag: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    elite_rank_within_strategy: Mapped[int | None] = mapped_column(
        sa.SmallInteger, nullable=True,
    )
    elite_target_count_per_strategy: Mapped[int | None] = mapped_column(
        sa.SmallInteger, nullable=True,
    )
