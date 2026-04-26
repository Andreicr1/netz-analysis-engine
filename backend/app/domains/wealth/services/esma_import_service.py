"""ESMA fund import service — creates an Instrument from ESMA data.

Reads esma_securities (ISIN→fund_lei) + esma_funds (fund-level metadata),
enriches with geography/currency from domicile, and inserts into
instruments_universe.

Post-Q11B: lookup by ISIN goes through esma_securities; fund metadata
comes from esma_funds via fund_lei JOIN.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.shared.models import EsmaFund, EsmaManager, EsmaSecurity

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
    """Create an Instrument in instruments_universe from ESMA data.

    Looks up esma_securities by ISIN → fund via fund_lei → esma_funds.
    Determines currency and geography from domicile.
    Populates attributes JSONB with structure, domicile, fund_type, fund_lei.
    """
    # Check if instrument already exists globally by ISIN
    existing_stmt = select(Instrument).where(Instrument.isin == isin)
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        # Check if already linked to this org
        existing_link = (await db.execute(
            select(InstrumentOrg).where(
                InstrumentOrg.instrument_id == existing.instrument_id,
                InstrumentOrg.organization_id == org_id,
            ),
        )).scalar_one_or_none()
        if existing_link:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Instrument with ISIN {isin} already exists in your universe",
            )
        # Link existing global instrument to this org
        org_link = InstrumentOrg(
            organization_id=org_id,
            instrument_id=existing.instrument_id,
            block_id=block_id,
            approval_status="pending",
        )
        db.add(org_link)
        await db.flush()
        return existing

    # Look up security by ISIN (esma_securities)
    sec_stmt = select(EsmaSecurity).where(EsmaSecurity.isin == isin)
    security = (await db.execute(sec_stmt)).scalar_one_or_none()

    # Fetch ESMA fund — via security.fund_lei if available, else try LEI direct
    fund = None
    if security:
        fund_stmt = select(EsmaFund).where(EsmaFund.lei == security.fund_lei)
        fund = (await db.execute(fund_stmt)).scalar_one_or_none()
    else:
        # Fallback: try isin as LEI (pre-FIRDS transition period)
        fund_stmt = select(EsmaFund).where(EsmaFund.lei == isin)
        fund = (await db.execute(fund_stmt)).scalar_one_or_none()

    if fund is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ESMA fund for ISIN {isin} not found",
        )

    # Fetch manager name
    mgr_stmt = select(EsmaManager.company_name).where(
        EsmaManager.esma_id == fund.esma_manager_id,
    )
    manager_name = (await db.execute(mgr_stmt)).scalar_one_or_none()

    # Resolve geography/currency from domicile
    domicile = fund.domicile or ""
    geography, currency = _DOMICILE_MAP.get(domicile, ("dm_europe", "EUR"))

    # Build attributes
    attributes: dict[str, object] = {
        "structure": "UCITS",
        "domicile": domicile,
        "fund_type": fund.fund_type,
        "fund_lei": fund.lei,
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
    if hasattr(fund, "strategy_label") and fund.strategy_label:
        attributes["strategy_label"] = fund.strategy_label

    # Use security name if available, else fund name
    name = security.full_name if security and security.full_name else fund.fund_name

    instrument = Instrument(
        instrument_type="fund",
        name=name,
        isin=isin,
        ticker=fund.yahoo_ticker,  # legacy fallback — Q11C migrates to provider-aware
        asset_class="alternatives",
        geography=geography,
        currency=currency,
        attributes=attributes,
    )
    db.add(instrument)
    await db.flush()

    # Create org-scoped link
    org_link = InstrumentOrg(
        organization_id=org_id,
        instrument_id=instrument.instrument_id,
        block_id=block_id,
        approval_status="pending",
    )
    db.add(org_link)
    await db.flush()
    await db.refresh(instrument)
    return instrument
