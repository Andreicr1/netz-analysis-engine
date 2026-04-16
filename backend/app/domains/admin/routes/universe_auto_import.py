"""Admin routes for universe auto-import.

Two endpoints, both gated on the platform ``SUPER_ADMIN`` role:

* ``POST /admin/universe/auto-import/run`` — synchronously populate one
  org's ``instruments_org`` from the sanitized catalog. Used for fresh
  tenant provisioning and for replaying a failed run. Response surfaces
  the same :class:`AutoImportMetrics` shape the worker persists to
  ``audit_events`` so the UI can render a single block of telemetry
  regardless of trigger.
* ``GET /admin/universe/auto-import/status`` — aggregates the last
  auto-import per org from ``audit_events`` (action=``auto_import``,
  entity_type=``instruments_org``). Answers "which orgs are covered,
  when was the last run, how big was it?" without paging through audit
  history.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.admin_auth import require_super_admin
from app.core.security.clerk_auth import Actor
from app.core.tenancy.admin_middleware import get_db_admin, get_db_for_tenant
from app.domains.wealth.services.universe_auto_import_service import (
    AUM_FLOOR_USD,
    NAV_COVERAGE_MIN,
    auto_import_for_org,
)

logger: Any = structlog.get_logger()

router = APIRouter(
    prefix="/admin/universe/auto-import",
    tags=["admin-universe-auto-import"],
    dependencies=[Depends(require_super_admin)],
)


# -- Schemas ---------------------------------------------------------------


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org_id: uuid.UUID
    reason: str = Field(
        min_length=3,
        max_length=120,
        description=(
            "Free-form label persisted to audit_events.after_state.reason. "
            "Use short snake_case tags (e.g. 'org_provisioning', "
            "'manual_reimport_after_rejection_reversal')."
        ),
    )


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org_id: uuid.UUID
    evaluated: int
    added: int
    updated: int
    skipped: int
    skipped_by_reason: dict[str, int]
    duration_ms: int
    aum_floor_usd: int
    nav_coverage_min: int


class OrgCoverageRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org_id: uuid.UUID
    last_run_at: datetime | None
    last_added: int
    last_updated: int
    last_skipped: int
    last_duration_ms: int
    total_rows: int


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aum_floor_usd: int
    nav_coverage_min: int
    per_org: list[OrgCoverageRow]


# -- Routes ----------------------------------------------------------------


@router.post("/run", response_model=RunResponse)
async def run_auto_import(
    body: RunRequest,
    request: Request,
    actor: Actor = Depends(require_super_admin),
) -> RunResponse:
    """Trigger auto-import for a single org synchronously.

    Runs on a dedicated tenant-scoped session (RLS bound to ``org_id``)
    so ``instruments_org`` writes use the correct policy. The request
    completes after the commit — callers can show the resulting metrics
    immediately without polling.
    """
    request_id = request.headers.get("X-Request-Id")
    try:
        # get_db_for_tenant wraps the session in session.begin(); the
        # transaction commits automatically when the generator exits.
        async for db in get_db_for_tenant(body.org_id):
            metrics = await auto_import_for_org(
                db,
                body.org_id,
                reason=body.reason,
                actor_id=actor.actor_id,
                actor_roles=[r.value for r in actor.roles],
                request_id=request_id,
            )
            return RunResponse(
                org_id=body.org_id,
                evaluated=metrics["evaluated"],
                added=metrics["added"],
                updated=metrics["updated"],
                skipped=metrics["skipped"],
                skipped_by_reason=metrics["skipped_by_reason"],
                duration_ms=metrics["duration_ms"],
                aum_floor_usd=AUM_FLOOR_USD,
                nav_coverage_min=NAV_COVERAGE_MIN,
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "universe_auto_import.endpoint_failed",
            org_id=str(body.org_id),
            reason=body.reason,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="auto_import_failed",
        ) from exc
    # get_db_for_tenant always yields exactly one session, but the loop
    # form requires an explicit return path for the type checker.
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="no_session_yielded",
    )


@router.get("/status", response_model=StatusResponse)
async def get_status(
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
) -> StatusResponse:
    """Return per-org coverage snapshot derived from audit_events.

    One row per org that has ever been imported (or has any rows in
    ``instruments_org``). ``total_rows`` is the live count today; the
    ``last_*`` columns are the most recent run's metrics.
    """
    result = await db.execute(
        text(
            """
            WITH latest_runs AS (
                SELECT DISTINCT ON (ae.organization_id)
                    ae.organization_id AS org_id,
                    ae.created_at,
                    COALESCE((ae.after_state->>'added')::int, 0)        AS added,
                    COALESCE((ae.after_state->>'updated')::int, 0)      AS updated,
                    COALESCE((ae.after_state->>'skipped')::int, 0)      AS skipped,
                    COALESCE((ae.after_state->>'duration_ms')::int, 0)  AS duration_ms
                FROM audit_events ae
                WHERE ae.action = 'auto_import'
                  AND ae.entity_type = 'instruments_org'
                  AND ae.organization_id IS NOT NULL
                ORDER BY ae.organization_id, ae.created_at DESC
            ),
            totals AS (
                SELECT organization_id AS org_id, COUNT(*) AS total_rows
                FROM instruments_org
                GROUP BY organization_id
            )
            SELECT
                COALESCE(lr.org_id, t.org_id)                    AS org_id,
                lr.created_at                                    AS last_run_at,
                COALESCE(lr.added, 0)                            AS last_added,
                COALESCE(lr.updated, 0)                          AS last_updated,
                COALESCE(lr.skipped, 0)                          AS last_skipped,
                COALESCE(lr.duration_ms, 0)                      AS last_duration_ms,
                COALESCE(t.total_rows, 0)                        AS total_rows
            FROM latest_runs lr
            FULL OUTER JOIN totals t USING (org_id)
            ORDER BY last_run_at DESC NULLS LAST, org_id
            """,
        ),
    )
    per_org = [
        OrgCoverageRow(
            org_id=row.org_id,
            last_run_at=row.last_run_at,
            last_added=row.last_added,
            last_updated=row.last_updated,
            last_skipped=row.last_skipped,
            last_duration_ms=row.last_duration_ms,
            total_rows=row.total_rows,
        )
        for row in result.all()
    ]
    return StatusResponse(
        aum_floor_usd=AUM_FLOOR_USD,
        nav_coverage_min=NAV_COVERAGE_MIN,
        per_org=per_org,
    )
