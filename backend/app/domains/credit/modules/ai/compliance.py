"""AI Compliance sub-router — obligations, linker."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.extraction.obligation_extractor import extract_obligation_register
from ai_engine.knowledge.linker import (
    get_entity_links_snapshot,
    get_obligation_status_snapshot,
    run_cross_container_linking,
)
from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_readonly_allowed, require_roles
from app.domains.credit.modules.ai.models import ObligationRegister
from app.domains.credit.modules.ai.routes._helpers import (
    _envelope_from_rows,
    _limit,
    _offset,
    _utcnow,
)
from app.domains.credit.modules.ai.schemas import (
    ObligationRegisterItem,
    ObligationRegisterResponse,
)
from app.shared.enums import Role

router = APIRouter()


@router.get("/obligations/register", response_model=ObligationRegisterResponse)
def get_obligation_register(
    fund_id: uuid.UUID,
    refresh: bool = Query(default=False, description="When true, triggers AI extraction instead of returning cached results"),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
) -> ObligationRegisterResponse:
    """Return obligation register for a fund."""
    if not refresh:
        existing = list(
            db.execute(
                select(ObligationRegister)
                .where(ObligationRegister.fund_id == fund_id)
                .order_by(ObligationRegister.as_of.desc())
                .limit(limit)
                .offset(offset)
            ).scalars().all()
        )
        if existing:
            as_of, data_latency, data_quality = _envelope_from_rows(existing)
            items = [ObligationRegisterItem.model_validate(row) for row in existing]
            return ObligationRegisterResponse(asOf=as_of, dataLatency=data_latency, dataQuality=data_quality, items=items)

    extract_obligation_register(db, fund_id=fund_id, actor_id=actor.actor_id)
    rows = list(
        db.execute(
            select(ObligationRegister)
            .where(ObligationRegister.fund_id == fund_id)
            .order_by(ObligationRegister.as_of.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
    )
    as_of, data_latency, data_quality = _envelope_from_rows(rows)
    items = [ObligationRegisterItem.model_validate(row) for row in rows]
    return ObligationRegisterResponse(asOf=as_of, dataLatency=data_latency, dataQuality=data_quality, items=items)


@router.post("/linker/run")
def run_linker(
    fund_id: uuid.UUID,
    as_of: dt.datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM])),
) -> dict:
    effective_as_of = as_of or _utcnow()
    return run_cross_container_linking(db, fund_id=fund_id, actor_id=actor.actor_id, as_of=effective_as_of)


@router.get("/linker/links")
def get_linker_links(
    fund_id: uuid.UUID,
    entity_id: uuid.UUID,
    as_of: dt.datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> dict:
    effective_as_of = as_of or _utcnow()
    return get_entity_links_snapshot(db, fund_id=fund_id, entity_id=entity_id, as_of=effective_as_of)


@router.get("/linker/obligations/status")
def get_linker_obligation_status(
    fund_id: uuid.UUID,
    as_of: dt.datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> dict:
    effective_as_of = as_of or _utcnow()
    return get_obligation_status_snapshot(db, fund_id=fund_id, as_of=effective_as_of)
