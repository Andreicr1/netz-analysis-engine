"""Monitoring API routes — DD expiry + rebalance overdue alerts.

Exposes the existing ``alert_engine.scan_alerts()`` as REST.
Sync function is run via ``asyncio.to_thread()`` with a dedicated sync session.
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_org_id
from app.domains.wealth.schemas.portfolio import AlertBatchRead, AlertRead

logger = structlog.get_logger()

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get(
    "/alerts",
    response_model=AlertBatchRead,
    summary="DD expiry + rebalance overdue alerts",
    description=(
        "Scans active portfolios and funds for due diligence report "
        "expirations (>12 months) and rebalance overdue conditions "
        "(>90 days since last rebalance)."
    ),
)
async def get_monitoring_alerts(
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> AlertBatchRead:
    """Return monitoring alerts for the current organization.

    ``scan_alerts()`` is a sync function that uses the ORM ``Session``
    API (db.query), so we run it in a thread with a dedicated sync session
    and RLS context set via ``SET LOCAL``.
    """
    from app.core.db.session import sync_session_factory
    from vertical_engines.wealth.monitoring.alert_engine import scan_alerts

    def _scan() -> AlertBatchRead:
        from sqlalchemy import text

        # org_id is a validated UUID from Clerk auth — safe for interpolation.
        # SET LOCAL does not accept bind parameters in PostgreSQL.
        safe_org = str(org_id).replace("'", "")
        with sync_session_factory() as sync_db, sync_db.begin():
            sync_db.execute(
                text(f"SET LOCAL app.current_organization_id = '{safe_org}'"),
            )
            batch = scan_alerts(sync_db, organization_id=org_id)
            return AlertBatchRead(
                alerts=[
                    AlertRead(
                        alert_type=a.alert_type,
                        severity=a.severity,
                        title=a.title,
                        detail=a.detail,
                        entity_id=a.entity_id,
                        entity_type=a.entity_type,
                    )
                    for a in batch.alerts
                ],
                scanned_at=batch.scanned_at.isoformat(),
                organization_id=str(batch.organization_id),
            )

    return await asyncio.to_thread(_scan)
