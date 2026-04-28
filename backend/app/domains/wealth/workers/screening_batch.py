"""Screening batch worker — weekly re-screening of all active instruments.

Uses pg_try_advisory_lock (non-blocking) with hardcoded lock ID 900_002.
Python hash() is nondeterministic across processes — never use it for lock IDs.

Short transactions: commits every 200 results to prevent connection pool starvation.
Config captured at start (frozen for entire run — prevents mid-batch inconsistency).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.db.engine import async_session_factory
from app.core.tenancy.middleware import set_rls_context
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.screening_result import ScreeningResult, ScreeningRun

logger = logging.getLogger(__name__)

SCREENING_BATCH_LOCK_ID = 900_002


def _chunked(iterable: list, size: int):
    """Yield chunks of `size` from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


async def run_screening_batch(org_id: uuid.UUID) -> dict:
    """Weekly batch re-screening. Uses pg_try_advisory_lock (non-blocking).

    Returns dict with status, counts, or skip reason.
    """
    async with async_session_factory() as db:
        await set_rls_context(db, org_id)
        # 1. Non-blocking advisory lock
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({SCREENING_BATCH_LOCK_ID})"),
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.info("Screening batch skipped — another instance is running")
            return {"status": "skipped", "reason": "batch already running"}

        try:
            return await _execute_batch(db, org_id)
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({SCREENING_BATCH_LOCK_ID})"),
            )


async def _execute_batch(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Execute the batch screening logic."""
    # 2. Fetch config ONCE (frozen for entire run)
    config_svc = ConfigService(db)
    config_l1 = (await config_svc.get("liquid_funds", "screening_layer1", org_id)).value
    config_l2 = (await config_svc.get("liquid_funds", "screening_layer2", org_id)).value
    config_l3 = (await config_svc.get("liquid_funds", "screening_layer3", org_id)).value

    config_hash = hashlib.sha256(
        json.dumps({"l1": config_l1, "l2": config_l2, "l3": config_l3}, sort_keys=True).encode(),
    ).hexdigest()

    # 3. Load all active instruments (short transaction)
    result = await db.execute(
        select(Instrument).where(Instrument.is_active.is_(True)),
    )
    instruments = result.scalars().all()

    if not instruments:
        logger.info("No active instruments to screen")
        return {"status": "completed", "instrument_count": 0}

    # Load latest fund_risk_metrics for each instrument (global table, no RLS)
    from app.domains.wealth.models.risk import FundRiskMetrics

    instrument_ids = [i.instrument_id for i in instruments]
    rm_res = await db.execute(
        select(FundRiskMetrics)
        .where(FundRiskMetrics.instrument_id.in_(instrument_ids))
        .distinct(FundRiskMetrics.instrument_id)
        .order_by(FundRiskMetrics.instrument_id, FundRiskMetrics.calc_date.desc()),
    )
    risk_metrics_by_id = {rm.instrument_id: rm for rm in rm_res.scalars().all()}

    # Load previous current screening_results for hysteresis
    prev_result = await db.execute(
        select(ScreeningResult).where(
            ScreeningResult.instrument_id.in_(instrument_ids),
            ScreeningResult.is_current.is_(True),
        ),
    )
    prev_status_by_id = {sr.instrument_id: sr.overall_status for sr in prev_result.scalars()}

    # Build per-instrument metric dicts for cohort peer_values
    from app.domains.wealth.services.screener_peer_values_builder import (
        METRIC_NAMES_BY_TYPE,
        build_per_instrument_peer_values,
    )
    from vertical_engines.wealth.screener.quant_metrics import (
        AltQuantMetrics,
        CashQuantMetrics,
        FIQuantMetrics,
        QuantMetrics,
    )

    def _safe_float(val: object, scale: float = 1.0) -> float | None:
        if val is None:
            return None
        try:
            return float(val) * scale
        except (ValueError, TypeError):
            return None

    # Build metric dicts (raw values for peer cohort building)
    metric_dicts_by_id: dict[uuid.UUID, dict[str, float | None]] = {}
    for i in instruments:
        rm = risk_metrics_by_id.get(i.instrument_id)
        attrs = dict(i.attributes) if i.attributes else {}
        asset_class = attrs.get("asset_class", "")
        if rm is None:
            metric_dicts_by_id[i.instrument_id] = {}
            continue
        if asset_class == "fixed_income":
            metric_dicts_by_id[i.instrument_id] = {
                "empirical_duration": _safe_float(rm.empirical_duration),
                "credit_beta": _safe_float(rm.credit_beta),
                "yield_proxy_12m": _safe_float(rm.yield_proxy_12m),
                "duration_adj_drawdown": _safe_float(rm.duration_adj_drawdown_1y),
                "sharpe_ratio": _safe_float(rm.sharpe_1y),
            }
        elif asset_class == "cash":
            metric_dicts_by_id[i.instrument_id] = {
                "yield_vs_risk_free": _safe_float(getattr(rm, "yield_vs_risk_free", None)),
                "nav_stability": _safe_float(getattr(rm, "nav_stability", None)),
                "liquidity_quality": _safe_float(getattr(rm, "liquidity_quality", None)),
                "maturity_discipline": _safe_float(getattr(rm, "maturity_discipline", None)),
                "fee_efficiency": _safe_float(getattr(rm, "fee_efficiency", None)),
            }
        elif asset_class == "alternatives":
            metric_dicts_by_id[i.instrument_id] = {
                "diversification_value": _safe_float(getattr(rm, "diversification_value", None)),
                "downside_protection": _safe_float(getattr(rm, "downside_protection", None)),
                "crisis_alpha": _safe_float(getattr(rm, "crisis_alpha", None)),
                "inflation_hedge": _safe_float(getattr(rm, "inflation_hedge", None)),
                "risk_adjusted_return": _safe_float(rm.sharpe_1y),
                "fee_efficiency": _safe_float(getattr(rm, "fee_efficiency", None)),
            }
        else:
            metric_dicts_by_id[i.instrument_id] = {
                "sharpe_ratio": _safe_float(rm.sharpe_1y),
                "max_drawdown": _safe_float(rm.max_drawdown_1y),
                "pct_positive_months": _safe_float(getattr(rm, "pct_positive_months", None)),
                "annual_volatility_pct": _safe_float(rm.volatility_1y, scale=100),
            }

    # Build instrument dicts for cohort grouping
    inst_dicts_for_cohorts = [
        {
            "instrument_id": i.instrument_id,
            "instrument_type": i.instrument_type,
            "attributes": dict(i.attributes) if i.attributes else {},
        }
        for i in instruments
    ]

    # Build per-instrument peer_values
    peer_values_by_id = build_per_instrument_peer_values(
        instruments=inst_dicts_for_cohorts,
        instrument_metrics_by_id=metric_dicts_by_id,
        metric_names_by_type=METRIC_NAMES_BY_TYPE,
    )

    def _build_quant_metrics(
        rm: object, attrs: dict,
    ) -> QuantMetrics | FIQuantMetrics | CashQuantMetrics | AltQuantMetrics | None:
        if rm is None:
            return None
        asset_class = attrs.get("asset_class", "")
        if asset_class == "fixed_income":
            if rm.empirical_duration is None and rm.credit_beta is None:
                return None
            return FIQuantMetrics(
                empirical_duration=float(rm.empirical_duration or 0),
                credit_beta=float(rm.credit_beta or 0),
                yield_proxy_12m=float(rm.yield_proxy_12m or 0),
                duration_adj_drawdown=float(rm.duration_adj_drawdown_1y or 0),
                sharpe_ratio=float(rm.sharpe_1y or 0),
                annual_return_pct=float(rm.return_1y or 0) * 100,
                data_period_days=0,
            )
        if asset_class == "cash":
            return CashQuantMetrics(
                yield_vs_risk_free=float(getattr(rm, "yield_vs_risk_free", 0) or 0),
                nav_stability=float(getattr(rm, "nav_stability", 0) or 0),
                liquidity_quality=float(getattr(rm, "liquidity_quality", 0) or 0),
                maturity_discipline=float(getattr(rm, "maturity_discipline", 0) or 0),
                fee_efficiency=float(getattr(rm, "fee_efficiency", 0) or 0),
                data_source="fund_risk_metrics",
            )
        if asset_class == "alternatives":
            return AltQuantMetrics(
                diversification_value=float(getattr(rm, "diversification_value", 0) or 0),
                downside_protection=float(getattr(rm, "downside_protection", 0) or 0),
                crisis_alpha=float(getattr(rm, "crisis_alpha", 0) or 0),
                inflation_hedge=float(getattr(rm, "inflation_hedge", 0) or 0),
                risk_adjusted_return=float(rm.sharpe_1y or 0),
                fee_efficiency=float(getattr(rm, "fee_efficiency", 0) or 0),
                alt_profile="generic_alt",
            )
        # Default: equity/fund
        return QuantMetrics(
            sharpe_ratio=float(rm.sharpe_1y or 0),
            annual_volatility_pct=float(rm.volatility_1y or 0) * 100,
            max_drawdown_pct=float(rm.max_drawdown_1y or 0) * 100,
            pct_positive_months=float(getattr(rm, "pct_positive_months", 0) or 0),
            annual_return_pct=float(rm.return_1y or 0) * 100,
            data_period_days=0,
        )

    # Extract scalar data before crossing async/thread boundary
    instrument_dicts = [
        {
            "instrument_id": i.instrument_id,
            "instrument_type": i.instrument_type,
            "attributes": dict(i.attributes) if i.attributes else {},
            "block_id": getattr(i, "block_id", None),
            "quant_metrics": _build_quant_metrics(
                risk_metrics_by_id.get(i.instrument_id),
                dict(i.attributes) if i.attributes else {},
            ),
            "peer_values": peer_values_by_id.get(i.instrument_id, {}),
            "previous_status": prev_status_by_id.get(i.instrument_id),
        }
        for i in instruments
    ]

    # 4. Create screening run record
    run = ScreeningRun(
        organization_id=org_id,
        run_type="batch",
        instrument_count=len(instrument_dicts),
        config_hash=config_hash,
    )
    db.add(run)
    await db.flush()
    run_id = run.run_id

    # 5. Compute all layers in thread (pure logic, no DB)
    from vertical_engines.wealth.screener.service import ScreenerService

    screener = ScreenerService(config_l1, config_l2, config_l3)
    screening_results = await asyncio.to_thread(
        lambda: [
            screener.screen_instrument(**inst_dict)
            for inst_dict in instrument_dicts
        ],
    )

    # 6. Write in batches of 200 (short transactions)
    for batch in _chunked(screening_results, 200):
        # Mark previous results as not current for this batch
        batch_ids = [sr.instrument_id for sr in batch]
        await db.execute(
            update(ScreeningResult)
            .where(
                ScreeningResult.instrument_id.in_(batch_ids),
                ScreeningResult.is_current.is_(True),
            )
            .values(is_current=False),
        )

        # Insert new results
        for sr in batch:
            screening_result = ScreeningResult(
                organization_id=org_id,
                instrument_id=sr.instrument_id,
                run_id=run_id,
                overall_status=sr.overall_status,
                score=sr.score,
                failed_at_layer=sr.failed_at_layer,
                layer_results=sr.layer_results_dict,
                required_analysis_type=sr.required_analysis_type,
                is_current=True,
            )
            db.add(screening_result)

        await db.commit()
        await set_rls_context(db, org_id)

    # 7. Mark run as completed
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    await db.commit()
    await set_rls_context(db, org_id)

    passed = sum(1 for r in screening_results if r.overall_status == "PASS")
    failed = sum(1 for r in screening_results if r.overall_status == "FAIL")
    watchlist = sum(1 for r in screening_results if r.overall_status == "WATCHLIST")

    logger.info(
        "Screening batch completed",
        instrument_count=len(screening_results),
        passed=passed,
        failed=failed,
        watchlist=watchlist,
    )

    return {
        "status": "completed",
        "instrument_count": len(screening_results),
        "passed": passed,
        "failed": failed,
        "watchlist": watchlist,
    }
