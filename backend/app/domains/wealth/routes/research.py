from __future__ import annotations

import uuid
from datetime import date, timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.risk import FundRiskMetrics
from app.domains.wealth.schemas.research import (
    MarketSensitivitiesPayload,
    ResearchMetricPoint,
    ResearchScatterResponse,
    SingleFundResearchResponse,
    StyleBiasPayload,
)
from quant_engine.factor_model_service import build_fundamental_factor_returns

router = APIRouter(prefix="/research", tags=["research"])

_FACTOR_LABELS: dict[str, str] = {
    "equity_us": "Global Equity",
    "duration": "Rate Duration",
    "credit": "Credit Spread",
    "usd": "Dollar Sensitivity",
    "commodity": "Commodity Linkage",
    "size": "Small Cap Tilt",
    "value": "Value Tilt",
    "international": "International Linkage",
}

_STYLE_LABELS: dict[str, str] = {
    "size_log_mkt_cap": "Scale",
    "book_to_market": "Value Tilt",
    "mom_12_1": "Momentum",
    "quality_roa": "Quality",
    "investment_growth": "Reinvestment",
    "profitability_gross": "Profitability",
}


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _significance_from_t_stat(t_stat: float | None) -> str:
    if t_stat is None:
        return "none"
    score = abs(float(t_stat))
    if score >= 2.0:
        return "high"
    if score >= 1.0:
        return "medium"
    if score >= 0.5:
        return "low"
    return "none"


async def _resolve_instrument(
    db: AsyncSession,
    instrument_id: uuid.UUID,
) -> Instrument:
    result = await db.execute(
        select(Instrument).where(Instrument.instrument_id == instrument_id),
    )
    instrument = result.scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instrument not found")
    return instrument


async def _load_single_returns(
    db: AsyncSession,
    instrument_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> pd.Series:
    stmt = (
        select(NavTimeseries.nav_date, NavTimeseries.return_1d)
        .where(
            NavTimeseries.instrument_id == instrument_id,
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.nav_date <= end_date,
            NavTimeseries.return_1d.isnot(None),
        )
        .order_by(NavTimeseries.nav_date)
    )
    result = await db.execute(stmt)
    rows = result.all()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series(
        [_to_float(row.return_1d) for row in rows],
        index=pd.to_datetime([row.nav_date for row in rows]),
        dtype=float,
    ).dropna()


def _build_market_sensitivities_payload(
    fund_returns: pd.Series,
    factor_returns: pd.DataFrame,
) -> MarketSensitivitiesPayload:
    aligned = pd.concat(
        [fund_returns.rename("fund"), factor_returns],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 60 or factor_returns.empty:
        return MarketSensitivitiesPayload(exposures=[])

    y = aligned["fund"].to_numpy(dtype=np.float64)
    x = aligned[factor_returns.columns].to_numpy(dtype=np.float64)
    x = np.column_stack([np.ones(len(aligned)), x])

    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ beta
    residual = y - fitted
    dof = max(len(y) - x.shape[1], 1)
    sigma2 = float((residual @ residual) / dof)
    xtx_inv = np.linalg.pinv(x.T @ x)
    se = np.sqrt(np.maximum(np.diag(xtx_inv) * sigma2, 0.0))
    t_stats = np.divide(
        beta,
        se,
        out=np.zeros_like(beta),
        where=se > 0,
    )

    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    ss_res = float(np.sum(residual ** 2))
    r_squared = 0.0 if ss_tot <= 0 else max(0.0, min(1.0, 1.0 - (ss_res / ss_tot)))

    exposures: list[ResearchMetricPoint] = []
    for idx, factor_name in enumerate(factor_returns.columns, start=1):
        exposures.append(
            ResearchMetricPoint(
                label=_FACTOR_LABELS.get(factor_name, factor_name.replace("_", " ").title()),
                value=round(float(beta[idx]), 4),
                significance=_significance_from_t_stat(float(t_stats[idx])),
            )
        )

    exposures.sort(key=lambda item: abs(item.value), reverse=True)
    return MarketSensitivitiesPayload(
        exposures=exposures,
        r_squared=round(r_squared, 4),
        systematic_risk_pct=round(r_squared * 100.0, 2),
        as_of_date=aligned.index[-1].date(),
    )


async def _load_style_bias_payload(
    db: AsyncSession,
    instrument_id: uuid.UUID,
) -> StyleBiasPayload:
    row_stmt = """
        WITH latest_point AS (
            SELECT as_of
            FROM equity_characteristics_monthly
            WHERE instrument_id = :instrument_id
            ORDER BY as_of DESC
            LIMIT 1
        ),
        sample AS (
            SELECT
                e.as_of,
                e.size_log_mkt_cap,
                e.book_to_market,
                e.mom_12_1,
                e.quality_roa,
                e.investment_growth,
                e.profitability_gross
            FROM equity_characteristics_monthly e
            JOIN latest_point lp ON lp.as_of = e.as_of
        )
        SELECT
            target.as_of,
            target.size_log_mkt_cap,
            target.book_to_market,
            target.mom_12_1,
            target.quality_roa,
            target.investment_growth,
            target.profitability_gross,
            avg(sample.size_log_mkt_cap) AS size_mean,
            stddev_samp(sample.size_log_mkt_cap) AS size_std,
            avg(sample.book_to_market) AS value_mean,
            stddev_samp(sample.book_to_market) AS value_std,
            avg(sample.mom_12_1) AS momentum_mean,
            stddev_samp(sample.mom_12_1) AS momentum_std,
            avg(sample.quality_roa) AS quality_mean,
            stddev_samp(sample.quality_roa) AS quality_std,
            avg(sample.investment_growth) AS investment_mean,
            stddev_samp(sample.investment_growth) AS investment_std,
            avg(sample.profitability_gross) AS profitability_mean,
            stddev_samp(sample.profitability_gross) AS profitability_std
        FROM equity_characteristics_monthly target
        JOIN latest_point lp ON lp.as_of = target.as_of
        CROSS JOIN sample
        WHERE target.instrument_id = :instrument_id
        GROUP BY
            target.as_of,
            target.size_log_mkt_cap,
            target.book_to_market,
            target.mom_12_1,
            target.quality_roa,
            target.investment_growth,
            target.profitability_gross
    """
    result = await db.execute(text(row_stmt), {"instrument_id": instrument_id})
    row = result.mappings().first()
    if row is None:
        return StyleBiasPayload(exposures=[])

    field_stats = {
        "size_log_mkt_cap": ("size_mean", "size_std"),
        "book_to_market": ("value_mean", "value_std"),
        "mom_12_1": ("momentum_mean", "momentum_std"),
        "quality_roa": ("quality_mean", "quality_std"),
        "investment_growth": ("investment_mean", "investment_std"),
        "profitability_gross": ("profitability_mean", "profitability_std"),
    }

    exposures: list[ResearchMetricPoint] = []
    for field_name, (mean_key, std_key) in field_stats.items():
        raw_value = _to_float(row.get(field_name))
        mean_value = _to_float(row.get(mean_key))
        std_value = _to_float(row.get(std_key))
        z_score: float | None = None
        if raw_value is not None and mean_value is not None and std_value not in (None, 0.0):
            z_score = max(-3.0, min(3.0, (raw_value - mean_value) / std_value))
        exposures.append(
            ResearchMetricPoint(
                label=_STYLE_LABELS[field_name],
                value=round(z_score or 0.0, 4),
                significance=_significance_from_t_stat(z_score),
            )
        )

    return StyleBiasPayload(
        exposures=exposures,
        as_of_date=row["as_of"],
    )


def _latest_risk_row_stmt(org_id: str):
    org_uuid = uuid.UUID(org_id)
    base = (
        select(
            FundRiskMetrics.instrument_id,
            FundRiskMetrics.calc_date,
            FundRiskMetrics.return_1y,
            FundRiskMetrics.cvar_95_12m,
            FundRiskMetrics.volatility_1y,
            FundRiskMetrics.peer_strategy_label,
            func.row_number().over(
                partition_by=FundRiskMetrics.instrument_id,
                order_by=(
                    case((FundRiskMetrics.organization_id == org_uuid, 0), else_=1),
                    FundRiskMetrics.calc_date.desc(),
                ),
            ).label("rn"),
        )
        .where(
            or_(
                FundRiskMetrics.organization_id.is_(None),
                FundRiskMetrics.organization_id == org_uuid,
            ),
        )
    )
    sq = base.subquery()
    return select(
        sq.c.instrument_id,
        sq.c.calc_date,
        sq.c.return_1y,
        sq.c.cvar_95_12m,
        sq.c.volatility_1y,
        sq.c.peer_strategy_label,
    ).where(sq.c.rn == 1)


@router.get(
    "/funds/{instrument_id}",
    response_model=SingleFundResearchResponse,
    summary="Single-fund research surface",
)
async def get_single_fund_research(
    instrument_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> SingleFundResearchResponse:
    instrument = await _resolve_instrument(db, instrument_id)

    end_date = date.today()
    start_date = end_date - timedelta(days=3 * 365)
    fund_returns = await _load_single_returns(db, instrument_id, start_date, end_date)
    try:
        factor_returns = await build_fundamental_factor_returns(db, start_date, end_date)
    except Exception:
        factor_returns = pd.DataFrame()
    market_payload = _build_market_sensitivities_payload(fund_returns, factor_returns)
    style_payload = await _load_style_bias_payload(db, instrument_id)

    return SingleFundResearchResponse(
        instrument_id=instrument.instrument_id,
        instrument_name=instrument.name,
        ticker=instrument.ticker,
        market_sensitivities=market_payload,
        style_bias=style_payload,
    )


@router.get(
    "/scatter",
    response_model=ResearchScatterResponse,
    summary="Multi-fund research scatter surface",
)
async def get_research_scatter(
    limit: int = Query(default=80, ge=2, le=200),
    approved_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: str = Depends(get_org_id),
    user: CurrentUser = Depends(get_current_user),
) -> ResearchScatterResponse:
    risk_sq = _latest_risk_row_stmt(org_id).subquery()
    stmt = (
        select(
            Instrument.instrument_id,
            Instrument.name,
            Instrument.ticker,
            risk_sq.c.return_1y,
            risk_sq.c.cvar_95_12m,
            risk_sq.c.volatility_1y,
            risk_sq.c.peer_strategy_label,
            risk_sq.c.calc_date,
            Instrument.attributes,
        )
        .join(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
        .join(
            risk_sq,
            risk_sq.c.instrument_id == Instrument.instrument_id,
            isouter=True,
        )
        .where(Instrument.is_active.is_(True))
        .where(Instrument.instrument_type == "fund")
    )
    if approved_only:
        stmt = stmt.where(InstrumentOrg.approval_status == "approved")
    stmt = stmt.order_by(
        risk_sq.c.return_1y.desc().nullslast(),
        Instrument.name.asc(),
    ).limit(limit)

    result = await db.execute(stmt)
    rows = result.all()
    if len(rows) < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not enough funds available for research scatter",
        )

    instrument_ids: list[uuid.UUID] = []
    names: list[str] = []
    tickers: list[str | None] = []
    expected_returns: list[float | None] = []
    tail_risks: list[float | None] = []
    volatilities: list[float | None] = []
    strategies: list[str] = []
    as_of_dates: list[date | None] = []
    strategy_map: dict[str, str] = {}

    for row in rows:
        strategy = (
            row.peer_strategy_label
            or (row.attributes or {}).get("strategy_label")
            or "Unclassified"
        )
        instrument_ids.append(row.instrument_id)
        names.append(row.name)
        tickers.append(row.ticker)
        expected_returns.append(_to_float(row.return_1y))
        tail_risks.append(_to_float(row.cvar_95_12m))
        volatilities.append(_to_float(row.volatility_1y))
        strategies.append(strategy)
        as_of_dates.append(row.calc_date)
        strategy_map[str(row.instrument_id)] = strategy

    return ResearchScatterResponse(
        instrument_ids=instrument_ids,
        names=names,
        tickers=tickers,
        expected_returns=expected_returns,
        tail_risks=tail_risks,
        volatilities=volatilities,
        strategies=strategies,
        strategy_map=strategy_map,
        as_of_dates=as_of_dates,
    )
