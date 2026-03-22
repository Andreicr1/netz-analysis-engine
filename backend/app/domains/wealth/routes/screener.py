"""Screener API routes — trigger and query instrument screening.

POST /screener/run      — trigger on-demand screening
GET  /screener/runs     — list screening runs
GET  /screener/runs/{id}— run detail with results
GET  /screener/results  — latest results with filters
GET  /screener/results/{instrument_id} — screening history
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.screening_result import ScreeningResult, ScreeningRun
from app.domains.wealth.schemas.screening import (
    ScreeningResultRead,
    ScreeningRunRead,
    ScreeningRunRequest,
    ScreeningRunResponse,
)
from app.shared.enums import Role

logger = structlog.get_logger()

router = APIRouter(prefix="/screener", tags=["screener"])


def _require_investment_role(actor: Actor) -> None:
    if not actor.has_role(Role.INVESTMENT_TEAM) and not actor.has_role(Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Team or Admin role required",
        )


@router.post(
    "/run",
    response_model=ScreeningRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger on-demand screening",
)
async def trigger_screening(
    body: ScreeningRunRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> ScreeningRunResponse:
    _require_investment_role(actor)

    # Load instruments to screen
    stmt = select(Instrument).where(Instrument.is_active.is_(True))
    if body.instrument_type:
        stmt = stmt.where(Instrument.instrument_type == body.instrument_type)
    if body.block_id:
        stmt = stmt.where(Instrument.block_id == body.block_id)
    if body.instrument_ids:
        stmt = stmt.where(Instrument.instrument_id.in_(body.instrument_ids))

    result = await db.execute(stmt)
    instruments = result.scalars().all()

    if not instruments:
        raise HTTPException(status_code=404, detail="No instruments found matching criteria")

    # Load screening config
    config_svc = ConfigService(db)
    config_l1 = (await config_svc.get("liquid_funds", "screening_layer1", org_id)).value
    config_l2 = (await config_svc.get("liquid_funds", "screening_layer2", org_id)).value
    config_l3 = (await config_svc.get("liquid_funds", "screening_layer3", org_id)).value

    config_hash = hashlib.sha256(
        json.dumps({"l1": config_l1, "l2": config_l2, "l3": config_l3}, sort_keys=True).encode()
    ).hexdigest()

    # Create screening run
    run = ScreeningRun(
        organization_id=org_id,
        run_type="on_demand",
        instrument_count=len(instruments),
        config_hash=config_hash,
    )
    db.add(run)
    await db.flush()

    # Extract instrument data for screening (cross async boundary safely)
    instrument_dicts = [
        {
            "instrument_id": i.instrument_id,
            "instrument_type": i.instrument_type,
            "attributes": dict(i.attributes) if i.attributes else {},
            "block_id": i.block_id,
        }
        for i in instruments
    ]

    # Run screening in thread (pure CPU logic)
    from vertical_engines.wealth.screener.service import ScreenerService

    screener = ScreenerService(config_l1, config_l2, config_l3)
    screening_results = await asyncio.to_thread(
        lambda: [
            screener.screen_instrument(**inst_dict)
            for inst_dict in instrument_dicts
        ]
    )

    # Mark previous results as not current
    for inst_dict in instrument_dicts:
        await db.execute(
            select(ScreeningResult)
            .where(
                ScreeningResult.instrument_id == inst_dict["instrument_id"],
                ScreeningResult.is_current.is_(True),
            )
            .with_for_update()
        )

    # Persist results
    for sr in screening_results:
        screening_result = ScreeningResult(
            organization_id=org_id,
            instrument_id=sr.instrument_id,
            run_id=run.run_id,
            overall_status=sr.overall_status,
            score=sr.score,
            failed_at_layer=sr.failed_at_layer,
            layer_results=sr.layer_results_dict,
            required_analysis_type=sr.required_analysis_type,
            is_current=True,
        )
        db.add(screening_result)

    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return ScreeningRunResponse(
        run_id=run.run_id,
        status="completed",
        instrument_count=len(instruments),
    )


@router.get(
    "/runs",
    response_model=list[ScreeningRunRead],
    summary="List screening runs",
)
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[ScreeningRunRead]:
    result = await db.execute(
        select(ScreeningRun)
        .order_by(ScreeningRun.started_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()
    return [ScreeningRunRead.model_validate(r) for r in runs]


@router.get(
    "/runs/{run_id}",
    response_model=ScreeningRunRead,
    summary="Get screening run detail",
)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> ScreeningRunRead:
    result = await db.execute(
        select(ScreeningRun).where(ScreeningRun.run_id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Screening run not found")
    return ScreeningRunRead.model_validate(run)


@router.get(
    "/results",
    response_model=list[ScreeningResultRead],
    summary="Latest screening results with filters",
)
async def list_results(
    overall_status: str | None = Query(None, description="PASS|FAIL|WATCHLIST"),
    instrument_type: str | None = Query(None),
    block_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[ScreeningResultRead]:
    stmt = (
        select(
            ScreeningResult,
            Instrument.name.label("inst_name"),
            Instrument.isin.label("inst_isin"),
            Instrument.ticker.label("inst_ticker"),
            Instrument.instrument_type.label("inst_type"),
            Instrument.block_id.label("inst_block_id"),
            Instrument.geography.label("inst_geography"),
            Instrument.currency.label("inst_currency"),
            Instrument.attributes["sec_crd_number"].astext.label("inst_manager_crd"),
            Instrument.attributes["strategy"].astext.label("inst_strategy"),
            Instrument.attributes["aum"].astext.label("inst_aum"),
        )
        .join(
            Instrument,
            ScreeningResult.instrument_id == Instrument.instrument_id,
        )
        .where(ScreeningResult.is_current.is_(True))
    )
    if overall_status:
        stmt = stmt.where(ScreeningResult.overall_status == overall_status)
    if instrument_type:
        stmt = stmt.where(Instrument.instrument_type == instrument_type)
    if block_id:
        stmt = stmt.where(Instrument.block_id == block_id)

    stmt = stmt.order_by(ScreeningResult.score.desc().nulls_last()).limit(limit)
    result = await db.execute(stmt)
    rows = result.all()

    enriched: list[ScreeningResultRead] = []
    for row in rows:
        sr = row[0]
        data = ScreeningResultRead.model_validate(sr)
        data.name = row.inst_name
        data.isin = row.inst_isin
        data.ticker = row.inst_ticker
        data.instrument_type = row.inst_type
        data.block_id = row.inst_block_id
        data.geography = row.inst_geography
        data.currency = row.inst_currency
        data.manager_crd = row.inst_manager_crd
        data.strategy = row.inst_strategy
        try:
            data.aum = float(row.inst_aum) if row.inst_aum else None
        except (ValueError, TypeError):
            data.aum = None
        enriched.append(data)

    return enriched


@router.get(
    "/results/{instrument_id}",
    response_model=list[ScreeningResultRead],
    summary="Screening history for instrument",
)
async def get_instrument_results(
    instrument_id: uuid.UUID,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[ScreeningResultRead]:
    result = await db.execute(
        select(ScreeningResult)
        .where(ScreeningResult.instrument_id == instrument_id)
        .order_by(ScreeningResult.screened_at.desc())
        .limit(limit)
    )
    results = result.scalars().all()
    return [ScreeningResultRead.model_validate(r) for r in results]
