"""Macro intelligence API routes — regional scores, snapshot, regime, committee.

Phase 1: GET /scores, GET /snapshot
Phase 2: GET /regime, GET /reviews, POST /reviews/generate,
         PATCH /reviews/{id}/approve, PATCH /reviews/{id}/reject
Phase 3A: GET /bis, GET /imf, GET /treasury, GET /ofr — raw hypertable data
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import route_cache
from app.core.config.config_service import ConfigService
from app.core.db.engine import async_session_factory
from app.core.security.clerk_auth import CurrentUser, get_current_user, require_role
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.macro_committee import MacroReview
from app.domains.wealth.routes.common import _get_content_semaphore, require_content_slot
from app.domains.wealth.schemas.macro import (
    BisDataResponse,
    BisTimePoint,
    DataFreshnessRead,
    DimensionScoreRead,
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
    RegimeHierarchyRead,
    RegionalScoreRead,
    TreasuryDataResponse,
    TreasuryTimePoint,
)
from app.shared.enums import Role
from app.shared.models import (
    BisStatistics,
    ImfWeoForecast,
    MacroRegionalSnapshot,
    OfrHedgeFundData,
    TreasuryData,
)
from quant_engine.allocation_proposal_service import (
    compute_regime_tilted_weights,
    extract_regime_from_review,
    extract_regional_scores_from_snapshot,
)
from quant_engine.regime_service import (
    REGIONAL_REGIME_SIGNALS,
    classify_regional_regime,
    compose_global_regime,
    get_latest_macro_values,
    resolve_regional_regime_config,
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
        f"The {name} macro environment is currently {tone} with a composite score of {composite_score:.0f}/100."
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

    Scores are percentile-ranked (0-100, 50 = historical median).
    Higher = better conditions (except inverted indicators like VIX).
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

    data = snapshot.data_json

    # Parse regions
    regions: dict[str, RegionalScoreRead] = {}
    for region_key, region_data in data.get("regions", {}).items():
        dimensions = {
            dim: DimensionScoreRead(**dim_data)
            for dim, dim_data in region_data.get("dimensions", {}).items()
        }
        freshness = {
            sid: DataFreshnessRead(**f_data)
            for sid, f_data in region_data.get("data_freshness", {}).items()
        }
        analysis_text = _build_analysis_text(
            region_key, region_data["composite_score"], dimensions,
        )
        regions[region_key] = RegionalScoreRead(
            composite_score=region_data["composite_score"],
            coverage=region_data["coverage"],
            dimensions=dimensions,
            data_freshness=freshness,
            analysis_text=analysis_text,
        )

    # Parse global indicators
    gi_data = data.get("global_indicators", {})
    global_indicators = GlobalIndicatorsRead(
        geopolitical_risk_score=gi_data.get("geopolitical_risk_score", 50.0),
        energy_stress=gi_data.get("energy_stress", 50.0),
        commodity_stress=gi_data.get("commodity_stress", 50.0),
        usd_strength=gi_data.get("usd_strength", 50.0),
    )

    return MacroScoresResponse(
        as_of_date=snapshot.as_of_date,
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
    response_model=RegimeHierarchyRead,
    summary="Hierarchical regime: global + per-region",
    tags=["macro"],
)
async def get_hierarchical_regime(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: UUID | None = Depends(get_org_id),
) -> RegimeHierarchyRead:
    """Return hierarchical regime classification: global + 4 regions.

    Uses ICE BofA credit spreads for regional signals and GDP-weighted
    composition with pessimistic override for global regime.
    """
    macro = await get_latest_macro_values(db)
    config_service = ConfigService(db)
    raw_result = await config_service.get("liquid_funds", "macro_intelligence", org_id)
    config = resolve_regional_regime_config(raw_result.value)

    vix_val = macro.get("VIXCLS", (None, None))[0]
    cpi_val = macro.get("CPI_YOY", (None, None))[0]

    regional_results: dict[str, str] = {}
    for region, signal_ids in REGIONAL_REGIME_SIGNALS.items():
        signal_values = {
            sid: macro.get(sid, (None, None))[0] for sid in signal_ids
        }
        result = classify_regional_regime(
            region, signal_values,
            vix=vix_val if region == "US" else None,
            cpi_yoy=cpi_val,
            config=config,
        )
        regional_results[region] = result.regime

    global_regime, composition_reasons = compose_global_regime(
        regional_results, config=config,
    )

    as_of = None
    for _, obs_date in macro.values():
        if obs_date is not None and (as_of is None or obs_date > as_of):
            as_of = obs_date

    return RegimeHierarchyRead(
        global_regime=global_regime,
        regional_regimes=regional_results,
        composition_reasons=composition_reasons,
        as_of_date=as_of,
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

        # Compute regime hierarchy and embed in report for downstream use
        regime_data: dict[str, Any] | None = None
        try:
            config_service = ConfigService(db)
            raw_config = await config_service.get(
                "liquid_funds", "macro_intelligence", org_id,
            )
            regime_config = resolve_regional_regime_config(raw_config.value)
            macro = await get_latest_macro_values(db)
            vix_val = macro.get("VIXCLS", (None, None))[0]
            cpi_val = macro.get("CPI_YOY", (None, None))[0]

            regional_regimes: dict[str, str] = {}
            for region, signal_ids in REGIONAL_REGIME_SIGNALS.items():
                signal_values = {
                    sid: macro.get(sid, (None, None))[0] for sid in signal_ids
                }
                rr = classify_regional_regime(
                    region, signal_values,
                    vix=vix_val if region == "US" else None,
                    cpi_yoy=cpi_val,
                    config=regime_config,
                )
                regional_regimes[region] = rr.regime

            global_regime, composition_reasons = compose_global_regime(
                regional_regimes, config=regime_config,
            )
            regime_data = {
                "global": global_regime,
                "regional": regional_regimes,
                "composition_reasons": composition_reasons,
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
    review.approved_by = user.actor_id
    review.approved_at = datetime.now(timezone.utc)
    review.decision_rationale = body.decision_rationale

    # ── G1.1 + G1.2: Generate allocation proposals from regime ──
    await _generate_allocation_proposals(db, review, user.actor_id, org_id)

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
    raw_config = await config_service.get("liquid_funds", "profiles", org_id)
    profiles_config = raw_config.value if raw_config else {}
    profiles_dict: dict = profiles_config.get("profiles", profiles_config)

    # Extract regime + regional scores from the approved review
    report_json = review.report_json or {}
    global_regime = extract_regime_from_review(report_json)

    # If regime data wasn't embedded in report, compute it live
    if global_regime == "RISK_ON" and not report_json.get("regime"):
        macro = await get_latest_macro_values(db)
        raw_regime_config = await config_service.get(
            "liquid_funds", "macro_intelligence", org_id,
        )
        regime_config = resolve_regional_regime_config(raw_regime_config.value)
        vix_val = macro.get("VIXCLS", (None, None))[0]
        cpi_val = macro.get("CPI_YOY", (None, None))[0]

        regional_results: dict[str, str] = {}
        for region, signal_ids in REGIONAL_REGIME_SIGNALS.items():
            signal_values = {
                sid: macro.get(sid, (None, None))[0] for sid in signal_ids
            }
            rr = classify_regional_regime(
                region, signal_values,
                vix=vix_val if region == "US" else None,
                cpi_yoy=cpi_val,
                config=regime_config,
            )
            regional_results[region] = rr.regime

        global_regime_computed, _ = compose_global_regime(
            regional_results, config=regime_config,
        )
        global_regime = global_regime_computed

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

            row = StrategicAllocation(
                profile=profile_name,
                block_id=bp.block_id,
                target_weight=D(str(bp.proposed_weight)),
                min_weight=D(str(bp.min_weight)),
                max_weight=D(str(bp.max_weight)),
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
    review.approved_by = user.actor_id  # Record who rejected for audit trail
    review.decision_rationale = body.decision_rationale

    await db.flush()
    return MacroReviewRead.model_validate(review)


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
    cache_key = f"bis:{country}:{indicator}"
    cached = await _get_cached(cache_key)
    if cached is not None:
        return BisDataResponse(country=country, indicator=indicator, data=cached)

    cutoff = datetime.now(timezone.utc) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    stmt = (
        select(BisStatistics.period, BisStatistics.value)
        .where(
            BisStatistics.country_code == country,
            BisStatistics.indicator == indicator,
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

    cutoff = datetime.now(timezone.utc) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
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
    """Return raw Treasury time series for a given series ID.

    Cached in Redis for 1 hour. 2-year lookback by default.
    """
    cache_key = f"treasury:{series}"
    cached = await _get_cached(cache_key)
    if cached is not None:
        return TreasuryDataResponse(series=series, data=cached)

    cutoff = date.today() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    stmt = (
        select(TreasuryData.obs_date, TreasuryData.value)
        .where(
            TreasuryData.series_id == series,
            TreasuryData.obs_date >= cutoff,
        )
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
    cache_key = f"ofr:{metric}"
    cached = await _get_cached(cache_key)
    if cached is not None:
        return OfrDataResponse(metric=metric, data=cached)

    cutoff = date.today() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    stmt = (
        select(OfrHedgeFundData.obs_date, OfrHedgeFundData.value)
        .where(
            OfrHedgeFundData.series_id == metric,
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
