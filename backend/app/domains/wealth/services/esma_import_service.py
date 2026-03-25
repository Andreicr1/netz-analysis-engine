"""ESMA fund import service — creates an Instrument from ESMA data.

Reads esma_funds + esma_isin_ticker_map, enriches with geography/currency
from domicile, and inserts into instruments_universe.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.instrument import Instrument
from app.shared.models import EsmaFund, EsmaIsinTickerMap, EsmaManager

# Map ESMA domicile (ISO-2) → geography + currency
_DOMICILE_MAP: dict[str, tuple[str, str]] = {
    "IE": ("dm_europe", "EUR"),
    "LU": ("dm_europe", "EUR"),
    "DE": ("dm_europe", "EUR"),
    "FR": ("dm_europe", "EUR"),
    "NL": ("dm_europe", "EUR"),
    "AT": ("dm_europe", "EUR"),
    "BE": ("dm_europe", "EUR"),
    "ES": ("dm_europe", "EUR"),
    "IT": ("dm_europe", "EUR"),
    "PT": ("dm_europe", "EUR"),
    "FI": ("dm_europe", "EUR"),
    "SE": ("dm_europe", "SEK"),
    "DK": ("dm_europe", "DKK"),
    "NO": ("dm_europe", "NOK"),
    "GB": ("dm_europe", "GBP"),
    "CH": ("dm_europe", "CHF"),
    "MT": ("dm_europe", "EUR"),
    "CY": ("dm_europe", "EUR"),
    "LI": ("dm_europe", "CHF"),
}


async def import_esma_fund_to_universe(
    db: AsyncSession,
    org_id: uuid.UUID,
    isin: str,
    *,
    block_id: str | None = None,
    strategy: str | None = None,
) -> Instrument:
    """Create an Instrument in instruments_universe from esma_funds.

    Looks up fund_name, esma_manager_id, domicile from esma_funds.
    Looks up yahoo_ticker from esma_isin_ticker_map.
    Determines currency and geography from domicile.
    Populates attributes JSONB with structure, domicile, fund_type, host_member_states.
    """
    # Check not already imported
    existing_stmt = select(Instrument).where(
        Instrument.isin == isin,
        Instrument.organization_id == org_id,
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Instrument with ISIN {isin} already exists in universe",
        )

    # Fetch ESMA fund
    fund_stmt = select(EsmaFund).where(EsmaFund.isin == isin)
    fund = (await db.execute(fund_stmt)).scalar_one_or_none()
    if fund is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ESMA fund with ISIN {isin} not found",
        )

    # Fetch ticker map
    ticker_stmt = select(EsmaIsinTickerMap).where(EsmaIsinTickerMap.isin == isin)
    ticker_row = (await db.execute(ticker_stmt)).scalar_one_or_none()

    # Fetch manager name
    mgr_stmt = select(EsmaManager.company_name).where(
        EsmaManager.esma_id == fund.esma_manager_id
    )
    manager_name = (await db.execute(mgr_stmt)).scalar_one_or_none()

    # Resolve geography/currency from domicile
    domicile = fund.domicile or ""
    geography, currency = _DOMICILE_MAP.get(domicile, ("dm_europe", "EUR"))

    # Build attributes — chk_fund_attrs requires aum_usd, manager_name, inception_date
    attributes: dict[str, object] = {
        "structure": "UCITS",
        "domicile": domicile,
        "fund_type": fund.fund_type,
        "esma_manager_id": fund.esma_manager_id,
        "source": "esma",
        "manager_name": manager_name,
        "aum_usd": None,
        "inception_date": None,
    }
    if fund.host_member_states:
        attributes["host_member_states"] = fund.host_member_states
    if strategy:
        attributes["strategy"] = strategy

    instrument = Instrument(
        organization_id=org_id,
        instrument_type="fund",
        name=fund.fund_name,
        isin=isin,
        ticker=ticker_row.yahoo_ticker if ticker_row else fund.yahoo_ticker,
        asset_class="alternatives",
        geography=geography,
        currency=currency,
        block_id=block_id,
        approval_status="pending",
        attributes=attributes,
    )
    db.add(instrument)
    await db.flush()
    await db.refresh(instrument)
    return instrument
