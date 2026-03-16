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
    """Fire-and-forget audit write using a separate session."""
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


@router.get("/funds/{fund_id}/investor/report-packs")
async def list_published_packs(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_INVESTOR_ROLES)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(MonthlyReportPack).where(
            MonthlyReportPack.fund_id == fund_id,
            MonthlyReportPack.status == ReportPackStatus.PUBLISHED,
        ).order_by(MonthlyReportPack.created_at.desc()).limit(limit).offset(offset),
    )
    packs = list(result.scalars().all())

    asyncio.ensure_future(
        _fire_audit(fund_id, actor.actor_id, "investor.report_pack.viewed", "MonthlyReportPack", {"count": len(packs)}),
    )

    return [
        {
            "id": str(p.id),
            "fund_id": str(p.fund_id),
            "status": p.status.value if hasattr(p.status, "value") else str(p.status),
            "period_month": p.period_month if hasattr(p, "period_month") else None,
            "published_at": p.published_at.isoformat() if hasattr(p, "published_at") and p.published_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in packs
    ]


@router.get("/funds/{fund_id}/investor/statements")
async def list_published_statements(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_INVESTOR_ROLES)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    result = await db.execute(
        select(InvestorStatement).where(
            InvestorStatement.fund_id == fund_id,
        ).order_by(InvestorStatement.created_at.desc()).limit(limit).offset(offset),
    )
    rows = list(result.scalars().all())

    asyncio.ensure_future(
        _fire_audit(fund_id, actor.actor_id, "investor.statement.viewed", "InvestorStatement", {"count": len(rows)}),
    )

    return {
        "items": [
            {
                "id": str(r.id),
                "period_month": r.period_month,
                "blob_path": r.blob_path,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/funds/{fund_id}/investor/documents")
async def list_approved_documents(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_INVESTOR_ROLES)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List documents approved for distribution (status in approved/published)."""
    result = await db.execute(
        select(Document).where(
            Document.fund_id == fund_id,
            Document.status.in_(["approved", "published"]),
        ).order_by(Document.created_at.desc()).limit(limit).offset(offset),
    )
    rows = list(result.scalars().all())

    asyncio.ensure_future(
        _fire_audit(fund_id, actor.actor_id, "investor.document.viewed", "Document", {"count": len(rows)}),
    )

    return {
        "items": [
            {
                "id": str(r.id),
                "title": r.title,
                "document_type": r.document_type,
                "status": r.status,
                "content_type": r.content_type,
                "original_filename": r.original_filename,
                "blob_uri": r.blob_uri,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
