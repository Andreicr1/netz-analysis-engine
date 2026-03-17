"""Correlation regime API routes.

GET /analytics/correlation-regime/{profile}                — portfolio correlation analysis
GET /analytics/correlation-regime/{profile}/pair/{a}/{b}   — pair drill-down
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime

import numpy as np
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.schemas.correlation_regime import (
    ConcentrationRead,
    CorrelationRegimeRead,
    InstrumentCorrelationRead,
    PairCorrelationTimeseriesRead,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/analytics/correlation-regime", tags=["correlation-regime"])


@router.get(
    "/{profile}",
    response_model=CorrelationRegimeRead,
    summary="Correlation regime analysis for a portfolio",
)
async def get_correlation_regime(
    profile: str,
    window_days: int = Query(60, ge=10, le=252),
    baseline_days: int = Query(504, ge=60, le=2520),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> CorrelationRegimeRead:
    # 1. Load live model portfolio
    mp_stmt = select(ModelPortfolio).where(
        ModelPortfolio.profile == profile,
        ModelPortfolio.status == "live",
    )
    mp_result = await db.execute(mp_stmt)
    live_portfolio = mp_result.scalar()

    if not live_portfolio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No live model portfolio found for profile '{profile}'",
        )

    # 2. Extract instrument_ids from fund_selection_schema
    fund_selection = live_portfolio.fund_selection_schema or {}
    instrument_ids: list[uuid.UUID] = []
    for block_funds in fund_selection.values():
        if isinstance(block_funds, list):
            for f in block_funds:
                iid = f["instrument_id"] if isinstance(f, dict) else str(f)
                try:
                    instrument_ids.append(uuid.UUID(iid))
                except (ValueError, AttributeError):
                    pass
        elif isinstance(block_funds, dict) and "instrument_id" in block_funds:
            try:
                instrument_ids.append(uuid.UUID(block_funds["instrument_id"]))
            except (ValueError, AttributeError):
                pass

    if len(instrument_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Need at least 2 instruments for correlation analysis",
        )

    # Deduplicate while preserving order
    seen: set[uuid.UUID] = set()
    unique_ids: list[uuid.UUID] = []
    for iid in instrument_ids:
        if iid not in seen:
            seen.add(iid)
            unique_ids.append(iid)
    instrument_ids = unique_ids

    # 3. Load instrument names
    inst_stmt = select(Instrument.instrument_id, Instrument.name).where(
        Instrument.instrument_id.in_(instrument_ids)
    )
    inst_result = await db.execute(inst_stmt)
    name_map = {row.instrument_id: row.name for row in inst_result.all()}

    # 4. Load NavTimeseries returns — date intersection, NOT forward-fill
    total_days = baseline_days + window_days
    nav_stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
        .where(
            NavTimeseries.instrument_id.in_(instrument_ids),
            NavTimeseries.return_1d.isnot(None),
        )
        .order_by(NavTimeseries.nav_date.desc())
        .limit(total_days * len(instrument_ids))
    )
    nav_result = await db.execute(nav_stmt)
    nav_rows = nav_result.all()

    # Group by instrument_id → {date: return}
    returns_by_inst: dict[uuid.UUID, dict[date, float]] = {}
    for row in nav_rows:
        returns_by_inst.setdefault(row.instrument_id, {})[row.nav_date] = float(row.return_1d)

    # Date intersection: only dates where ALL instruments have data
    if returns_by_inst:
        date_sets = [set(dates.keys()) for dates in returns_by_inst.values()]
        common_dates = sorted(set.intersection(*date_sets), reverse=False)
    else:
        common_dates = []

    if len(common_dates) < 45:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient overlapping NAV data: {len(common_dates)} days (min 45)",
        )

    # Build returns matrix (T x N) — ordered by instrument_ids
    ordered_ids = [iid for iid in instrument_ids if iid in returns_by_inst]
    T = len(common_dates)
    N = len(ordered_ids)
    returns_matrix = np.zeros((T, N))
    for j, iid in enumerate(ordered_ids):
        inst_returns = returns_by_inst[iid]
        for i, d in enumerate(common_dates):
            returns_matrix[i, j] = inst_returns[d]

    # Names and IDs as tuples
    inst_id_strs = tuple(str(iid) for iid in ordered_ids)
    inst_names = tuple(name_map.get(iid, str(iid)) for iid in ordered_ids)

    # 5. Run correlation analysis in thread
    from vertical_engines.wealth.correlation.service import CorrelationService

    svc = CorrelationService(config={
        "window_days": window_days,
        "baseline_window_days": baseline_days,
    })
    result = await asyncio.to_thread(
        svc.analyze_portfolio_correlation,
        instrument_ids=inst_id_strs,
        instrument_names=inst_names,
        returns_matrix=returns_matrix,
        profile=profile,
    )

    # 6. Build response
    contagion_pairs = [
        InstrumentCorrelationRead(
            instrument_a_id=uuid.UUID(p.instrument_a_id),
            instrument_a_name=p.instrument_a_name,
            instrument_b_id=uuid.UUID(p.instrument_b_id),
            instrument_b_name=p.instrument_b_name,
            current_correlation=p.current_correlation,
            baseline_correlation=p.baseline_correlation,
            correlation_change=p.correlation_change,
            is_contagion=p.is_contagion,
        )
        for p in result.contagion_pairs
    ]

    concentration = ConcentrationRead(
        eigenvalues=list(result.concentration.eigenvalues),
        explained_variance_ratios=list(result.concentration.explained_variance_ratios),
        first_eigenvalue_ratio=result.concentration.first_eigenvalue_ratio,
        concentration_status=result.concentration.concentration_status,
        diversification_ratio=result.concentration.diversification_ratio,
        dr_alert=result.concentration.dr_alert,
        absorption_ratio=result.concentration.absorption_ratio,
        absorption_status=result.concentration.absorption_status,
    )

    return CorrelationRegimeRead(
        profile=result.profile,
        instrument_count=result.instrument_count,
        window_days=result.window_days,
        correlation_matrix=[list(row) for row in result.correlation_matrix],
        instrument_labels=list(result.instrument_labels),
        contagion_pairs=contagion_pairs,
        concentration=concentration,
        average_correlation=result.average_correlation,
        baseline_average_correlation=result.baseline_average_correlation,
        regime_shift_detected=result.regime_shift_detected,
        computed_at=datetime.fromisoformat(result.computed_at) if isinstance(result.computed_at, str) else result.computed_at,
    )


@router.get(
    "/{profile}/pair/{inst_a}/{inst_b}",
    response_model=PairCorrelationTimeseriesRead,
    summary="Rolling correlation timeseries for a pair of instruments",
)
async def get_pair_correlation(
    profile: str,
    inst_a: uuid.UUID,
    inst_b: uuid.UUID,
    window_days: int = Query(60, ge=10, le=252),
    lookback_days: int = Query(504, ge=60, le=2520),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> PairCorrelationTimeseriesRead:
    # Load instrument names
    inst_stmt = select(Instrument.instrument_id, Instrument.name).where(
        Instrument.instrument_id.in_([inst_a, inst_b])
    )
    inst_result = await db.execute(inst_stmt)
    name_map = {row.instrument_id: row.name for row in inst_result.all()}

    if len(name_map) < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both instruments not found",
        )

    # Load returns
    nav_stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
        .where(
            NavTimeseries.instrument_id.in_([inst_a, inst_b]),
            NavTimeseries.return_1d.isnot(None),
        )
        .order_by(NavTimeseries.nav_date)
    )
    nav_result = await db.execute(nav_stmt)

    returns_a: dict[date, float] = {}
    returns_b: dict[date, float] = {}
    for row in nav_result.all():
        if row.instrument_id == inst_a:
            returns_a[row.nav_date] = float(row.return_1d)
        else:
            returns_b[row.nav_date] = float(row.return_1d)

    # Date intersection
    common_dates = sorted(set(returns_a.keys()) & set(returns_b.keys()))
    if len(common_dates) < window_days:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient overlapping data: {len(common_dates)} days (need {window_days})",
        )

    # Limit to lookback
    common_dates = common_dates[-lookback_days:]

    # Compute rolling correlation
    arr_a = np.array([returns_a[d] for d in common_dates])
    arr_b = np.array([returns_b[d] for d in common_dates])

    dates_out: list[str] = []
    corrs_out: list[float] = []

    for i in range(window_days, len(common_dates) + 1):
        window_a = arr_a[i - window_days:i]
        window_b = arr_b[i - window_days:i]
        corr = float(np.corrcoef(window_a, window_b)[0, 1])
        dates_out.append(common_dates[i - 1].isoformat())
        corrs_out.append(round(corr, 6))

    return PairCorrelationTimeseriesRead(
        instrument_a_id=inst_a,
        instrument_a_name=name_map[inst_a],
        instrument_b_id=inst_b,
        instrument_b_name=name_map[inst_b],
        dates=dates_out,
        correlations=corrs_out,
        window_days=window_days,
    )
