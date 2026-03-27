"""Holdings Exploder — I/O layer for portfolio-through-fund N-PORT decomposition.

Given a model portfolio, explodes its composition into underlying holdings
by reading sec_nport_holdings weighted by fund_selection_schema allocations.

This is the I/O boundary. Pure math lives in
vertical_engines/wealth/monitoring/overlap_scanner.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.shared.models import SecNportHolding

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class HoldingRow:
    """Single exploded holding — one CUSIP contributed by one fund."""

    cusip: str
    issuer_name: str | None
    sector: str | None
    fund_instrument_id: uuid.UUID
    fund_weight: float  # weight of the fund in the portfolio (0.0-1.0)
    pct_of_fund_nav: float  # pct_of_nav from N-PORT (0.0-100.0)
    weighted_pct: float  # fund_weight × (pct_of_fund_nav / 100.0)


async def fetch_portfolio_holdings_exploded(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
) -> list[HoldingRow]:
    """Explode a model portfolio into weighted underlying holdings.

    Algorithm:
    1. Load fund_selection_schema from ModelPortfolio
    2. For each fund, resolve sec_cik from Instrument.attributes
    3. Query latest sec_nport_holdings per cik (global table, no RLS)
    4. Weight each holding by fund allocation

    Returns empty list if portfolio has no fund_selection or no CIK mappings.
    """
    # 1. Load portfolio
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None or not portfolio.fund_selection_schema:
        return []

    funds = portfolio.fund_selection_schema.get("funds", [])
    if not funds:
        return []

    # Build instrument_id → weight map
    fund_weights: dict[uuid.UUID, float] = {}
    for f in funds:
        iid = f.get("instrument_id")
        w = f.get("weight")
        if iid and w:
            fund_weights[uuid.UUID(iid)] = w

    if not fund_weights:
        return []

    # 2. Resolve sec_cik for each instrument
    instrument_ids = list(fund_weights.keys())
    inst_stmt = select(
        Instrument.instrument_id,
        Instrument.attributes,
    ).where(Instrument.instrument_id.in_(instrument_ids))
    inst_result = await db.execute(inst_stmt)

    instrument_to_cik: dict[uuid.UUID, str] = {}
    for row in inst_result.all():
        attrs = row.attributes or {}
        cik = attrs.get("sec_cik")
        if cik:
            instrument_to_cik[row.instrument_id] = str(cik)

    if not instrument_to_cik:
        logger.warning(
            "no_cik_mappings_for_portfolio",
            portfolio_id=str(portfolio_id),
            n_funds=len(fund_weights),
        )
        return []

    # Build reverse map: cik → instrument_id
    cik_to_instrument: dict[str, uuid.UUID] = {
        cik: iid for iid, cik in instrument_to_cik.items()
    }
    cik_list = list(cik_to_instrument.keys())

    # 3. Query latest N-PORT report date per CIK, then fetch holdings
    # sec_nport_holdings is a GLOBAL table — no RLS, no SET LOCAL
    latest_date_subq = (
        select(
            SecNportHolding.cik,
            func.max(SecNportHolding.report_date).label("max_date"),
        )
        .where(SecNportHolding.cik.in_(cik_list))
        .group_by(SecNportHolding.cik)
        .subquery()
    )

    holdings_stmt = (
        select(
            SecNportHolding.cik,
            SecNportHolding.cusip,
            SecNportHolding.issuer_name,
            SecNportHolding.sector,
            SecNportHolding.pct_of_nav,
        )
        .join(
            latest_date_subq,
            (SecNportHolding.cik == latest_date_subq.c.cik)
            & (SecNportHolding.report_date == latest_date_subq.c.max_date),
        )
        .where(SecNportHolding.cik.in_(cik_list))
    )

    holdings_result = await db.execute(holdings_stmt)

    # 4. Weight each holding
    rows: list[HoldingRow] = []
    for h in holdings_result.all():
        instrument_id = cik_to_instrument[h.cik]
        fund_w = fund_weights[instrument_id]
        pct = float(h.pct_of_nav) if h.pct_of_nav is not None else 0.0

        rows.append(HoldingRow(
            cusip=h.cusip,
            issuer_name=h.issuer_name,
            sector=h.sector,
            fund_instrument_id=instrument_id,
            fund_weight=fund_w,
            pct_of_fund_nav=pct,
            weighted_pct=fund_w * (pct / 100.0),
        ))

    logger.info(
        "portfolio_holdings_exploded",
        portfolio_id=str(portfolio_id),
        n_funds=len(instrument_to_cik),
        n_holdings=len(rows),
    )

    return rows
