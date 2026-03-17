"""Strategy drift API routes — detect and query fund behavior changes.

POST /analytics/strategy-drift/scan            — trigger drift scan (persists alerts)
GET  /analytics/strategy-drift/alerts          — list persisted alerts
GET  /analytics/strategy-drift/{instrument_id} — single instrument drift check
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.risk import FundRiskMetrics
from app.domains.wealth.models.strategy_drift_alert import StrategyDriftAlert
from app.domains.wealth.schemas.strategy_drift import (
    StrategyDriftRead,
    StrategyDriftScanRead,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/analytics/strategy-drift", tags=["strategy-drift"])

DRIFT_SCAN_LOCK_ID = 900_005


def _metrics_row_to_dict(row: FundRiskMetrics) -> dict:
    """Extract scalar attributes from ORM object for thread-safe processing."""
    return {
        "calc_date": row.calc_date,
        "volatility_1y": float(row.volatility_1y) if row.volatility_1y is not None else None,
        "max_drawdown_1y": float(row.max_drawdown_1y) if row.max_drawdown_1y is not None else None,
        "sharpe_1y": float(row.sharpe_1y) if row.sharpe_1y is not None else None,
        "sortino_1y": float(row.sortino_1y) if row.sortino_1y is not None else None,
        "alpha_1y": float(row.alpha_1y) if row.alpha_1y is not None else None,
        "beta_1y": float(row.beta_1y) if row.beta_1y is not None else None,
        "tracking_error_1y": float(row.tracking_error_1y) if row.tracking_error_1y is not None else None,
    }


def _drift_result_to_alert_dict(
    result, org_id: uuid.UUID,
) -> dict:
    """Convert StrategyDriftResult to dict for DB insert."""
    return {
        "organization_id": org_id,
        "instrument_id": uuid.UUID(result.instrument_id),
        "status": result.status,
        "severity": result.severity,
        "anomalous_count": result.anomalous_count,
        "total_metrics": result.total_metrics,
        "metric_details": [
            {
                "metric_name": m.metric_name,
                "recent_mean": m.recent_mean,
                "baseline_mean": m.baseline_mean,
                "baseline_std": m.baseline_std,
                "z_score": m.z_score,
                "is_anomalous": m.is_anomalous,
            }
            for m in result.metrics
        ],
        "is_current": True,
        "detected_at": datetime.now(timezone.utc),
    }


@router.post(
    "/scan",
    response_model=StrategyDriftScanRead,
    summary="Scan all instruments for strategy drift",
    description=(
        "Scans all active instruments in the organization for behavior changes. "
        "Persists results to strategy_drift_alerts (marks previous as is_current=False). "
        "Uses advisory lock to serialize concurrent scans."
    ),
)
async def trigger_drift_scan(
    severity_filter: str | None = Query(None, pattern="^(moderate|severe)$"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> StrategyDriftScanRead:
    # Advisory lock — serialize globally (xact-scoped: auto-releases on commit/rollback)
    lock_result = await db.execute(
        text(f"SELECT pg_try_advisory_xact_lock({DRIFT_SCAN_LOCK_ID})")
    )
    if not lock_result.scalar():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Drift scan already in progress for this organization",
        )

    return await _do_drift_scan(db, org_id, severity_filter, limit)


async def _do_drift_scan(
    db: AsyncSession,
    org_id: uuid.UUID,
    severity_filter: str | None,
    limit: int,
) -> StrategyDriftScanRead:
    # 1. Load all active instruments
    inst_stmt = select(Instrument.instrument_id, Instrument.name).where(
        Instrument.is_active == True,  # noqa: E712
    )
    inst_result = await db.execute(inst_stmt)
    instruments = inst_result.all()

    if not instruments:
        return StrategyDriftScanRead(
            scanned_count=0,
            alerts=[],
            stable_count=0,
            insufficient_data_count=0,
            scan_timestamp=datetime.now(timezone.utc),
        )

    instrument_ids = [row.instrument_id for row in instruments]
    instrument_names = {str(row.instrument_id): row.name for row in instruments}

    # 2. Batch-load FundRiskMetrics (single IN query, not N+1)
    metrics_stmt = (
        select(FundRiskMetrics)
        .where(FundRiskMetrics.instrument_id.in_(instrument_ids))
        .order_by(FundRiskMetrics.instrument_id, FundRiskMetrics.calc_date.asc())
    )
    metrics_result = await db.execute(metrics_stmt)
    all_metrics = metrics_result.scalars().all()

    # Group by instrument_id → list of dicts
    metrics_by_instrument: dict[str, list[dict]] = {}
    for row in all_metrics:
        key = str(row.instrument_id)
        metrics_by_instrument.setdefault(key, []).append(_metrics_row_to_dict(row))

    # Include instruments with no metrics (they'll get insufficient_data)
    for inst_id in instrument_ids:
        key = str(inst_id)
        if key not in metrics_by_instrument:
            metrics_by_instrument[key] = []

    # 3. Run scan in thread
    from vertical_engines.wealth.monitoring.strategy_drift_scanner import scan_all_strategy_drift

    scan_result = await asyncio.to_thread(
        scan_all_strategy_drift,
        metrics_by_instrument,
        instrument_names,
    )

    # 4. Persist results — mark previous alerts as not current, insert new
    scanned_ids = [uuid.UUID(iid) for iid in metrics_by_instrument]
    if scanned_ids:
        await db.execute(
            update(StrategyDriftAlert)
            .where(
                StrategyDriftAlert.instrument_id.in_(scanned_ids),
                StrategyDriftAlert.is_current == True,  # noqa: E712
            )
            .values(is_current=False)
        )

    # Insert new alerts for all scanned instruments (not just drift_detected)
    if scan_result.all_results:
        alert_dicts = [_drift_result_to_alert_dict(r, org_id) for r in scan_result.all_results]
        for alert_dict in alert_dicts:
            stmt = pg_insert(StrategyDriftAlert).values(**alert_dict)
            # On conflict (partial unique index), update existing current
            stmt = stmt.on_conflict_do_update(
                index_elements=["organization_id", "instrument_id"],
                set_={
                    "status": stmt.excluded.status,
                    "severity": stmt.excluded.severity,
                    "anomalous_count": stmt.excluded.anomalous_count,
                    "total_metrics": stmt.excluded.total_metrics,
                    "metric_details": stmt.excluded.metric_details,
                    "detected_at": stmt.excluded.detected_at,
                    "updated_at": stmt.excluded.updated_at,
                },
                where=StrategyDriftAlert.is_current == True,  # noqa: E712
            )
            await db.execute(stmt)

        await db.commit()

    # 5. Build response (filter by severity if requested)
    alerts = [
        StrategyDriftRead(
            instrument_id=uuid.UUID(a.instrument_id),
            instrument_name=a.instrument_name,
            status=a.status,
            anomalous_count=a.anomalous_count,
            total_metrics=a.total_metrics,
            metrics=[
                {
                    "metric_name": m.metric_name,
                    "recent_mean": m.recent_mean,
                    "baseline_mean": m.baseline_mean,
                    "baseline_std": m.baseline_std,
                    "z_score": m.z_score,
                    "is_anomalous": m.is_anomalous,
                }
                for m in a.metrics
            ],
            severity=a.severity,
            detected_at=a.detected_at,
        )
        for a in scan_result.alerts
        if severity_filter is None or a.severity == severity_filter
    ][:limit]

    return StrategyDriftScanRead(
        scanned_count=scan_result.scanned_count,
        alerts=alerts,
        stable_count=scan_result.stable_count,
        insufficient_data_count=scan_result.insufficient_data_count,
        scan_timestamp=scan_result.scan_timestamp,
    )


@router.get(
    "/alerts",
    response_model=list[StrategyDriftRead],
    summary="List persisted drift alerts",
)
async def list_drift_alerts(
    is_current: bool = Query(True),
    severity: str | None = Query(None, pattern="^(none|moderate|severe)$"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[StrategyDriftRead]:
    stmt = select(StrategyDriftAlert).where(
        StrategyDriftAlert.is_current == is_current,
    )
    if severity:
        stmt = stmt.where(StrategyDriftAlert.severity == severity)

    stmt = stmt.order_by(StrategyDriftAlert.detected_at.desc()).limit(limit)

    result = await db.execute(stmt)
    alerts = result.scalars().all()

    # Need instrument names — lazy="raise" means we query separately
    inst_ids = [a.instrument_id for a in alerts]
    if inst_ids:
        inst_result = await db.execute(
            select(Instrument.instrument_id, Instrument.name).where(
                Instrument.instrument_id.in_(inst_ids)
            )
        )
        name_map = {row.instrument_id: row.name for row in inst_result.all()}
    else:
        name_map = {}

    return [
        StrategyDriftRead(
            instrument_id=a.instrument_id,
            instrument_name=name_map.get(a.instrument_id, str(a.instrument_id)),
            status=a.status,
            anomalous_count=a.anomalous_count,
            total_metrics=a.total_metrics,
            metrics=a.metric_details,
            severity=a.severity,
            detected_at=a.detected_at,
        )
        for a in alerts
    ]


# ── Parameterized route MUST come after literal routes (/alerts, /scan) ──
# FastAPI matches top-to-bottom; /{instrument_id} would capture "alerts" as UUID.


@router.get(
    "/{instrument_id}",
    response_model=StrategyDriftRead,
    summary="Check drift for a single instrument",
)
async def get_instrument_drift(
    instrument_id: uuid.UUID,
    recent_days: int = Query(90, ge=5, le=365),
    baseline_days: int = Query(360, ge=20, le=1800),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> StrategyDriftRead:
    # Verify instrument exists
    inst_result = await db.execute(
        select(Instrument.name).where(Instrument.instrument_id == instrument_id)
    )
    inst_name = inst_result.scalar()
    if inst_name is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instrument not found")

    # Load metrics history
    stmt = (
        select(FundRiskMetrics)
        .where(FundRiskMetrics.instrument_id == instrument_id)
        .order_by(FundRiskMetrics.calc_date.asc())
        .limit(baseline_days)
    )
    result = await db.execute(stmt)
    metrics_rows = result.scalars().all()

    # Extract to plain dicts for thread-safe processing
    metrics_dicts = [_metrics_row_to_dict(r) for r in metrics_rows]

    from vertical_engines.wealth.monitoring.strategy_drift_scanner import scan_strategy_drift

    drift_result = await asyncio.to_thread(
        scan_strategy_drift,
        metrics_dicts,
        str(instrument_id),
        inst_name,
        {"recent_window_days": recent_days, "baseline_window_days": baseline_days},
    )

    return StrategyDriftRead(
        instrument_id=instrument_id,
        instrument_name=drift_result.instrument_name,
        status=drift_result.status,
        anomalous_count=drift_result.anomalous_count,
        total_metrics=drift_result.total_metrics,
        metrics=[
            {
                "metric_name": m.metric_name,
                "recent_mean": m.recent_mean,
                "baseline_mean": m.baseline_mean,
                "baseline_std": m.baseline_std,
                "z_score": m.z_score,
                "is_anomalous": m.is_anomalous,
            }
            for m in drift_result.metrics
        ],
        severity=drift_result.severity,
        detected_at=drift_result.detected_at,
    )
