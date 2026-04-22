"""Macro intelligence API routes — regional scores, snapshot, regime, committee.

Phase 1: GET /scores, GET /snapshot
Phase 2: GET /regime, GET /reviews, POST /reviews/generate,
         PATCH /reviews/{id}/approve, PATCH /reviews/{id}/reject
Phase 3A: GET /bis, GET /imf, GET /treasury, GET /ofr — raw hypertable data
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import route_cache
from app.core.config.config_service import ConfigService
from app.core.db.engine import async_session_factory
from app.core.security.clerk_auth import CurrentUser, get_current_user, require_role
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.allocation import MacroRegimeSnapshot, StrategicAllocation
from app.domains.wealth.models.macro_committee import MacroReview
from app.domains.wealth.routes.common import _get_content_semaphore, require_content_slot
from app.domains.wealth.schemas.allocation import GlobalRegimeRead
from app.domains.wealth.schemas.macro import (
    BisDataResponse,
    BisTimePoint,
    CbCalendarResponse,
    CbEvent,
    CrossAssetPoint,
    CrossAssetResponse,
    DataFreshnessRead,
    DimensionScoreRead,
    FredDataResponse,
    FredTimePoint,
    GlobalIndicatorsRead,
    ImfDataResponse,
    ImfYearPoint,
    MacroReviewApprove,
    MacroReviewRead,
    MacroReviewReject,
    MacroScoresResponse,
    MacroSnapshotResponse,
    OfrDataResponse,
    OfrTimePoint,
    RegimeTrailPoint,
    RegimeTrailResponse,
    RegionalRegimeResponse,
    RegionalRegimeRow,
    RegionalScoreRead,
    TreasuryDataResponse,
    TreasuryTimePoint,
)
from app.shared.enums import Role
from app.shared.models import (
    BisStatistics,
    ImfWeoForecast,
    MacroData,
    MacroRegionalSnapshot,
    OfrHedgeFundData,
    TreasuryData,
)
from quant_engine.allocation_proposal_service import (
    compute_regime_tilted_weights,
    extract_regime_from_review,
    extract_regional_scores_from_snapshot,
)
from vertical_engines.wealth.macro_committee_engine import (
    build_report_json,
    generate_weekly_report,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/macro")

_REGION_DISPLAY_NAMES: dict[str, str] = {
    "US": "United States",
    "EUROPE": "Europe",
    "ASIA": "Asia",
    "EM": "Emerging Markets",
}


def _build_analysis_text(
    region_key: str,
    composite_score: float,
    dimensions: dict[str, DimensionScoreRead],
) -> str:
    """Build a short analytical summary from region scores and dimensions."""
    name = _REGION_DISPLAY_NAMES.get(region_key, region_key)
    if composite_score >= 70:
        tone = "strong"
    elif composite_score >= 55:
        tone = "moderately positive"
    elif composite_score >= 40:
        tone = "mixed"
    else:
        tone = "weak"

    parts = [
        f"The {name} macro environment is currently {tone} with a composite score of {composite_score:.0f}/100.",
    ]

    strong = [d for d, v in dimensions.items() if v.score >= 65]
    weak = [d for d, v in dimensions.items() if v.score < 40]

    if strong:
        labels = ", ".join(d.replace("_", " ") for d in strong)
        parts.append(f"Strength areas: {labels}.")
    if weak:
        labels = ", ".join(d.replace("_", " ") for d in weak)
        parts.append(f"Areas of concern: {labels}.")

    return " ".join(parts)


@router.get(
    "/scores",
    response_model=MacroScoresResponse,
    summary="Latest regional macro scores + global indicators",
    tags=["macro"],
)
async def get_macro_scores(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> MacroScoresResponse:
    """Return the most recent regional macro scores and global indicators.
    
    Refactored to use mv_macro_regional_summary for performance.
    """
    from sqlalchemy import text
    
    # 1. Get regional summary from view
    stmt = text("SELECT * FROM mv_macro_regional_summary")
    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No macro snapshot available. Run macro ingestion worker first.",
        )

    as_of_date = rows[0].as_of_date
    regions: dict[str, RegionalScoreRead] = {}
    
    for r in rows:
        region_key = r.region_key
        dimensions = {
            dim: DimensionScoreRead(**dim_data)
            for dim, dim_data in r.dimensions.items()
        }
        freshness = {
            sid: DataFreshnessRead(**f_data)
            for sid, f_data in r.data_freshness.items()
        }
        analysis_text = _build_analysis_text(
            region_key, float(r.composite_score), dimensions,
        )
        regions[region_key] = RegionalScoreRead(
            composite_score=float(r.composite_score),
            coverage=float(r.coverage),
            dimensions=dimensions,
            data_freshness=freshness,
            analysis_text=analysis_text,
        )

    # 2. Get global indicators from the main snapshot (global indicators are not yet flattened)
    # Falling back to the latest snapshot for global indicators specifically
    stmt_gi = select(MacroRegionalSnapshot).order_by(MacroRegionalSnapshot.as_of_date.desc()).limit(1)
    res_gi = await db.execute(stmt_gi)
    full_snapshot = res_gi.scalar_one_or_none()
    
    gi_data = full_snapshot.data_json.get("global_indicators", {}) if full_snapshot else {}
    global_indicators = GlobalIndicatorsRead(
        geopolitical_risk_score=gi_data.get("geopolitical_risk_score", 50.0),
        energy_stress=gi_data.get("energy_stress", 50.0),
        commodity_stress=gi_data.get("commodity_stress", 50.0),
        usd_strength=gi_data.get("usd_strength", 50.0),
    )

    return MacroScoresResponse(
        as_of_date=as_of_date,
        regions=regions,
        global_indicators=global_indicators,
    )


@router.get(
    "/snapshot",
    response_model=MacroSnapshotResponse,
    summary="Latest full macro snapshot (raw JSONB)",
    tags=["macro"],
)
@route_cache(ttl=300, key_prefix="macro:snapshot")
async def get_macro_snapshot(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> MacroSnapshotResponse:
    """Return the latest raw macro regional snapshot.

    The data_json field contains the full snapshot including per-indicator
    percentile scores, staleness metadata, and dimension breakdowns.
    """
    stmt = (
        select(MacroRegionalSnapshot)
        .order_by(MacroRegionalSnapshot.as_of_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No macro snapshot available. Run macro ingestion worker first.",
        )

    return MacroSnapshotResponse.model_validate(snapshot)


# ---------------------------------------------------------------------------
#  Phase 2: Regime Hierarchy + Committee Workflow
# ---------------------------------------------------------------------------


@router.get(
    "/regime",
    response_model=GlobalRegimeRead,
    summary="Current global market regime (multi-signal)",
    tags=["macro"],
)
async def get_regime(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> GlobalRegimeRead:
    """Return the latest global regime from macro_regime_snapshot.

    Uses the 10-signal multi-factor stress model (55% financial + 45% real economy).
    Computed daily by the regime_detection worker.
    """
    stmt = (
        select(MacroRegimeSnapshot)
        .order_by(MacroRegimeSnapshot.as_of_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No regime snapshot available. The regime_detection worker may not have run yet.",
        )

    return GlobalRegimeRead(
        as_of_date=snapshot.as_of_date,
        raw_regime=snapshot.raw_regime,
        stress_score=snapshot.stress_score,
        signal_details=snapshot.signal_details,
        signal_breakdown=snapshot.signal_breakdown or [],
    )


@router.get(
    "/reviews",
    response_model=list[MacroReviewRead],
    summary="List macro committee reviews",
    tags=["macro"],
)
async def list_reviews(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: Literal["pending", "approved", "rejected"] | None = Query(
        default=None, alias="status",
    ),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[MacroReviewRead]:
    """List macro committee reviews for the current organization."""
    stmt = (
        select(MacroReview)
        .order_by(MacroReview.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(MacroReview.status == status_filter)
    result = await db.execute(stmt)
    reviews = result.scalars().all()
    return [MacroReviewRead.model_validate(r) for r in reviews]


@router.post(
    "/reviews/generate",
    response_model=MacroReviewRead,
    status_code=status.HTTP_201_CREATED,
    summary="Generate macro committee report",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.INVESTMENT_TEAM))],
)
async def generate_review(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: UUID | None = Depends(get_org_id),
) -> MacroReviewRead:
    """Generate a new macro committee review from current + previous snapshots."""
    # Backpressure: reject if too many concurrent content tasks
    await require_content_slot()

    try:
        # Get current and previous snapshots
        stmt = (
            select(MacroRegionalSnapshot)
            .order_by(MacroRegionalSnapshot.as_of_date.desc())
            .limit(2)
        )
        result = await db.execute(stmt)
        snapshots = result.scalars().all()

        if not snapshots:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No macro snapshot available. Run macro ingestion worker first.",
            )

        current = snapshots[0]
        previous = snapshots[1] if len(snapshots) > 1 else None

        report = generate_weekly_report(
            current.data_json,
            previous.data_json if previous else None,
        )

        # Embed latest regime snapshot in report for downstream use
        regime_data: dict[str, Any] | None = None
        try:
            regime_stmt = (
                select(MacroRegimeSnapshot)
                .order_by(MacroRegimeSnapshot.as_of_date.desc())
                .limit(1)
            )
            regime_result = await db.execute(regime_stmt)
            regime_snapshot = regime_result.scalar_one_or_none()
            if regime_snapshot:
                regime_data = {
                    "global": regime_snapshot.raw_regime,
                    "stress_score": float(regime_snapshot.stress_score) if regime_snapshot.stress_score else None,
                    "signal_details": regime_snapshot.signal_details,
                }
        except Exception:
            logger.warning("regime_embed_failed", exc_info=True)

        review = MacroReview(
            organization_id=org_id,
            status="pending",
            is_emergency=False,
            as_of_date=current.as_of_date,
            snapshot_id=current.id,
            report_json=build_report_json(report, regime_data=regime_data),
            created_by=user.actor_id,
        )
        db.add(review)
        await db.flush()

        return MacroReviewRead.model_validate(review)
    finally:
        _get_content_semaphore().release()


@router.patch(
    "/reviews/{review_id}/approve",
    response_model=MacroReviewRead,
    summary="CIO approval of macro review",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.DIRECTOR, Role.ADMIN))],
)
async def approve_review(
    review_id: UUID,
    body: MacroReviewApprove,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: UUID | None = Depends(get_org_id),
) -> MacroReviewRead:
    """Approve a pending macro review.

    Side-effect: generates allocation proposals for all profiles and
    upserts them as pending StrategicAllocation records (G1.1 + G1.2).
    """
    stmt = (
        select(MacroReview)
        .where(MacroReview.id == review_id)
        .with_for_update()
    )
    result = await db.execute(stmt)
    review = result.scalar_one_or_none()

    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found.",
        )
    if review.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Review is already {review.status}.",
        )

    review.status = "approved"
    review.approved_by = user.name
    review.approved_at = datetime.now(UTC)
    review.decision_rationale = body.decision_rationale

    # ── G1.1 + G1.2: Generate allocation proposals from regime ──
    await _generate_allocation_proposals(db, review, user.name, org_id)

    await db.flush()
    return MacroReviewRead.model_validate(review)


async def _generate_allocation_proposals(
    db: AsyncSession,
    review: MacroReview,
    actor_id: str,
    org_id: UUID | None,
) -> None:
    """Generate regime-tilted allocation proposals for all profiles.

    Called as a side-effect of macro review approval. Reads profile
    configs via ConfigService, computes tilted weights, and upserts
    StrategicAllocation records with actor_source='macro_proposal'.
    """
    config_service = ConfigService(db)
    raw_config = await config_service.get("liquid_funds", "portfolio_profiles", org_id)
    profiles_config = raw_config.value if raw_config else {}
    profiles_dict: dict = profiles_config.get("profiles", profiles_config)

    # Extract regime + regional scores from the approved review
    report_json = review.report_json or {}
    global_regime = extract_regime_from_review(report_json)

    # If regime data wasn't embedded in report, read from snapshot
    if global_regime == "RISK_ON" and not report_json.get("regime"):
        regime_stmt = (
            select(MacroRegimeSnapshot)
            .order_by(MacroRegimeSnapshot.as_of_date.desc())
            .limit(1)
        )
        regime_result = await db.execute(regime_stmt)
        regime_snapshot = regime_result.scalar_one_or_none()
        if regime_snapshot:
            global_regime = regime_snapshot.raw_regime

    # Get snapshot data for regional scores
    regional_scores: dict[str, float] = {}
    if review.snapshot_id:
        snap_stmt = select(MacroRegionalSnapshot).where(
            MacroRegionalSnapshot.id == review.snapshot_id,
        )
        snap_result = await db.execute(snap_stmt)
        snapshot = snap_result.scalar_one_or_none()
        if snapshot:
            regional_scores = extract_regional_scores_from_snapshot(
                snapshot.data_json,
            )

    today = date.today()

    for profile_name, profile_data in profiles_dict.items():
        strategic_config = profile_data.get("strategic_allocation", {})
        if not strategic_config:
            continue

        proposal = compute_regime_tilted_weights(
            profile_name=profile_name,
            strategic_config=strategic_config,
            global_regime=global_regime,
            regional_scores=regional_scores,
        )

        # Expire current allocations with actor_source='macro_proposal'
        expire_stmt = select(StrategicAllocation).where(
            StrategicAllocation.profile == profile_name,
            StrategicAllocation.actor_source == "macro_proposal",
            StrategicAllocation.effective_from <= today,
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= today),
        )
        expire_result = await db.execute(expire_stmt)
        for old_row in expire_result.scalars().all():
            old_row.effective_to = today

        # Insert new proposed allocations
        for bp in proposal.proposals:
            from decimal import Decimal as D

            # PR-A26.2 — the legacy SA ``min_weight/max_weight`` columns
            # were dropped in migration 0155; the macro proposal's bounds
            # land on ``drift_min/drift_max`` (realize-mode BlockConstraint
            # now reads those).
            row = StrategicAllocation(
                organization_id=org_id,
                profile=profile_name,
                block_id=bp.block_id,
                target_weight=D(str(bp.proposed_weight)),
                drift_min=D(str(bp.min_weight)),
                drift_max=D(str(bp.max_weight)),
                rationale=proposal.rationale,
                approved_by=actor_id,
                effective_from=today,
                actor_source="macro_proposal",
            )
            db.add(row)

    logger.info(
        "allocation_proposals_generated",
        review_id=str(review.id),
        regime=global_regime,
        profiles=list(profiles_dict.keys()),
    )


@router.patch(
    "/reviews/{review_id}/reject",
    response_model=MacroReviewRead,
    summary="CIO rejection of macro review",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.DIRECTOR, Role.ADMIN))],
)
async def reject_review(
    review_id: UUID,
    body: MacroReviewReject,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> MacroReviewRead:
    """Reject a pending macro review with rationale."""
    stmt = (
        select(MacroReview)
        .where(MacroReview.id == review_id)
        .with_for_update()
    )
    result = await db.execute(stmt)
    review = result.scalar_one_or_none()

    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found.",
        )
    if review.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Review is already {review.status}.",
        )

    review.status = "rejected"
    review.approved_by = user.name  # Record who rejected for audit trail
    review.decision_rationale = body.decision_rationale

    await db.flush()
    return MacroReviewRead.model_validate(review)


# ── Download ────────────────────────────────────────────────────────


@router.get(
    "/reviews/{review_id}/download",
    summary="Download macro committee review as PDF",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.INVESTMENT_TEAM))],
)
async def download_macro_review_pdf(
    review_id: UUID,
    language: str = Query(default="pt", description="pt or en"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Render macro review as PDF on-demand via Playwright."""
    result = await db.execute(
        select(MacroReview).where(MacroReview.id == review_id),
    )
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found.",
        )
    if review.status not in ("pending", "approved"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Review must be pending or approved (current: {review.status}).",
        )

    from vertical_engines.wealth.pdf.macro_pdf import generate_macro_review_pdf

    pdf_bytes = await generate_macro_review_pdf(
        review.report_json,
        as_of_date=review.as_of_date,
        language=language,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="macro-review-{review.as_of_date}.pdf"'
            ),
        },
    )


# ---------------------------------------------------------------------------
#  Phase 3A: Raw Hypertable Data Panels
#  Global tables (no RLS), Redis-cached, INVESTMENT_TEAM auth.
# ---------------------------------------------------------------------------

_DEFAULT_LOOKBACK_DAYS = 730  # 2 years


async def _get_cached(cache_key: str) -> list | None:
    """Check Redis for cached raw data result."""
    try:
        import redis.asyncio as aioredis

        from app.core.jobs.tracker import get_redis_pool

        r = aioredis.Redis(connection_pool=get_redis_pool())
        try:
            cached = await r.get(f"macro_raw:{cache_key}")
            if cached:
                return json.loads(cached)
        finally:
            await r.aclose()
    except Exception:
        logger.debug("macro_raw_cache_miss", cache_key=cache_key)
    return None


async def _set_cached(cache_key: str, data: list, ttl: int) -> None:
    """Cache raw data result in Redis."""
    try:
        import redis.asyncio as aioredis

        from app.core.jobs.tracker import get_redis_pool

        r = aioredis.Redis(connection_pool=get_redis_pool())
        try:
            await r.set(
                f"macro_raw:{cache_key}",
                json.dumps(data, default=str),
                ex=ttl,
            )
        finally:
            await r.aclose()
    except Exception:
        logger.debug("macro_raw_cache_set_failed", cache_key=cache_key)


@router.get(
    "/bis",
    response_model=BisDataResponse,
    summary="Raw BIS time series",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.INVESTMENT_TEAM))],
)
async def get_bis_data(
    country: str = Query(..., description="ISO country code, e.g. US, DE, GB"),
    indicator: str = Query(..., description="BIS indicator, e.g. CREDIT_GAP"),
    user: CurrentUser = Depends(get_current_user),
) -> BisDataResponse:
    """Return raw BIS time series for a country/indicator pair.

    Cached in Redis for 6 hours. 2-year lookback by default.
    """
    # Map frontend UPPER_CASE IDs to DB lowercase values
    _BIS_MAP: dict[str, str] = {
        "CREDIT_GAP": "credit_to_gdp_gap",
        "DSR": "debt_service_ratio",
        "PROPERTY_PRICES": "property_prices",
    }
    db_indicator = _BIS_MAP.get(indicator, indicator)

    cache_key = f"bis:{country}:{indicator}"
    cached = await _get_cached(cache_key)
    if cached is not None:
        return BisDataResponse(country=country, indicator=indicator, data=cached)

    cutoff = datetime.now(UTC) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    stmt = (
        select(BisStatistics.period, BisStatistics.value)
        .where(
            BisStatistics.country_code == country,
            BisStatistics.indicator == db_indicator,
            BisStatistics.period >= cutoff,
        )
        .order_by(BisStatistics.period)
    )

    async with async_session_factory() as db:
        result = await db.execute(stmt)

    rows = result.all()
    points = [
        BisTimePoint(period=r.period.date() if hasattr(r.period, "date") else r.period, value=float(r.value))
        for r in rows
    ]

    await _set_cached(cache_key, [p.model_dump(mode="json") for p in points], ttl=21600)
    return BisDataResponse(country=country, indicator=indicator, data=points)


@router.get(
    "/imf",
    response_model=ImfDataResponse,
    summary="Raw IMF WEO forecasts",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.INVESTMENT_TEAM))],
)
async def get_imf_data(
    country: str = Query(..., description="ISO country code, e.g. US, DE, BR"),
    indicator: str = Query(..., description="IMF indicator, e.g. NGDP_RPCH"),
    user: CurrentUser = Depends(get_current_user),
) -> ImfDataResponse:
    """Return raw IMF WEO annual forecasts for a country/indicator pair.

    Provenance: model_inference (NOT deterministic).
    Cached in Redis for 6 hours. 2-year lookback by default.
    """
    cache_key = f"imf:{country}:{indicator}"
    cached = await _get_cached(cache_key)
    if cached is not None:
        return ImfDataResponse(country=country, indicator=indicator, data=cached)

    cutoff = datetime.now(UTC) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    stmt = (
        select(ImfWeoForecast.year, ImfWeoForecast.value)
        .where(
            ImfWeoForecast.country_code == country,
            ImfWeoForecast.indicator == indicator,
            ImfWeoForecast.period >= cutoff,
        )
        .order_by(ImfWeoForecast.year)
    )

    async with async_session_factory() as db:
        result = await db.execute(stmt)

    rows = result.all()
    points = [
        ImfYearPoint(year=r.year, value=float(r.value))
        for r in rows
        if r.value is not None
    ]

    await _set_cached(cache_key, [p.model_dump(mode="json") for p in points], ttl=21600)
    return ImfDataResponse(country=country, indicator=indicator, data=points)


@router.get(
    "/treasury",
    response_model=TreasuryDataResponse,
    summary="Raw US Treasury data",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.INVESTMENT_TEAM))],
)
async def get_treasury_data(
    series: str = Query(..., description="Treasury series ID, e.g. 10Y_RATE"),
    user: CurrentUser = Depends(get_current_user),
) -> TreasuryDataResponse:
    """Return raw Treasury/FRED time series for a given series ID.

    Market interest rates (10Y, 2Y, Fed Funds, yield curve) come from
    macro_data (FRED). Debt statistics come from treasury_data.
    Cached in Redis for 1 hour. 2-year lookback by default.
    """
    # Map frontend-friendly IDs to FRED series in macro_data
    _FRED_MAP: dict[str, str] = {
        "10Y_RATE": "DGS10",
        "2Y_RATE": "DGS2",
        "30Y_RATE": "DGS30",
        "FED_FUNDS": "DFF",
        "YIELD_CURVE": "YIELD_CURVE_10Y2Y",  # derived: DGS10 - DGS2
        "SOFR": "SOFR",
    }

    cache_key = f"treasury:{series}"
    cached = await _get_cached(cache_key)
    if cached is not None:
        return TreasuryDataResponse(series=series, data=cached)

    cutoff = date.today() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    fred_id = _FRED_MAP.get(series)

    if fred_id:
        # Interest rates from macro_data (FRED)
        stmt = (
            select(MacroData.obs_date, MacroData.value)
            .where(MacroData.series_id == fred_id, MacroData.obs_date >= cutoff)
            .order_by(MacroData.obs_date)
        )
    else:
        # Debt statistics from treasury_data
        stmt = (
            select(TreasuryData.obs_date, TreasuryData.value)
            .where(TreasuryData.series_id == series, TreasuryData.obs_date >= cutoff)
            .order_by(TreasuryData.obs_date)
        )

    async with async_session_factory() as db:
        result = await db.execute(stmt)

    rows = result.all()
    points = [
        TreasuryTimePoint(obs_date=r.obs_date, value=float(r.value))
        for r in rows
        if r.value is not None
    ]

    await _set_cached(cache_key, [p.model_dump(mode="json") for p in points], ttl=3600)
    return TreasuryDataResponse(series=series, data=points)


@router.get(
    "/ofr",
    response_model=OfrDataResponse,
    summary="Raw OFR hedge fund data",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.INVESTMENT_TEAM))],
)
async def get_ofr_data(
    metric: str = Query(..., description="OFR metric/series ID, e.g. HF_LEVERAGE"),
    user: CurrentUser = Depends(get_current_user),
) -> OfrDataResponse:
    """Return raw OFR hedge fund time series for a given metric.

    Cached in Redis for 1 hour. 2-year lookback by default.
    """
    # Map frontend-friendly IDs to actual OFR series_id values
    _OFR_MAP: dict[str, str] = {
        "HF_AUM": "OFR_INDUSTRY_NAV",
        "HF_LEVERAGE": "OFR_LEVERAGE_P50",
        "HF_REPO_STRESS": "OFR_REPO_VOLUME",
    }
    db_metric = _OFR_MAP.get(metric, metric)

    cache_key = f"ofr:{metric}"
    cached = await _get_cached(cache_key)
    if cached is not None:
        return OfrDataResponse(metric=metric, data=cached)

    cutoff = date.today() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    stmt = (
        select(OfrHedgeFundData.obs_date, OfrHedgeFundData.value)
        .where(
            OfrHedgeFundData.series_id == db_metric,
            OfrHedgeFundData.obs_date >= cutoff,
        )
        .order_by(OfrHedgeFundData.obs_date)
    )

    async with async_session_factory() as db:
        result = await db.execute(stmt)

    rows = result.all()
    points = [
        OfrTimePoint(obs_date=r.obs_date, value=float(r.value))
        for r in rows
        if r.value is not None
    ]

    await _set_cached(cache_key, [p.model_dump(mode="json") for p in points], ttl=3600)
    return OfrDataResponse(metric=metric, data=points)


# ── Allowlist of FRED series exposed to frontend ──────────────────────
# Prevents arbitrary macro_data queries. Add series_ids as needed.
_FRED_ALLOWLIST: set[str] = {
    # US Macro
    "VIXCLS", "CPIAUCSL", "CPI_YOY", "UNRATE", "PAYEMS",
    "A191RL1Q225SBEA", "INDPRO", "UMCSENT", "JTSJOL", "SAHMREALTIME",
    # Interest rates & spreads
    "DGS10", "DGS2", "DGS30", "DFF", "SOFR", "YIELD_CURVE_10Y2Y",
    "BAA10Y", "BAMLH0A0HYM2", "MORTGAGE30US", "MORTGAGE15US",
    # Financial conditions
    "NFCI",
    # Commodities & energy
    "DCOILWTICO", "DCOILBRENTEU", "DHHNGSP", "GOLDAMGBD228NLBM", "PCOPPUSDM",
    # Housing
    "CSUSHPINSA", "HOUST", "PERMIT", "MSPUS",
    # Europe
    "CP0000EZ19M086NEST", "ECBDFR", "IRLTLT01DEM156N", "BAMLHE00EHYIEY",
    # Asia
    "JPNCPIALLMINMEI", "CHNCPIALLMINMEI", "IRLTLT01JPM156N",
    # EM
    "BRACPIALLMINMEI", "INDCPIALLMINMEI", "INTDSRBRM193N", "BAMLEMCBPIOAS",
    # Global
    "GPRH", "USEPUINDXD", "DTWEXBGS",
    # Regime signal sparklines
    "CFNAI", "ICSA", "TOTBKCR",
}

_FRED_ALLOWLIST.update({"DEXUSEU", "DEXJPUS", "DEXBZUS", "IRLTLT01DEM156N"})


# ---------------------------------------------------------------------------
#  Cross-asset batch endpoint
# ---------------------------------------------------------------------------

_CROSS_ASSET_CATALOG: list[dict[str, str]] = [
    {"symbol": "DGS2", "name": "US 2Y", "sector": "RATES", "unit": "%", "source": "fred"},
    {"symbol": "DGS10", "name": "US 10Y", "sector": "RATES", "unit": "%", "source": "fred"},
    {"symbol": "DGS30", "name": "US 30Y", "sector": "RATES", "unit": "%", "source": "fred"},
    {
        "symbol": "IRLTLT01DEM156N",
        "name": "DE 10Y",
        "sector": "RATES",
        "unit": "%",
        "source": "fred",
    },
    {"symbol": "DTWEXBGS", "name": "DXY", "sector": "FX", "unit": "idx", "source": "fred"},
    {"symbol": "DEXUSEU", "name": "EUR/USD", "sector": "FX", "unit": "", "source": "fred"},
    {"symbol": "DEXJPUS", "name": "USD/JPY", "sector": "FX", "unit": "", "source": "fred"},
    {"symbol": "DEXBZUS", "name": "USD/BRL", "sector": "FX", "unit": "", "source": "fred"},
    {"symbol": "SPY", "name": "SPX", "sector": "EQUITY", "unit": "idx", "source": "nav"},
    {"symbol": "QQQ", "name": "NDX", "sector": "EQUITY", "unit": "idx", "source": "nav"},
    {"symbol": "IWM", "name": "RUT", "sector": "EQUITY", "unit": "idx", "source": "nav"},
    {"symbol": "EEM", "name": "EM", "sector": "EQUITY", "unit": "idx", "source": "nav"},
    {
        "symbol": "DCOILWTICO",
        "name": "WTI",
        "sector": "COMMODITY",
        "unit": "USD",
        "source": "fred",
    },
    {
        "symbol": "GOLDAMGBD228NLBM",
        "name": "Gold",
        "sector": "COMMODITY",
        "unit": "USD",
        "source": "fred",
    },
    {
        "symbol": "PCOPPUSDM",
        "name": "Copper",
        "sector": "COMMODITY",
        "unit": "USD",
        "source": "fred",
    },
    {
        "symbol": "DHHNGSP",
        "name": "NatGas",
        "sector": "COMMODITY",
        "unit": "USD",
        "source": "fred",
    },
    {"symbol": "BAA10Y", "name": "IG Spread", "sector": "CREDIT", "unit": "%", "source": "fred"},
    {
        "symbol": "BAMLH0A0HYM2",
        "name": "HY Spread",
        "sector": "CREDIT",
        "unit": "%",
        "source": "fred",
    },
    {
        "symbol": "BAMLEMCBPIOAS",
        "name": "EM Spread",
        "sector": "CREDIT",
        "unit": "bps",
        "source": "fred",
    },
    {
        "symbol": "BAMLHE00EHYIEY",
        "name": "EU HY",
        "sector": "CREDIT",
        "unit": "%",
        "source": "fred",
    },
]

_CROSS_ASSET_LOOKBACK = 60
_CROSS_ASSET_SPARKLINE_N = 30


async def _fetch_fred_series_batch(
    series_ids: list[str],
    cutoff: date,
) -> dict[str, list[tuple[date, float]]]:
    """Fetch multiple FRED series in one DB query."""
    stmt = (
        select(MacroData.series_id, MacroData.obs_date, MacroData.value)
        .where(MacroData.series_id.in_(series_ids), MacroData.obs_date >= cutoff)
        .order_by(MacroData.series_id, MacroData.obs_date)
    )
    async with async_session_factory() as db:
        result = await db.execute(stmt)

    out: dict[str, list[tuple[date, float]]] = {}
    for row in result.all():
        if row.value is not None:
            out.setdefault(row.series_id, []).append((row.obs_date, float(row.value)))
    return out


async def _fetch_equity_nav_batch(
    tickers: list[str],
    cutoff: date,
) -> dict[str, list[tuple[date, float]]]:
    """Fetch nav_timeseries for equity proxy tickers."""
    from app.domains.wealth.models.instrument import Instrument
    from app.domains.wealth.models.nav import NavTimeseries

    stmt = (
        select(Instrument.ticker, NavTimeseries.nav_date, NavTimeseries.nav)
        .join(NavTimeseries, NavTimeseries.instrument_id == Instrument.instrument_id)
        .where(Instrument.ticker.in_(tickers), NavTimeseries.nav_date >= cutoff)
        .order_by(Instrument.ticker, NavTimeseries.nav_date)
    )
    async with async_session_factory() as db:
        result = await db.execute(stmt)

    out: dict[str, list[tuple[date, float]]] = {}
    for row in result.all():
        if row.nav is not None and row.ticker is not None:
            out.setdefault(row.ticker, []).append((row.nav_date, float(row.nav)))
    return out


def _compute_cross_asset_point(
    item: dict[str, str],
    series_data: list[tuple[date, float]],
) -> CrossAssetPoint:
    """Convert raw time series into a terminal cross-asset row."""
    if not series_data:
        return CrossAssetPoint(
            symbol=item["symbol"],
            name=item["name"],
            sector=item["sector"],  # type: ignore[arg-type]
            unit=item["unit"],
        )

    values = [v for _, v in series_data]
    last_value = values[-1]
    prev_value = values[-2] if len(values) >= 2 else None
    change_pct = None
    if prev_value is not None and prev_value != 0:
        change_pct = (last_value - prev_value) / abs(prev_value) * 100

    return CrossAssetPoint(
        symbol=item["symbol"],
        name=item["name"],
        sector=item["sector"],  # type: ignore[arg-type]
        unit=item["unit"],
        last_value=last_value,
        change_pct=change_pct,
        sparkline=values[-_CROSS_ASSET_SPARKLINE_N:],
    )


@router.get(
    "/cross-asset",
    response_model=CrossAssetResponse,
    summary="Cross-asset panel data",
    tags=["macro"],
)
@route_cache(ttl=300, key_prefix="macro:cross_asset")
async def get_cross_asset(
    user: CurrentUser = Depends(get_current_user),
) -> CrossAssetResponse:
    """Batch cross-asset data for the macro terminal left panel."""
    cutoff = date.today() - timedelta(days=_CROSS_ASSET_LOOKBACK)
    fred_symbols = [i["symbol"] for i in _CROSS_ASSET_CATALOG if i["source"] == "fred"]
    nav_symbols = [i["symbol"] for i in _CROSS_ASSET_CATALOG if i["source"] == "nav"]

    fred_data, nav_data = await asyncio.gather(
        _fetch_fred_series_batch(fred_symbols, cutoff),
        _fetch_equity_nav_batch(nav_symbols, cutoff),
    )
    combined = {**fred_data, **nav_data}
    assets = [
        _compute_cross_asset_point(item, combined.get(item["symbol"], []))
        for item in _CROSS_ASSET_CATALOG
    ]
    as_of = max((d for pts in combined.values() for d, _ in pts), default=None)

    return CrossAssetResponse(as_of_date=as_of, assets=assets)


# ---------------------------------------------------------------------------
#  Regime trail — 18-month history for SVG polyline
# ---------------------------------------------------------------------------

_TRAIL_MONTHS = 18


def _score_to_gi(score: float | None) -> float:
    """Map percentile score 0-100 to growth/inflation coordinate [-1, +1]."""
    if score is None:
        return 0.0
    return (float(score) / 100.0) * 2.0 - 1.0


@router.get(
    "/regime/trail",
    response_model=RegimeTrailResponse,
    summary="18-month regime trail coordinates",
    tags=["macro"],
)
@route_cache(ttl=3600, key_prefix="macro:regime_trail")
async def get_regime_trail(
    region: str = Query(default="US", description="Region key, e.g. US, EUROPE, ASIA, EM"),
    user: CurrentUser = Depends(get_current_user),
) -> RegimeTrailResponse:
    """Return 18 months of growth/inflation coordinates from regional snapshots."""
    cutoff = date.today() - timedelta(days=_TRAIL_MONTHS * 31)
    stmt = (
        select(MacroRegionalSnapshot.as_of_date, MacroRegionalSnapshot.data_json)
        .where(MacroRegionalSnapshot.as_of_date >= cutoff)
        .order_by(MacroRegionalSnapshot.as_of_date)
    )
    async with async_session_factory() as db:
        result = await db.execute(stmt)

    points: list[RegimeTrailPoint] = []
    for row in result.all():
        snapshot_data = row.data_json if isinstance(row.data_json, dict) else {}
        regions_data = snapshot_data.get("regions", {})
        region_data = regions_data.get(region, {})
        dimensions = region_data.get("dimensions", {})
        growth_score = dimensions.get("growth", {}).get("score")
        inflation_score = dimensions.get("inflation", {}).get("score")
        if growth_score is None and inflation_score is None:
            continue
        points.append(
            RegimeTrailPoint(
                as_of_date=row.as_of_date,
                g=_score_to_gi(growth_score),
                i=_score_to_gi(inflation_score),
                stress=region_data.get("stress_score"),
            ),
        )

    return RegimeTrailResponse(points=points, region=region)


# ---------------------------------------------------------------------------
#  CB Calendar — static seed fixture, updated by operator quarterly
# ---------------------------------------------------------------------------

_CB_CALENDAR_SEED: list[dict[str, str | float | int]] = [
    {"central_bank": "Fed", "meeting_date": "2026-05-07", "current_rate_pct": 4.50, "expected_change_bps": 0},
    {"central_bank": "Fed", "meeting_date": "2026-06-18", "current_rate_pct": 4.50, "expected_change_bps": -25},
    {"central_bank": "Fed", "meeting_date": "2026-07-30", "current_rate_pct": 4.25, "expected_change_bps": 0},
    {"central_bank": "Fed", "meeting_date": "2026-09-17", "current_rate_pct": 4.25, "expected_change_bps": -25},
    {"central_bank": "Fed", "meeting_date": "2026-11-05", "current_rate_pct": 4.00, "expected_change_bps": 0},
    {"central_bank": "Fed", "meeting_date": "2026-12-17", "current_rate_pct": 4.00, "expected_change_bps": -25},
    {"central_bank": "ECB", "meeting_date": "2026-04-30", "current_rate_pct": 2.50, "expected_change_bps": 0},
    {"central_bank": "ECB", "meeting_date": "2026-06-11", "current_rate_pct": 2.50, "expected_change_bps": -25},
    {"central_bank": "ECB", "meeting_date": "2026-07-23", "current_rate_pct": 2.25, "expected_change_bps": 0},
    {"central_bank": "ECB", "meeting_date": "2026-09-10", "current_rate_pct": 2.25, "expected_change_bps": -25},
    {"central_bank": "BoJ", "meeting_date": "2026-04-28", "current_rate_pct": 0.50, "expected_change_bps": 0},
    {"central_bank": "BoJ", "meeting_date": "2026-06-17", "current_rate_pct": 0.50, "expected_change_bps": 25},
    {"central_bank": "BoJ", "meeting_date": "2026-07-30", "current_rate_pct": 0.75, "expected_change_bps": 0},
    {"central_bank": "BoE", "meeting_date": "2026-05-08", "current_rate_pct": 4.50, "expected_change_bps": -25},
    {"central_bank": "BoE", "meeting_date": "2026-06-19", "current_rate_pct": 4.25, "expected_change_bps": 0},
    {"central_bank": "BoE", "meeting_date": "2026-08-06", "current_rate_pct": 4.25, "expected_change_bps": -25},
    {"central_bank": "BCB", "meeting_date": "2026-05-07", "current_rate_pct": 13.75, "expected_change_bps": 0},
    {"central_bank": "BCB", "meeting_date": "2026-06-18", "current_rate_pct": 13.75, "expected_change_bps": -50},
    {"central_bank": "Banxico", "meeting_date": "2026-05-14", "current_rate_pct": 9.00, "expected_change_bps": -25},
    {"central_bank": "Banxico", "meeting_date": "2026-06-25", "current_rate_pct": 8.75, "expected_change_bps": 0},
]


@router.get(
    "/cb-calendar",
    response_model=CbCalendarResponse,
    summary="Upcoming central bank meeting calendar",
    tags=["macro"],
)
async def get_cb_calendar(
    n: int = Query(default=8, ge=1, le=24, description="Number of upcoming events"),
    user: CurrentUser = Depends(get_current_user),
) -> CbCalendarResponse:
    """Return upcoming central bank meetings from the seed calendar."""
    today = date.today()
    upcoming = [
        CbEvent(
            central_bank=str(e["central_bank"]),
            meeting_date=date.fromisoformat(str(e["meeting_date"])),
            current_rate_pct=float(e["current_rate_pct"]),
            expected_change_bps=int(e["expected_change_bps"]),
        )
        for e in _CB_CALENDAR_SEED
        if date.fromisoformat(str(e["meeting_date"])) >= today
    ]
    upcoming.sort(key=lambda event: event.meeting_date)
    return CbCalendarResponse(events=upcoming[:n], as_of_date=today)


# ---------------------------------------------------------------------------
#  Regional regime — 4-region dense table for Live Workbench
# ---------------------------------------------------------------------------

_REGIONAL_REGIME_CODES = ["US", "EU", "EM", "BR"]
_REGIONAL_SNAPSHOT_KEYS: dict[str, tuple[str, ...]] = {
    "US": ("US", "United States"),
    "EU": ("EU", "EUROPE", "Europe"),
    "EM": ("EM", "Emerging Markets"),
    "BR": ("BR", "Brazil"),
}


def _quadrant_label(growth: float, inflation: float) -> str:
    if growth >= 50 and inflation < 50:
        return "GOLDILOCKS"
    if growth >= 50 and inflation >= 50:
        return "OVERHEATING"
    if growth < 50 and inflation >= 50:
        return "STAGFLATION"
    return "REFLATION"


def _stress_level(growth: float, inflation: float) -> Literal["LOW", "MED", "HIGH"]:
    distance = ((growth - 50) ** 2 + (inflation - 50) ** 2) ** 0.5
    if distance >= 30:
        return "HIGH"
    if distance >= 15:
        return "MED"
    return "LOW"


def _region_payload(snapshot_data: dict[str, Any], code: str) -> dict[str, Any]:
    regions = snapshot_data.get("regions", {})
    if not isinstance(regions, dict):
        return {}
    for key in _REGIONAL_SNAPSHOT_KEYS[code]:
        payload = regions.get(key)
        if isinstance(payload, dict):
            return payload
    return {}


def _dimension_score(region_data: dict[str, Any], dimension: str) -> float | None:
    dimensions = region_data.get("dimensions", {})
    if not isinstance(dimensions, dict):
        return None
    payload = dimensions.get(dimension, {})
    if not isinstance(payload, dict):
        return None
    score = payload.get("score")
    return float(score) if score is not None else None


@router.get(
    "/regional-regime",
    response_model=RegionalRegimeResponse,
    summary="Current regime quadrant per tracked region",
    tags=["macro"],
)
@route_cache(ttl=900, key_prefix="macro:regional_regime")
async def get_regional_regime(
    user: CurrentUser = Depends(get_current_user),
) -> RegionalRegimeResponse:
    """Return US/EU/EM/BR regime labels for the Live Workbench panel."""
    stmt = (
        select(MacroRegionalSnapshot.as_of_date, MacroRegionalSnapshot.data_json)
        .order_by(MacroRegionalSnapshot.as_of_date.desc())
        .limit(2)
    )
    async with async_session_factory() as db:
        result = await db.execute(stmt)

    rows = result.all()
    if not rows:
        return RegionalRegimeResponse(
            as_of_date=None,
            regions=[
                RegionalRegimeRow(
                    region_code=code,
                    regime_label="GOLDILOCKS",
                    stress_level="LOW",
                    trend_up=True,
                )
                for code in _REGIONAL_REGIME_CODES
            ],
        )

    latest = rows[0]
    previous = rows[1] if len(rows) > 1 else None
    latest_data = latest.data_json if isinstance(latest.data_json, dict) else {}
    previous_data = (
        previous.data_json
        if previous is not None and isinstance(previous.data_json, dict)
        else {}
    )

    regions: list[RegionalRegimeRow] = []
    for code in _REGIONAL_REGIME_CODES:
        current_region = _region_payload(latest_data, code)
        previous_region = _region_payload(previous_data, code)
        growth_score = _dimension_score(current_region, "growth")
        inflation_score = _dimension_score(current_region, "inflation")
        growth = growth_score if growth_score is not None else 50.0
        inflation = inflation_score if inflation_score is not None else 50.0
        previous_growth = _dimension_score(previous_region, "growth")
        trend_up = (
            previous_growth <= growth
            if previous_growth is not None
            else growth >= 50.0
        )

        regions.append(
            RegionalRegimeRow(
                region_code=code,
                regime_label=_quadrant_label(growth, inflation),
                stress_level=_stress_level(growth, inflation),
                trend_up=trend_up,
                growth_score=round(growth_score, 1) if growth_score is not None else None,
                inflation_score=round(inflation_score, 1)
                if inflation_score is not None
                else None,
            ),
        )

    return RegionalRegimeResponse(as_of_date=latest.as_of_date, regions=regions)


@router.get(
    "/fred",
    response_model=FredDataResponse,
    summary="Raw FRED time series from macro_data",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.INVESTMENT_TEAM))],
)
async def get_fred_data(
    series_id: str = Query(..., description="FRED series ID, e.g. VIXCLS"),
    user: CurrentUser = Depends(get_current_user),
) -> FredDataResponse:
    """Return raw FRED time series from macro_data hypertable.

    Only allowlisted series are exposed. Cached in Redis for 1 hour.
    2-year lookback by default.
    """
    if series_id not in _FRED_ALLOWLIST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Series '{series_id}' is not available. Check /macro/fred allowlist.",
        )

    cache_key = f"fred:{series_id}"
    cached = await _get_cached(cache_key)
    if cached is not None:
        return FredDataResponse(series_id=series_id, data=cached)

    cutoff = date.today() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    stmt = (
        select(MacroData.obs_date, MacroData.value)
        .where(MacroData.series_id == series_id, MacroData.obs_date >= cutoff)
        .order_by(MacroData.obs_date)
    )

    async with async_session_factory() as db:
        result = await db.execute(stmt)

    rows = result.all()
    points = [
        FredTimePoint(obs_date=r.obs_date, value=float(r.value))
        for r in rows
        if r.value is not None
    ]

    await _set_cached(cache_key, [p.model_dump(mode="json") for p in points], ttl=3600)
    return FredDataResponse(series_id=series_id, data=points)
