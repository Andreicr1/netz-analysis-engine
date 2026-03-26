"""Polymorphic NAV reader — unified access to fund and portfolio NAV series.

Provides a single interface for reading NAV time series regardless of whether
the entity is an instrument (nav_timeseries) or a model portfolio
(model_portfolio_nav). This enables the quant analytics layer (QuantAnalyzer,
fact_sheet, chart_builder, track_record) to treat model portfolios as funds.

Usage:
    # Async (routes, workers)
    series = await fetch_nav_series(db, entity_id, start, end)

    # Sync (track_record, quant_analyzer — via asyncio.to_thread)
    series = fetch_nav_series_sync(db, entity_id, start, end)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav
from app.domains.wealth.models.nav import NavTimeseries


@dataclass(frozen=True, slots=True)
class NavRow:
    """Normalized NAV row — works for both funds and model portfolios."""

    entity_id: uuid.UUID
    nav_date: date
    nav: float
    daily_return: float | None


async def is_model_portfolio(db: AsyncSession, entity_id: uuid.UUID) -> bool:
    """Check if entity_id refers to a model portfolio."""
    result = await db.execute(
        select(ModelPortfolio.id).where(ModelPortfolio.id == entity_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


def is_model_portfolio_sync(db: Session, entity_id: uuid.UUID) -> bool:
    """Sync version — for use in to_thread contexts."""
    result = db.execute(
        select(ModelPortfolio.id).where(ModelPortfolio.id == entity_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def fetch_nav_series(
    db: AsyncSession,
    entity_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[NavRow]:
    """Fetch NAV series for a fund or model portfolio (async).

    Automatically detects entity type and queries the correct table.
    Returns rows ordered by nav_date ascending.
    """
    is_portfolio = await is_model_portfolio(db, entity_id)

    if is_portfolio:
        stmt = select(
            ModelPortfolioNav.portfolio_id,
            ModelPortfolioNav.nav_date,
            ModelPortfolioNav.nav,
            ModelPortfolioNav.daily_return,
        ).where(ModelPortfolioNav.portfolio_id == entity_id)

        if start_date is not None:
            stmt = stmt.where(ModelPortfolioNav.nav_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(ModelPortfolioNav.nav_date <= end_date)

        stmt = stmt.order_by(ModelPortfolioNav.nav_date)
    else:
        stmt = select(
            NavTimeseries.instrument_id,
            NavTimeseries.nav_date,
            NavTimeseries.nav,
            NavTimeseries.return_1d,
        ).where(NavTimeseries.instrument_id == entity_id)

        if start_date is not None:
            stmt = stmt.where(NavTimeseries.nav_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(NavTimeseries.nav_date <= end_date)

        stmt = stmt.order_by(NavTimeseries.nav_date)

    result = await db.execute(stmt)
    return [
        NavRow(
            entity_id=row[0],
            nav_date=row[1],
            nav=float(row[2]) if row[2] is not None else 0.0,
            daily_return=float(row[3]) if row[3] is not None else None,
        )
        for row in result.all()
    ]


def fetch_nav_series_sync(
    db: Session,
    entity_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[NavRow]:
    """Fetch NAV series for a fund or model portfolio (sync).

    Same as fetch_nav_series but for sync Session (used in to_thread contexts).
    """
    is_portfolio = is_model_portfolio_sync(db, entity_id)

    if is_portfolio:
        stmt = select(
            ModelPortfolioNav.portfolio_id,
            ModelPortfolioNav.nav_date,
            ModelPortfolioNav.nav,
            ModelPortfolioNav.daily_return,
        ).where(ModelPortfolioNav.portfolio_id == entity_id)

        if start_date is not None:
            stmt = stmt.where(ModelPortfolioNav.nav_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(ModelPortfolioNav.nav_date <= end_date)

        stmt = stmt.order_by(ModelPortfolioNav.nav_date)
    else:
        stmt = select(
            NavTimeseries.instrument_id,
            NavTimeseries.nav_date,
            NavTimeseries.nav,
            NavTimeseries.return_1d,
        ).where(NavTimeseries.instrument_id == entity_id)

        if start_date is not None:
            stmt = stmt.where(NavTimeseries.nav_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(NavTimeseries.nav_date <= end_date)

        stmt = stmt.order_by(NavTimeseries.nav_date)

    result = db.execute(stmt)
    return [
        NavRow(
            entity_id=row[0],
            nav_date=row[1],
            nav=float(row[2]) if row[2] is not None else 0.0,
            daily_return=float(row[3]) if row[3] is not None else None,
        )
        for row in result.all()
    ]


async def fetch_returns_only(
    db: AsyncSession,
    entity_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[float]:
    """Fetch only daily returns as a flat list (async).

    Convenience for CVaR, Sharpe, drawdown computations.
    Returns ordered by nav_date ascending, filtering out None values.
    """
    rows = await fetch_nav_series(db, entity_id, start_date, end_date)
    return [r.daily_return for r in rows if r.daily_return is not None]
