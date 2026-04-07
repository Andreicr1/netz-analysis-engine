"""Fast-Track Eviction service — automated revocation of degraded fast-tracked funds.

Funds approved via the Quantitative Fast-Track flow bypass qualitative DD. If
their `manager_score` deteriorates below the eviction threshold, they represent
a systemic risk to portfolios consuming the Approved Universe. This service
identifies such funds, revokes their approval, updates the org-link status,
writes audit events and emits monitoring alerts so Portfolio Managers can react.

Designed to be invoked from a daily cron worker — see
`backend/app/domains/wealth/workers/fast_track_eviction.py`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import structlog
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.domains.wealth.enums import UniverseDecision
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.domains.wealth.models.risk import FundRiskMetrics
from app.domains.wealth.models.strategy_drift_alert import StrategyDriftAlert
from app.domains.wealth.models.universe_approval import UniverseApproval

logger = structlog.get_logger(__name__)


# ── Tunables ─────────────────────────────────────────────────────────

#: Funds with manager_score strictly below this value are evicted.
EVICTION_SCORE_THRESHOLD: float = 40.0

#: Substring matched (case-insensitive) against UniverseApproval.rationale to
#: identify fast-tracked approvals. Mirrors the rationale string written by
#: ``POST /screener/fast-track-approval``.
FAST_TRACK_RATIONALE_NEEDLE: str = "Fast-Track"

#: Rationale persisted on the new revoked UniverseApproval row.
EVICTION_RATIONALE: str = (
    "Automated eviction: manager_score dropped below 40.0"
)

#: System actor recorded for audit trail and decided_by columns.
SYSTEM_ACTOR: str = "system:fast_track_eviction"


async def process_fast_track_evictions(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> int:
    """Revoke fast-tracked approvals whose latest manager_score < threshold.

    Steps for the given organization:
      1. Find current ``approved`` UniverseApproval rows whose rationale was
         written by the fast-track flow.
      2. Join the GLOBAL ``fund_risk_metrics`` table (no RLS, no org filter)
         using a lateral lookup of the most recent ``calc_date`` per instrument.
      3. Keep only funds whose ``manager_score`` is strictly below
         :data:`EVICTION_SCORE_THRESHOLD`.
      4. For each, mark the old approval ``is_current = False``, insert a new
         ``revoked`` approval, flip ``InstrumentOrg.approval_status`` to
         ``revoked``, write an audit event and persist a monitoring alert.

    The caller is expected to:
      - have already invoked ``set_rls_context(db, org_id)`` so RLS-scoped
        writes (UniverseApproval, StrategyDriftAlert, audit_events) are
        attributed to the correct tenant;
      - own the SQLAlchemy session lifecycle (commit/rollback).

    Args:
        db: An ``AsyncSession`` already scoped to ``org_id`` via RLS.
        org_id: Target organization UUID.

    Returns:
        The number of fast-tracked instruments that were revoked.
    """
    log = logger.bind(org_id=str(org_id))

    candidates = await _find_fast_track_candidates(db, org_id)
    log.info("fast_track_eviction.scan", scanned=len(candidates))

    if not candidates:
        return 0

    instrument_ids = [c.instrument_id for c in candidates]
    latest_scores = await _latest_manager_scores(db, instrument_ids)

    revoked_count = 0
    revoked_now = dt.datetime.now(dt.UTC)

    for candidate in candidates:
        score = latest_scores.get(candidate.instrument_id)
        if score is None:
            # No score yet (e.g. fund just imported, global_risk_metrics not
            # run). Skip — eviction must be evidence-based.
            continue
        if float(score) >= EVICTION_SCORE_THRESHOLD:
            continue

        try:
            await _revoke_single(
                db,
                org_id=org_id,
                approval=candidate,
                latest_score=float(score),
                revoked_at=revoked_now,
            )
            revoked_count += 1
        except Exception:
            # Per-instrument failure must not abort the org sweep.
            log.exception(
                "fast_track_eviction.instrument_failed",
                instrument_id=str(candidate.instrument_id),
            )

    log.info(
        "fast_track_eviction.done",
        scanned=len(candidates),
        revoked=revoked_count,
        threshold=EVICTION_SCORE_THRESHOLD,
    )
    return revoked_count


# ── Internals ─────────────────────────────────────────────────────────


async def _find_fast_track_candidates(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> list[UniverseApproval]:
    """Return current approved+fast-tracked rows for the org.

    Uses ILIKE on rationale; the fast-track endpoint always writes the literal
    "Auto-approved via Quantitative Fast-Track" string.
    """
    stmt = (
        select(UniverseApproval)
        .where(
            UniverseApproval.organization_id == org_id,
            UniverseApproval.is_current.is_(True),
            UniverseApproval.decision == UniverseDecision.approved.value,
            UniverseApproval.rationale.ilike(f"%{FAST_TRACK_RATIONALE_NEEDLE}%"),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _latest_manager_scores(
    db: AsyncSession,
    instrument_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Decimal]:
    """Fetch the most recent manager_score for each instrument from the GLOBAL table.

    ``fund_risk_metrics`` is a global hypertable (no RLS, no organization_id
    filter). We use a DISTINCT ON pattern to pick the latest ``calc_date`` per
    instrument in a single round-trip.
    """
    if not instrument_ids:
        return {}

    stmt = (
        select(FundRiskMetrics.instrument_id, FundRiskMetrics.manager_score)
        .where(
            FundRiskMetrics.instrument_id.in_(instrument_ids),
            FundRiskMetrics.manager_score.is_not(None),
        )
        .order_by(
            FundRiskMetrics.instrument_id,
            FundRiskMetrics.calc_date.desc(),
        )
        .distinct(FundRiskMetrics.instrument_id)
    )
    result = await db.execute(stmt)
    return {row.instrument_id: row.manager_score for row in result.all()}


async def _revoke_single(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    approval: UniverseApproval,
    latest_score: float,
    revoked_at: dt.datetime,
) -> None:
    """Apply the revocation state machine for one fast-tracked instrument.

    All writes share the caller's transaction; the worker commits per-org.
    """
    instrument_id = approval.instrument_id

    # Resolve fund name for audit/alert payloads (best-effort).
    fund_name = await db.scalar(
        select(Instrument.name).where(Instrument.instrument_id == instrument_id),
    )

    # 1. Mark previous approval as not current.
    approval.is_current = False

    # 2. Insert new revoked approval row (is_current = True).
    revoked_approval = UniverseApproval(
        organization_id=org_id,
        instrument_id=instrument_id,
        analysis_report_id=None,
        decision=UniverseDecision.revoked.value,
        rationale=EVICTION_RATIONALE,
        created_by=SYSTEM_ACTOR,
        decided_by=SYSTEM_ACTOR,
        decided_at=revoked_at,
        is_current=True,
    )
    db.add(revoked_approval)

    # 3. Flip InstrumentOrg approval_status.
    await db.execute(
        update(InstrumentOrg)
        .where(
            and_(
                InstrumentOrg.instrument_id == instrument_id,
                InstrumentOrg.organization_id == org_id,
            ),
        )
        .values(approval_status=UniverseDecision.revoked.value),
    )

    # 4. Audit trail.
    await write_audit_event(
        db,
        actor_id=SYSTEM_ACTOR,
        action="universe.automated_eviction",
        entity_type="UniverseApproval",
        entity_id=str(instrument_id),
        before={
            "decision": UniverseDecision.approved.value,
            "rationale": approval.rationale,
        },
        after={
            "decision": UniverseDecision.revoked.value,
            "rationale": EVICTION_RATIONALE,
            "manager_score": latest_score,
            "threshold": EVICTION_SCORE_THRESHOLD,
            "fund_name": fund_name,
        },
        organization_id=org_id,
    )

    # 5. Monitoring alert for Portfolio Managers.
    alert = StrategyDriftAlert(
        organization_id=org_id,
        instrument_id=instrument_id,
        status="active",
        severity="high",
        anomalous_count=1,
        total_metrics=1,
        metric_details={
            "trigger": "fast_track_eviction",
            "manager_score": latest_score,
            "threshold": EVICTION_SCORE_THRESHOLD,
            "fund_name": fund_name,
            "previous_decision": UniverseDecision.approved.value,
            "new_decision": UniverseDecision.revoked.value,
            "rationale": EVICTION_RATIONALE,
        },
        is_current=True,
        detected_at=revoked_at,
        snapshot_date=revoked_at.date(),
        drift_magnitude=Decimal(str(EVICTION_SCORE_THRESHOLD - latest_score)),
        drift_threshold=Decimal(str(EVICTION_SCORE_THRESHOLD)),
        rebalance_triggered=False,
    )
    db.add(alert)

    logger.info(
        "fast_track_eviction.revoked",
        org_id=str(org_id),
        instrument_id=str(instrument_id),
        fund_name=fund_name,
        manager_score=latest_score,
        threshold=EVICTION_SCORE_THRESHOLD,
    )
