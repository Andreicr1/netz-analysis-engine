"""Investor portal routes — external-facing endpoints for LPs and advisors.

All routes use response_model= and model_validate(). No inline dict serialization.
Investor-facing schemas intentionally exclude internal storage paths (blob_path, blob_uri).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor, require_fund_access, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.modules.documents.models import Document
from app.domains.credit.reporting.enums import ReportPackStatus
from app.domains.credit.reporting.models.investor_statements import InvestorStatement
from app.domains.credit.reporting.models.report_packs import MonthlyReportPack
from app.domains.credit.reporting.schemas.investor_portal import (
    InvestorDocumentItem,
    InvestorReportPackItem,
    InvestorStatementItem,
)
from app.shared.enums import Role

logger = logging.getLogger(__name__)

_INVESTOR_ROLES = (Role.INVESTOR, Role.ADVISOR, Role.ADMIN)

router = APIRouter(tags=["Investor Portal"], dependencies=[Depends(require_fund_access())])


async def _fire_audit(
    fund_id: uuid.UUID,
    actor_id: str,
    action: str,
    entity_type: str,
    after: dict[str, Any],
) -> None:
    """Background audit write using a separate session."""
    from app.core.db.engine import async_session_factory

    try:
        async with async_session_factory() as audit_db:
            await write_audit_event(
                audit_db,
                fund_id=fund_id,
                actor_id=actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=str(fund_id),
                before=None,
                after=after,
            )
            await audit_db.commit()
    except Exception:
        logger.warning("Background audit write failed for %s", action, exc_info=True)


@router.get(
    "/funds/{fund_id}/investor/report-packs",
    response_model=list[InvestorReportPackItem],
)
async def list_published_packs(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_INVESTOR_ROLES)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[InvestorReportPackItem]:
    result = await db.execute(
        select(MonthlyReportPack).where(
            MonthlyReportPack.fund_id == fund_id,
            MonthlyReportPack.status == ReportPackStatus.PUBLISHED,
        ).order_by(MonthlyReportPack.created_at.desc()).limit(limit).offset(offset),
    )
    packs = list(result.scalars().all())

    asyncio.create_task(
        _fire_audit(fund_id, actor.actor_id, "investor.report_pack.viewed", "MonthlyReportPack", {"count": len(packs)}),
    )

    return [
        InvestorReportPackItem(
            id=p.id,
            fund_id=p.fund_id,
            status=p.status.value if hasattr(p.status, "value") else str(p.status),
            period_month=getattr(p, "period_month", None),
            published_at=p.published_at,
            created_at=p.created_at,
        )
        for p in packs
    ]


@router.get(
    "/funds/{fund_id}/investor/statements",
    response_model=dict[str, list[InvestorStatementItem]],
)
async def list_published_statements(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_INVESTOR_ROLES)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, list[InvestorStatementItem]]:
    result = await db.execute(
        select(InvestorStatement).where(
            InvestorStatement.fund_id == fund_id,
        ).order_by(InvestorStatement.created_at.desc()).limit(limit).offset(offset),
    )
    rows = list(result.scalars().all())

    asyncio.create_task(
        _fire_audit(fund_id, actor.actor_id, "investor.statement.viewed", "InvestorStatement", {"count": len(rows)}),
    )

    return {
        "items": [
            InvestorStatementItem.model_validate(r)
            for r in rows
        ],
    }


@router.get(
    "/funds/{fund_id}/investor/documents",
    response_model=dict[str, list[InvestorDocumentItem]],
)
async def list_approved_documents(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_INVESTOR_ROLES)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, list[InvestorDocumentItem]]:
    """List documents approved for distribution (status in approved/published)."""
    result = await db.execute(
        select(Document).where(
            Document.fund_id == fund_id,
            Document.status.in_(["approved", "published"]),
        ).order_by(Document.created_at.desc()).limit(limit).offset(offset),
    )
    rows = list(result.scalars().all())

    asyncio.create_task(
        _fire_audit(fund_id, actor.actor_id, "investor.document.viewed", "Document", {"count": len(rows)}),
    )

    return {
        "items": [
            InvestorDocumentItem.model_validate(r)
            for r in rows
        ],
    }
