"""Instrument Universe API routes — CRUD + import for polymorphic instruments.

Replaces the deprecated funds.py routes. Supports fund, bond, and equity
instrument types. Yahoo Finance import and CSV bulk upload.
"""

from __future__ import annotations

import io
import uuid

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.domains.wealth.schemas.instrument import (
    InstrumentCreate,
    InstrumentImportCsvResponse,
    InstrumentImportYahoo,
    InstrumentRead,
    InstrumentUpdate,
)
from app.shared.enums import Role

logger = structlog.get_logger()

router = APIRouter(prefix="/instruments", tags=["instruments"])

_MAX_CSV_SIZE = 5 * 1024 * 1024  # 5MB


def _require_investment_role(actor: Actor) -> None:
    if not actor.has_role(Role.INVESTMENT_TEAM) and not actor.has_role(Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Team or Admin role required",
        )


@router.get(
    "",
    response_model=list[InstrumentRead],
    summary="List instruments in the universe",
)
async def list_instruments(
    instrument_type: str | None = Query(None, description="Filter by type: fund|bond|equity"),
    block_id: str | None = Query(None, description="Filter by allocation block"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    approval_status: str | None = Query(None, description="Filter by approval status"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[InstrumentRead]:
    stmt = select(Instrument).join(
        InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id,
    )
    if instrument_type:
        stmt = stmt.where(Instrument.instrument_type == instrument_type)
    if block_id:
        stmt = stmt.where(InstrumentOrg.block_id == block_id)
    if is_active is not None:
        stmt = stmt.where(Instrument.is_active == is_active)
    if approval_status:
        stmt = stmt.where(InstrumentOrg.approval_status == approval_status)
    stmt = stmt.order_by(Instrument.name)
    result = await db.execute(stmt)
    instruments = result.scalars().all()
    return [InstrumentRead.model_validate(i) for i in instruments]


@router.get(
    "/{instrument_id}",
    response_model=InstrumentRead,
    summary="Get single instrument detail",
)
async def get_instrument(
    instrument_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> InstrumentRead:
    result = await db.execute(
        select(Instrument).where(Instrument.instrument_id == instrument_id),
    )
    instrument = result.scalar_one_or_none()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return InstrumentRead.model_validate(instrument)


@router.patch(
    "/{instrument_id}",
    response_model=InstrumentRead,
    summary="Update instrument fields",
)
async def update_instrument(
    instrument_id: uuid.UUID,
    body: InstrumentUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> InstrumentRead:
    _require_investment_role(actor)
    result = await db.execute(
        select(Instrument).where(Instrument.instrument_id == instrument_id),
    )
    instrument = result.scalar_one_or_none()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(instrument, field, value)

    await db.flush()
    await db.refresh(instrument)
    await db.commit()
    return InstrumentRead.model_validate(instrument)


@router.post(
    "",
    response_model=InstrumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create instrument manually",
)
async def create_instrument(
    body: InstrumentCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> InstrumentRead:
    _require_investment_role(actor)
    instrument = Instrument(
        instrument_type=body.instrument_type,
        name=body.name,
        isin=body.isin,
        ticker=body.ticker,
        bloomberg_ticker=body.bloomberg_ticker,
        asset_class=body.asset_class,
        geography=body.geography,
        currency=body.currency,
        attributes=body.attributes,
    )
    db.add(instrument)
    await db.flush()

    # Create org-scoped link with block assignment
    instrument_org = InstrumentOrg(
        instrument_id=instrument.instrument_id,
        organization_id=org_id,
        block_id=body.block_id,
    )
    db.add(instrument_org)
    await db.flush()
    await db.refresh(instrument)
    await db.commit()
    return InstrumentRead.model_validate(instrument)


@router.post(
    "/import/yahoo",
    response_model=list[InstrumentRead],
    status_code=status.HTTP_201_CREATED,
    summary="Import instruments from Yahoo Finance by ticker",
)
async def import_from_yahoo(
    body: InstrumentImportYahoo,
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> list[InstrumentRead]:
    _require_investment_role(actor)

    import asyncio

    from app.services.providers import get_instrument_provider

    provider = get_instrument_provider()
    raw_data = await asyncio.to_thread(provider.fetch_batch, body.tickers)

    created: list[Instrument] = []
    for data in raw_data:
        instrument = Instrument(
            instrument_type=data.instrument_type,
            name=data.name,
            isin=data.isin,
            ticker=data.ticker,
            asset_class=data.asset_class,
            geography=data.geography,
            currency=data.currency,
            attributes=data.raw_attributes,
        )
        db.add(instrument)
        created.append(instrument)

    if created:
        await db.flush()
        # Create org-scoped links for each imported instrument
        for inst in created:
            instrument_org = InstrumentOrg(
                instrument_id=inst.instrument_id,
                organization_id=org_id,
            )
            db.add(instrument_org)
        await db.flush()
        for inst in created:
            await db.refresh(inst)
        await db.commit()

    return [InstrumentRead.model_validate(i) for i in created]


@router.post(
    "/import/csv",
    response_model=InstrumentImportCsvResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk import instruments via CSV",
)
async def import_from_csv(
    instrument_type: str = Query(..., description="Instrument type: fund|bond|equity"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> InstrumentImportCsvResponse:
    _require_investment_role(actor)

    if instrument_type not in ("fund", "bond", "equity"):
        raise HTTPException(status_code=400, detail="instrument_type must be fund, bond, or equity")

    content = await file.read()
    if len(content) > _MAX_CSV_SIZE:
        raise HTTPException(status_code=400, detail="CSV file exceeds 5MB limit")

    from app.services.providers.csv_import_adapter import CsvImportAdapter

    adapter = CsvImportAdapter()
    result = adapter.parse(io.BytesIO(content), instrument_type)

    created_instruments: list[Instrument] = []
    for data in result.instruments:
        instrument = Instrument(
            instrument_type=data.instrument_type,
            name=data.name,
            isin=data.isin,
            ticker=data.ticker,
            asset_class=data.asset_class,
            geography=data.geography,
            currency=data.currency,
            attributes=data.raw_attributes,
        )
        db.add(instrument)
        created_instruments.append(instrument)

    if created_instruments:
        await db.flush()
        # Create org-scoped links for each imported instrument
        for inst in created_instruments:
            instrument_org = InstrumentOrg(
                instrument_id=inst.instrument_id,
                organization_id=org_id,
            )
            db.add(instrument_org)
        await db.commit()

    return InstrumentImportCsvResponse(
        imported=result.imported,
        skipped=result.skipped,
        errors=[
            {"row": e.row_number, "column": e.column, "message": e.message}
            for e in result.errors
        ],
    )
