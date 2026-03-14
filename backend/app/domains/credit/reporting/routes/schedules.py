"""Report schedule management routes."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor, require_fund_access, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.reporting.models.schedules import ReportRun, ReportSchedule

router = APIRouter(
    prefix="/funds/{fund_id}/report-schedules",
    tags=["Report Schedules"],
    dependencies=[Depends(require_fund_access())],
)


# -- Schemas -----------------------------------------------------------------

class ScheduleCreate(BaseModel):
    name: str
    report_type: str
    frequency: str
    next_run_date: date | None = None
    config: dict | None = None
    auto_distribute: bool = False
    distribution_list: list[str] | None = None
    notes: str | None = None


class ScheduleUpdate(BaseModel):
    is_active: bool | None = None
    next_run_date: date | None = None
    frequency: str | None = None
    config: dict | None = None
    auto_distribute: bool | None = None
    distribution_list: list[str] | None = None
    notes: str | None = None


# -- CRUD --------------------------------------------------------------------

@router.get("")
async def list_schedules(
    fund_id: uuid.UUID,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE", "AUDITOR"])),
) -> dict[str, Any]:
    stmt = select(ReportSchedule).where(ReportSchedule.fund_id == fund_id)
    if active_only:
        stmt = stmt.where(ReportSchedule.is_active.is_(True))
    result = await db.execute(stmt.order_by(ReportSchedule.next_run_date.asc().nullslast()))
    rows = list(result.scalars().all())
    return {
        "count": len(rows),
        "schedules": [_schedule_to_dict(s) for s in rows],
    }


@router.post("")
async def create_schedule(
    fund_id: uuid.UUID,
    payload: ScheduleCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["ADMIN", "GP"])),
) -> dict[str, Any]:
    schedule = ReportSchedule(
        fund_id=fund_id,
        **payload.model_dump(),
    )
    db.add(schedule)
    await db.flush()

    await write_audit_event(
        db=db, fund_id=fund_id, actor_id=actor.actor_id,
        action="report_schedule.created", entity_type="ReportSchedule",
        entity_id=str(schedule.id), before=None, after=payload.model_dump(mode="json"),
    )

    return _schedule_to_dict(schedule)


@router.patch("/{schedule_id}")
async def update_schedule(
    fund_id: uuid.UUID,
    schedule_id: uuid.UUID,
    payload: ScheduleUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["ADMIN", "GP"])),
) -> dict[str, Any]:
    result = await db.execute(
        select(ReportSchedule).where(
            ReportSchedule.id == schedule_id, ReportSchedule.fund_id == fund_id,
        ),
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    before = {"is_active": schedule.is_active, "frequency": schedule.frequency}
    updates = payload.model_dump(exclude_unset=True)
    for key, val in updates.items():
        setattr(schedule, key, val)
    await db.flush()

    await write_audit_event(
        db=db, fund_id=fund_id, actor_id=actor.actor_id,
        action="report_schedule.updated", entity_type="ReportSchedule",
        entity_id=str(schedule_id), before=before, after=updates,
    )

    return _schedule_to_dict(schedule)


@router.post("/{schedule_id}/trigger")
async def trigger_schedule(
    fund_id: uuid.UUID,
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["ADMIN", "GP"])),
) -> dict[str, Any]:
    """Manually trigger a scheduled report generation."""
    result = await db.execute(
        select(ReportSchedule).where(
            ReportSchedule.id == schedule_id, ReportSchedule.fund_id == fund_id,
        ),
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    now = datetime.now(UTC)
    run = ReportRun(
        fund_id=fund_id,
        schedule_id=schedule_id,
        report_type=schedule.report_type,
        status="RUNNING",
        started_at=now,
    )
    db.add(run)

    schedule.last_run_at = now
    schedule.run_count = (schedule.run_count or 0) + 1
    _advance_next_run(schedule)
    await db.flush()

    await write_audit_event(
        db=db, fund_id=fund_id, actor_id=actor.actor_id,
        action="report_schedule.triggered", entity_type="ReportSchedule",
        entity_id=str(schedule_id), before=None,
        after={"run_id": str(run.id), "report_type": schedule.report_type},
    )

    return {
        "runId": str(run.id),
        "scheduleId": str(schedule_id),
        "reportType": schedule.report_type,
        "status": "RUNNING",
        "nextRunDate": schedule.next_run_date.isoformat() if schedule.next_run_date else None,
    }


@router.get("/{schedule_id}/runs")
async def list_schedule_runs(
    fund_id: uuid.UUID,
    schedule_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE", "AUDITOR"])),
) -> dict[str, Any]:
    result = await db.execute(
        select(ReportRun)
        .where(ReportRun.schedule_id == schedule_id, ReportRun.fund_id == fund_id)
        .order_by(ReportRun.started_at.desc())
        .limit(limit),
    )
    rows = list(result.scalars().all())
    return {
        "count": len(rows),
        "runs": [
            {
                "id": str(r.id),
                "reportType": r.report_type,
                "status": r.status,
                "startedAt": r.started_at.isoformat() if r.started_at else None,
                "completedAt": r.completed_at.isoformat() if r.completed_at else None,
                "outputBlobUri": r.output_blob_uri,
                "errorMessage": r.error_message,
                "distributedTo": r.distributed_to,
                "distributedAt": r.distributed_at.isoformat() if r.distributed_at else None,
            }
            for r in rows
        ],
    }


# -- Helpers -----------------------------------------------------------------

_FREQ_DELTA = {
    "MONTHLY": relativedelta(months=1),
    "QUARTERLY": relativedelta(months=3),
    "SEMI_ANNUAL": relativedelta(months=6),
    "ANNUAL": relativedelta(years=1),
}


def _advance_next_run(schedule: ReportSchedule) -> None:
    """Advance next_run_date based on frequency."""
    delta = _FREQ_DELTA.get(schedule.frequency)
    if delta and schedule.next_run_date:
        schedule.next_run_date = schedule.next_run_date + delta
    elif delta:
        schedule.next_run_date = date.today() + delta


def _schedule_to_dict(s: ReportSchedule) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "reportType": s.report_type,
        "frequency": s.frequency,
        "isActive": s.is_active,
        "nextRunDate": s.next_run_date.isoformat() if s.next_run_date else None,
        "lastRunAt": s.last_run_at.isoformat() if s.last_run_at else None,
        "lastRunStatus": s.last_run_status,
        "autoDistribute": s.auto_distribute,
        "distributionList": s.distribution_list,
        "runCount": s.run_count,
        "config": s.config,
        "notes": s.notes,
        "createdAt": s.created_at.isoformat() if s.created_at else None,
    }
