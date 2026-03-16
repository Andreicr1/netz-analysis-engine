from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor, require_fund_access, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.documents.models.evidence import EvidenceDocument
from app.domains.credit.reporting.enums import ReportPackStatus, ReportSectionType
from app.domains.credit.reporting.models.report_packs import MonthlyReportPack
from app.domains.credit.reporting.models.report_sections import ReportPackSection
from app.domains.credit.reporting.schemas.report_packs import ReportPackCreate, ReportPackOut
from app.domains.credit.reporting.services.generators import (
    generate_nav_summary,
    generate_open_actions,
    generate_overdue_obligations,
    generate_portfolio_exposure,
)

router = APIRouter(tags=["Reporting Packs"], dependencies=[Depends(require_fund_access())])


@router.post("/funds/{fund_id}/report-packs", response_model=ReportPackOut, status_code=status.HTTP_201_CREATED)
async def create_pack(
    fund_id: uuid.UUID,
    payload: ReportPackCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["ADMIN", "COMPLIANCE", "INVESTMENT_TEAM"])),
) -> ReportPackOut:
    pack = MonthlyReportPack(
        fund_id=fund_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        status=ReportPackStatus.DRAFT,
        created_at=datetime.now(UTC),
    )
    db.add(pack)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="report_pack.created",
        entity_type="MonthlyReportPack",
        entity_id=str(pack.id),
        before=None,
        after={"period_start": str(payload.period_start), "period_end": str(payload.period_end)},
    )

    return ReportPackOut.model_validate(pack)


@router.post("/funds/{fund_id}/report-packs/{pack_id}/generate", response_model=ReportPackOut)
async def generate_pack(
    fund_id: uuid.UUID,
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["ADMIN", "COMPLIANCE", "INVESTMENT_TEAM"])),
) -> ReportPackOut:
    result = await db.execute(
        select(MonthlyReportPack).where(MonthlyReportPack.fund_id == fund_id, MonthlyReportPack.id == pack_id),
    )
    pack = result.scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail="Not found")

    if pack.status != ReportPackStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Pack must be DRAFT to generate")

    # Generate immutable snapshots.
    # Sequential by design: each generator is a single COUNT/SUM query.
    sections = [
        (ReportSectionType.NAV_SUMMARY, await generate_nav_summary(db, fund_id)),
        (ReportSectionType.PORTFOLIO_EXPOSURE, await generate_portfolio_exposure(db, fund_id)),
        (ReportSectionType.OBLIGATIONS, await generate_overdue_obligations(db, fund_id)),
        (ReportSectionType.ACTIONS, await generate_open_actions(db, fund_id)),
    ]

    for section_type, snapshot in sections:
        db.add(
            ReportPackSection(
                report_pack_id=pack.id,
                section_type=section_type,
                snapshot=snapshot,
                created_at=datetime.now(UTC),
            ),
        )

    pack.status = ReportPackStatus.GENERATED
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="report_pack.generated",
        entity_type="MonthlyReportPack",
        entity_id=str(pack.id),
        before=None,
        after={"status": pack.status.value},
    )

    return ReportPackOut.model_validate(pack)


@router.post("/funds/{fund_id}/report-packs/{pack_id}/publish", response_model=ReportPackOut)
async def publish_pack(
    fund_id: uuid.UUID,
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["ADMIN", "COMPLIANCE", "INVESTMENT_TEAM"])),
) -> ReportPackOut:
    result = await db.execute(
        select(MonthlyReportPack).where(MonthlyReportPack.fund_id == fund_id, MonthlyReportPack.id == pack_id),
    )
    pack = result.scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail="Not found")

    if pack.status != ReportPackStatus.GENERATED:
        raise HTTPException(status_code=400, detail="Pack must be GENERATED to publish")

    pack.status = ReportPackStatus.PUBLISHED
    pack.published_at = datetime.now(UTC)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="report_pack.published",
        entity_type="MonthlyReportPack",
        entity_id=str(pack.id),
        before=None,
        after={"status": pack.status.value},
    )

    # Evidence placeholder for published output
    filename = f"Monthly_Report_{pack.period_end.year:04d}_{pack.period_end.month:02d}.pdf"
    evidence = EvidenceDocument(
        fund_id=fund_id,
        deal_id=None,
        action_id=None,
        report_pack_id=pack.id,
        filename=filename,
        blob_uri=None,
        uploaded_at=None,
    )
    db.add(evidence)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="report_pack.evidence_registered",
        entity_type="EvidenceDocument",
        entity_id=str(evidence.id),
        before=None,
        after={"filename": filename, "report_pack_id": str(pack.id)},
    )

    return ReportPackOut.model_validate(pack)


@router.post("/funds/{fund_id}/report-packs/{pack_id}/unpublish", response_model=ReportPackOut)
async def unpublish_pack(
    fund_id: uuid.UUID,
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["ADMIN", "COMPLIANCE", "INVESTMENT_TEAM"])),
) -> ReportPackOut:
    """Unpublish a report pack: published → generated. Removes from investor portal."""
    result = await db.execute(
        select(MonthlyReportPack).where(MonthlyReportPack.fund_id == fund_id, MonthlyReportPack.id == pack_id),
    )
    pack = result.scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail="Not found")

    if pack.status != ReportPackStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Pack must be PUBLISHED to unpublish")

    pack.status = ReportPackStatus.GENERATED
    pack.published_at = None
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="report_pack.unpublished",
        entity_type="MonthlyReportPack",
        entity_id=str(pack.id),
        before=None,
        after={"status": pack.status.value},
    )

    return ReportPackOut.model_validate(pack)
