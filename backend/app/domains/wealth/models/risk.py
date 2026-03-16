import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, ForeignKey, Numeric, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class FundRiskMetrics(OrganizationScopedMixin, Base):
    __tablename__ = "fund_risk_metrics"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("instruments_universe.instrument_id"), primary_key=True
    )
    calc_date: Mapped[date] = mapped_column(Date, primary_key=True)

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

    # DTW drift signal (derivative DTW vs block benchmark, length-normalized)
    dtw_drift_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
