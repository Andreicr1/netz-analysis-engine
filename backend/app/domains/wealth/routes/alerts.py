"""Unified Alerts Inbox routes — Phase 7 of the
portfolio-enterprise-workbench plan.

Two endpoints:

  GET  /alerts/inbox                          — aggregated inbox
  POST /alerts/{source}/{alert_id}/acknowledge — mark a single alert read

The aggregator reads from BOTH alert sources currently in production
(``strategy_drift_alerts`` populated by the drift_check worker, and
``portfolio_alerts`` scaffolded in migration 0103) and emits a single
time-ordered stream of ``UnifiedAlertRead`` rows.

Per CLAUDE.md:
  - async-first, AsyncSession from get_db_with_rls (RLS enforced)
  - Pydantic schemas via response_model + model_validate
  - lazy="raise" on relationships → all needed names are explicit
    SELECTs, no implicit lazy loads

Per Phase 7 user mandate:
  - Frontend never branches on the source — only the UnifiedAlert shape
  - Read/unread state lives on the source tables (acknowledged_at)
  - DL15: zero localStorage; the inbox state IS this DB write
  - No complex resolution workflows: acknowledge is the only mutation
"""
from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import (
    Actor,
    CurrentUser,
    get_actor,
    get_current_user,
)
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.model_portfolio import (
    ModelPortfolio,
    PortfolioAlert,
)
from app.domains.wealth.models.strategy_drift_alert import StrategyDriftAlert
from app.domains.wealth.schemas.alerts import (
    PortfolioAlertCountRead,
    UnifiedAlertAcknowledgeRequest,
    UnifiedAlertInboxResponse,
    UnifiedAlertRead,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Severity normalization ────────────────────────────────────────


_DRIFT_SEVERITY_MAP: dict[str, str] = {
    "severe": "critical",
    "moderate": "warning",
    "none": "info",
}


def _normalize_drift_severity(raw: str) -> str:
    """Drift severities are ``none|moderate|severe`` — normalize to
    the unified ``info|warning|critical`` scale used by the inbox."""
    return _DRIFT_SEVERITY_MAP.get(raw, "info")


def _normalize_portfolio_severity(raw: str) -> str:
    """Portfolio_alerts already uses ``info|warning|critical`` per
    migration 0103. Pass through with a defensive fallback."""
    if raw in {"info", "warning", "critical"}:
        return raw
    return "info"


# ── Title + subtitle synthesis ─────────────────────────────────────


def _drift_title(alert: StrategyDriftAlert, instrument_name: str | None) -> str:
    label = instrument_name or "Instrument"
    if alert.severity == "severe":
        return f"Drift detected: {label}"
    if alert.severity == "moderate":
        return f"Drift warning: {label}"
    return f"Drift signal: {label}"


def _drift_subtitle(alert: StrategyDriftAlert) -> str:
    return f"{alert.anomalous_count} of {alert.total_metrics} metrics anomalous"


# ── Mappers ────────────────────────────────────────────────────────


def _drift_to_unified(
    alert: StrategyDriftAlert,
    instrument_name: str | None,
) -> UnifiedAlertRead:
    """Project a StrategyDriftAlert ORM row onto UnifiedAlertRead.

    Subject is the underlying instrument. The drill-through href
    points to the Builder's universe sub-pill so the PM can review
    the instrument inside the workspace context. Discovery deep
    linking lands when the instrument_id ↔ external_id bridge
    arrives in a follow-up sprint.
    """
    return UnifiedAlertRead(
        id=alert.id,
        source="drift",
        alert_type="drift",
        severity=_normalize_drift_severity(alert.severity),
        title=_drift_title(alert, instrument_name),
        subtitle=_drift_subtitle(alert),
        subject_kind="instrument",
        subject_id=alert.instrument_id,
        subject_name=instrument_name,
        created_at=alert.detected_at,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
        href=f"/portfolio?tab=universe&instrument={alert.instrument_id}",
    )


def _portfolio_to_unified(
    alert: PortfolioAlert,
    portfolio_name: str | None,
) -> UnifiedAlertRead:
    """Project a PortfolioAlert ORM row onto UnifiedAlertRead.

    Subject is the model_portfolio. The drill-through href points to
    the Phase 6 Analytics surface with the portfolio pre-selected so
    the PM lands directly on the relevant analytics group.
    """
    return UnifiedAlertRead(
        id=alert.id,
        source="portfolio",
        alert_type=alert.alert_type,
        severity=_normalize_portfolio_severity(alert.severity),
        title=alert.title,
        subtitle=portfolio_name,
        subject_kind="portfolio",
        subject_id=alert.portfolio_id,
        subject_name=portfolio_name,
        created_at=alert.created_at,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
        href=f"/portfolio/analytics?subject={alert.portfolio_id}",
    )


# ── GET /alerts/inbox ─────────────────────────────────────────────


@router.get(
    "/inbox",
    response_model=UnifiedAlertInboxResponse,
    summary="Aggregated alerts inbox (Phase 7 unification)",
)
async def get_alerts_inbox(
    limit: int = Query(100, ge=1, le=500),
    unread_only: bool = Query(False),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> UnifiedAlertInboxResponse:
    """Return a unified time-ordered alerts feed across both sources.

    The frontend GlobalAlertInbox renders this verbatim — no client-
    side joins, no source branching. Sorted by ``created_at DESC``
    so the most recent alerts surface first.

    Filters:
      - ``limit``        — cap the number of rows returned (default 100)
      - ``unread_only``  — when true, hides rows where
                           ``acknowledged_at IS NOT NULL``

    Both filters are applied in SQL where possible. The two SELECTs
    run sequentially because the ORM models live on different tables;
    a UNION ALL would also work but the per-row mapping needs the
    instrument/portfolio name JOIN which is cleaner as two queries.
    """
    # ── Source 1: drift alerts (instrument-keyed) ──
    drift_stmt = (
        select(
            StrategyDriftAlert,
            Instrument.name.label("instrument_name"),
        )
        .outerjoin(
            Instrument,
            Instrument.instrument_id == StrategyDriftAlert.instrument_id,
        )
        .where(StrategyDriftAlert.is_current.is_(True))
        .order_by(StrategyDriftAlert.detected_at.desc())
        .limit(limit)
    )
    if unread_only:
        drift_stmt = drift_stmt.where(StrategyDriftAlert.acknowledged_at.is_(None))

    drift_rows = (await db.execute(drift_stmt)).all()
    drift_items = [
        _drift_to_unified(row.StrategyDriftAlert, row.instrument_name)
        for row in drift_rows
    ]

    # ── Source 2: portfolio alerts (portfolio-keyed) ──
    portfolio_stmt = (
        select(
            PortfolioAlert,
            ModelPortfolio.display_name.label("portfolio_name"),
        )
        .outerjoin(
            ModelPortfolio,
            ModelPortfolio.id == PortfolioAlert.portfolio_id,
        )
        .where(PortfolioAlert.dismissed_at.is_(None))
        .order_by(PortfolioAlert.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        portfolio_stmt = portfolio_stmt.where(
            PortfolioAlert.acknowledged_at.is_(None),
        )

    portfolio_rows = (await db.execute(portfolio_stmt)).all()
    portfolio_items = [
        _portfolio_to_unified(row.PortfolioAlert, row.portfolio_name)
        for row in portfolio_rows
    ]

    # ── Merge + sort + cap ──
    combined = drift_items + portfolio_items
    combined.sort(key=lambda a: a.created_at, reverse=True)
    capped = combined[:limit]

    # ── Counts (over the entire combined slice, not just the cap) ──
    unread_count = sum(1 for a in combined if a.acknowledged_at is None)
    by_source: dict[str, int] = {
        "drift": len(drift_items),
        "portfolio": len(portfolio_items),
    }

    return UnifiedAlertInboxResponse(
        items=capped,
        total=len(combined),
        unread_count=unread_count,
        by_source=by_source,
    )


# ── POST /alerts/{source}/{alert_id}/acknowledge ──────────────────


@router.post(
    "/{source}/{alert_id}/acknowledge",
    response_model=UnifiedAlertRead,
    summary="Mark a unified alert as read (DL15 — server-persisted)",
)
async def acknowledge_alert(
    source: str,
    alert_id: uuid.UUID,
    body: UnifiedAlertAcknowledgeRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> UnifiedAlertRead:
    """Persist read state on the appropriate source table.

    Phase 7 contract:
      - Single canonical mutation per alert (acknowledge)
      - Read state lives on the source row's ``acknowledged_at`` +
        ``acknowledged_by`` columns — no separate alert_reads table
      - Idempotent: re-acknowledging an already-read alert is a no-op
        with the same response (the GlobalAlertInbox can replay this
        without server-side dedupe)

    Per DL15: zero localStorage involvement. The frontend's read state
    is purely a re-fetch of /alerts/inbox after the POST returns.
    """
    now = datetime.utcnow()
    actor_id = actor.actor_id
    # ``body`` is currently empty per the schema; the parameter is
    # reserved so a future expansion (acknowledge reason, dismiss flag)
    # can extend the contract without a path change.
    del body

    if source == "drift":
        result = await db.execute(
            select(
                StrategyDriftAlert,
                Instrument.name.label("instrument_name"),
            )
            .outerjoin(
                Instrument,
                Instrument.instrument_id == StrategyDriftAlert.instrument_id,
            )
            .where(StrategyDriftAlert.id == alert_id),
        )
        row = result.first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"drift alert {alert_id} not found",
            )
        drift_alert = row.StrategyDriftAlert
        if drift_alert.acknowledged_at is None:
            drift_alert.acknowledged_at = now
            drift_alert.acknowledged_by = actor_id
            await db.flush()
            await db.refresh(drift_alert)
        return _drift_to_unified(drift_alert, row.instrument_name)

    if source == "portfolio":
        result = await db.execute(
            select(
                PortfolioAlert,
                ModelPortfolio.display_name.label("portfolio_name"),
            )
            .outerjoin(
                ModelPortfolio,
                ModelPortfolio.id == PortfolioAlert.portfolio_id,
            )
            .where(PortfolioAlert.id == alert_id),
        )
        row = result.first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"portfolio alert {alert_id} not found",
            )
        portfolio_alert = row.PortfolioAlert
        if portfolio_alert.acknowledged_at is None:
            portfolio_alert.acknowledged_at = now
            portfolio_alert.acknowledged_by = actor_id
            await db.flush()
            await db.refresh(portfolio_alert)
        return _portfolio_to_unified(portfolio_alert, row.portfolio_name)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unknown alert source: {source!r}. Expected 'drift' or 'portfolio'.",
    )


# ── GET /alerts/portfolio/{portfolio_id}/count ─────────────────────


@router.get(
    "/portfolio/{portfolio_id}/count",
    response_model=PortfolioAlertCountRead,
    summary="Open-alert count for a single live portfolio (Phase 5 sub-nav badge)",
)
async def get_portfolio_alert_count(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> PortfolioAlertCountRead:
    """Return the open-alert count for a single portfolio.

    Used by the Phase 5 PortfolioSubNav 'Live' pill badge to surface
    the per-portfolio count without paginating through the full inbox.
    Counts only ``portfolio_alerts`` rows where
    ``dismissed_at IS NULL AND acknowledged_at IS NULL`` — drift
    alerts are instrument-keyed and not portfolio-attributable
    without a holdings join (deferred to a follow-up sprint).
    """
    result = await db.execute(
        select(func.count(PortfolioAlert.id))
        .where(PortfolioAlert.portfolio_id == portfolio_id)
        .where(PortfolioAlert.dismissed_at.is_(None))
        .where(PortfolioAlert.acknowledged_at.is_(None)),
    )
    count = result.scalar_one() or 0
    return PortfolioAlertCountRead(
        portfolio_id=portfolio_id,
        open_count=int(count),
    )
