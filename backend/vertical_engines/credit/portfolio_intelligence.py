from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domains.credit.deals.models.deals import Deal as PortfolioDeal
from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
    BoardMonitoringBrief,
    CashImpactFlag,
    CovenantStatusRegister,
    DealIntelligenceProfile,
    DocumentRegistry,
    InvestmentRiskRegistry,
    PerformanceDriftFlag,
)
from app.domains.credit.modules.deals.models import Deal as PipelineDeal
from app.domains.credit.modules.portfolio.models import (
    Covenant,
    CovenantBreach,
    CovenantTest,
    PortfolioMetric,
)

logger = logging.getLogger(__name__)

PORTFOLIO_CONTAINER = "portfolio-active-investments"


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _folder_from_blob(blob_path: str | None) -> str | None:
    parts = [p for p in (blob_path or "").split("/") if p]
    return parts[0] if parts else None


def _safe_float(value: object | None) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _extract_percent(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def discover_active_investments(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[ActiveInvestment]:
    docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == PORTFOLIO_CONTAINER,
            ),
        ).scalars().all(),
    )

    grouped: dict[str, list[DocumentRegistry]] = defaultdict(list)
    for doc in docs:
        folder = _folder_from_blob(doc.blob_path)
        if folder:
            grouped[folder].append(doc)

    # Load pipeline deals for name-matching + intelligence profiles
    p_deals = list(db.execute(select(PipelineDeal).where(PipelineDeal.fund_id == fund_id)).scalars().all())
    p_deals_by_name = {(d.deal_name or d.title or "").strip().lower(): d for d in p_deals}

    # Batch pre-load intelligence profiles for all pipeline deals
    all_profiles = list(
        db.execute(
            select(DealIntelligenceProfile).where(DealIntelligenceProfile.fund_id == fund_id),
        ).scalars().all(),
    )
    profiles_by_deal = {p.deal_id: p for p in all_profiles}

    # Batch pre-load existing active investments for the fund
    all_active_invs = list(
        db.execute(
            select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id),
        ).scalars().all(),
    )
    active_inv_by_folder = {inv.source_folder: inv for inv in all_active_invs if inv.source_folder}

    # Load portfolio deals — active_investments now FK → deals.id
    port_deals = list(db.execute(select(PortfolioDeal).where(PortfolioDeal.fund_id == fund_id)).scalars().all())
    port_by_name = {(d.name or "").strip().lower(): d for d in port_deals}
    # Also index by pipeline_deal_id for lookup after pipeline match
    port_by_pipeline = {d.pipeline_deal_id: d for d in port_deals if d.pipeline_deal_id}

    saved: list[ActiveInvestment] = []
    for folder_name, folder_docs in grouped.items():
        key = folder_name.strip().lower()
        p_deal = p_deals_by_name.get(key)           # pipeline deal (history)
        port_deal = port_by_name.get(key)            # portfolio deal (identity)

        # If we matched a pipeline deal but not a portfolio deal, try via approved_deal_id
        if p_deal and not port_deal:
            if p_deal.approved_deal_id:
                port_deal = next(
                    (d for d in port_deals if d.id == p_deal.approved_deal_id), None,
                )
            elif p_deal.id in port_by_pipeline:
                port_deal = port_by_pipeline[p_deal.id]

        source_folder = f"{PORTFOLIO_CONTAINER}/{folder_name}"
        primary_doc = max(folder_docs, key=lambda d: d.last_ingested_at)
        manager_name = (p_deal.sponsor_name if p_deal else None) or folder_name
        lifecycle = "ACTIVE"
        lifecycle_stage = p_deal.lifecycle_stage if p_deal and p_deal.lifecycle_stage else None
        if lifecycle_stage and lifecycle_stage.upper() in {"APPROVED", "DEPLOYED", "MONITORING"}:
            lifecycle = lifecycle_stage.upper()

        profile = profiles_by_deal.get(p_deal.id) if p_deal is not None else None

        existing = active_inv_by_folder.get(source_folder)

        target_return = profile.target_return if profile else None
        strategy = profile.strategy_type if profile else None

        transition_log: list[dict] = []
        if existing and existing.transition_log:
            transition_log = list(existing.transition_log)

        if existing and existing.lifecycle_status != lifecycle:
            transition_log.append(
                {
                    "from": existing.lifecycle_status,
                    "to": lifecycle,
                    "at": as_of.isoformat(),
                    "reason": "daily_monitoring_reclassification",
                },
            )

        # deal_id now points to portfolio deals.id (not pipeline_deals.id)
        payload = {
            "fund_id": fund_id,
            "access_level": "internal",
            "deal_id": port_deal.id if port_deal else None,
            "primary_document_id": primary_doc.id,
            "investment_name": folder_name,
            "manager_name": manager_name,
            "lifecycle_status": lifecycle,
            "source_container": PORTFOLIO_CONTAINER,
            "source_folder": source_folder,
            "strategy_type": strategy,
            "target_return": target_return,
            "last_monitoring_at": as_of,
            "transition_log": transition_log,
            "as_of": as_of,
            "data_latency": None,
            "data_quality": "OK",
            "created_by": actor_id,
            "updated_by": actor_id,
        }

        if existing is None:
            row = ActiveInvestment(**payload)
            db.add(row)
            db.flush()
        else:
            for key_name, value in payload.items():
                if key_name == "created_by":
                    continue
                setattr(existing, key_name, value)
            db.flush()
            row = existing

        saved.append(row)

    db.flush()
    return saved


def extract_portfolio_metrics(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[PortfolioMetric]:
    investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id)).scalars().all())
    as_of_date = as_of.date()

    db.execute(
        delete(PortfolioMetric).where(
            PortfolioMetric.fund_id == fund_id,
            PortfolioMetric.as_of == as_of_date,
            PortfolioMetric.metric_name.like("AI4_%"),
        ),
    )

    # ── METRIC STATUS: PENDING_REAL_DATA_SOURCE ──────────────────────
    # REFACTOR NOTE (Phase 1, Step 1): Synthetic day_factor modulation
    # has been removed.  Financial metrics (NAV, deployed capital,
    # expected returns) MUST originate from a real financial data source
    # (e.g. fund administrator NAV feed, portfolio management system).
    # Until that integration is wired, this function emits only metrics
    # whose underlying data already exists on the ActiveInvestment row.
    # Investments with NULL financials are tagged PENDING_REAL_DATA_SOURCE.
    # ──────────────────────────────────────────────────────────────────

    rows: list[PortfolioMetric] = []
    for inv in investments:
        committed = _safe_float(inv.committed_capital_usd)
        deployed = _safe_float(inv.deployed_capital_usd)
        nav = _safe_float(inv.current_nav_usd)
        target_return_pct = _extract_percent(inv.target_return)

        # Guard: if real financial data is absent, skip metric creation
        # and mark the investment as awaiting real data.
        if committed is None and deployed is None and nav is None:
            logger.info(
                "Investment %s (%s) has no real financial data — "
                "metric_status=PENDING_REAL_DATA_SOURCE",
                inv.id,
                inv.investment_name,
            )
            # Persist a single sentinel metric so downstream modules
            # can detect "no data" vs "never ran"
            sentinel = PortfolioMetric(
                fund_id=fund_id,
                access_level="internal",
                as_of=as_of_date,
                metric_name="AI4_DATA_STATUS",
                metric_value=0.0,
                meta={
                    "investmentId": str(inv.id),
                    "investmentName": inv.investment_name,
                    "asOf": as_of.isoformat(),
                    "metric_status": "PENDING_REAL_DATA_SOURCE",
                },
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(sentinel)
            rows.append(sentinel)
            continue

        # Use only real values — no synthetic fallbacks
        committed = committed or 0.0
        deployed = deployed or 0.0
        nav = nav or 0.0

        deployment_ratio = deployed / committed if committed > 0 else 0.0
        liquidity_days = int(max(1.0, committed / 250000.0)) if committed > 0 else 0

        metrics: list[tuple[str, float]] = [
            ("AI4_DEPLOYMENT_RATIO", float(deployment_ratio)),
            ("AI4_LIQUIDITY_DAYS", float(liquidity_days)),
        ]
        if nav > 0:
            metrics.append(("AI4_NAV_USD", float(nav)))
        if target_return_pct is not None:
            metrics.append(("AI4_RETURN_EXPECTED_PCT", float(target_return_pct)))

        for metric_name, metric_value in metrics:
            metric = PortfolioMetric(
                fund_id=fund_id,
                access_level="internal",
                as_of=as_of_date,
                metric_name=metric_name,
                metric_value=metric_value,
                meta={
                    "investmentId": str(inv.id),
                    "investmentName": inv.investment_name,
                    "asOf": as_of.isoformat(),
                    "metric_status": "REAL_DATA",
                },
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(metric)
            rows.append(metric)

    db.flush()
    return rows


def _latest_metric_by_investment(rows: list[PortfolioMetric], metric_name: str) -> dict[uuid.UUID, float]:
    out: dict[uuid.UUID, float] = {}
    for row in rows:
        if row.metric_name != metric_name:
            continue
        investment_id_raw = (row.meta or {}).get("investmentId")
        if not investment_id_raw:
            continue
        try:
            investment_id = uuid.UUID(str(investment_id_raw))
        except Exception:
            continue
        out[investment_id] = _safe_float(row.metric_value) or 0.0
    return out


def detect_performance_drift(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[PerformanceDriftFlag]:
    investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id)).scalars().all())
    if not investments:
        return []

    dates = list(
        db.execute(
            select(PortfolioMetric.as_of)
            .where(PortfolioMetric.fund_id == fund_id, PortfolioMetric.metric_name.like("AI4_%"))
            .group_by(PortfolioMetric.as_of)
            .order_by(PortfolioMetric.as_of.desc())
            .limit(2),
        ).scalars().all(),
    )

    db.execute(delete(PerformanceDriftFlag).where(PerformanceDriftFlag.fund_id == fund_id))
    if len(dates) < 2:
        db.flush()
        return []

    # Single query for both periods (excludes sentinel AI4_DATA_STATUS rows)
    both_period_rows = list(
        db.execute(
            select(PortfolioMetric).where(
                PortfolioMetric.fund_id == fund_id,
                PortfolioMetric.as_of.in_(dates),
                PortfolioMetric.metric_name.like("AI4_%"),
                PortfolioMetric.metric_name != "AI4_DATA_STATUS",
            ),
        ).scalars().all(),
    )
    current_rows = [r for r in both_period_rows if r.as_of == dates[0]]
    baseline_rows = [r for r in both_period_rows if r.as_of == dates[1]]

    current_by_metric = {
        "AI4_RETURN_EXPECTED_PCT": _latest_metric_by_investment(current_rows, "AI4_RETURN_EXPECTED_PCT"),
        "AI4_DEPLOYMENT_RATIO": _latest_metric_by_investment(current_rows, "AI4_DEPLOYMENT_RATIO"),
        "AI4_LIQUIDITY_DAYS": _latest_metric_by_investment(current_rows, "AI4_LIQUIDITY_DAYS"),
    }
    baseline_by_metric = {
        "AI4_RETURN_EXPECTED_PCT": _latest_metric_by_investment(baseline_rows, "AI4_RETURN_EXPECTED_PCT"),
        "AI4_DEPLOYMENT_RATIO": _latest_metric_by_investment(baseline_rows, "AI4_DEPLOYMENT_RATIO"),
        "AI4_LIQUIDITY_DAYS": _latest_metric_by_investment(baseline_rows, "AI4_LIQUIDITY_DAYS"),
    }

    thresholds = {
        "AI4_RETURN_EXPECTED_PCT": 10.0,
        "AI4_DEPLOYMENT_RATIO": 20.0,
        "AI4_LIQUIDITY_DAYS": 30.0,
    }

    flags: list[PerformanceDriftFlag] = []
    for inv in investments:
        for metric_name, threshold in thresholds.items():
            baseline = baseline_by_metric.get(metric_name, {}).get(inv.id)
            current = current_by_metric.get(metric_name, {}).get(inv.id)
            if baseline is None or current is None:
                continue
            if baseline == 0:
                drift_pct = 100.0 if current != 0 else 0.0
            else:
                drift_pct = ((current - baseline) / abs(baseline)) * 100.0

            if abs(drift_pct) < threshold:
                continue

            severity = "MEDIUM"
            if abs(drift_pct) >= (threshold * 1.5):
                severity = "HIGH"

            flag = PerformanceDriftFlag(
                fund_id=fund_id,
                access_level="internal",
                investment_id=inv.id,
                metric_name=metric_name,
                baseline_value=float(baseline),
                current_value=float(current),
                drift_pct=float(drift_pct),
                severity=severity,
                reasoning=(
                    f"Metric {metric_name} drift for {inv.investment_name} moved from {baseline:.4f} to {current:.4f} "
                    f"({drift_pct:.2f}%), above threshold {threshold:.2f}%."
                ),
                status="OPEN",
                as_of=as_of,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(flag)
            flags.append(flag)

    db.flush()
    return flags


def build_covenant_surveillance(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[CovenantStatusRegister]:
    investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id)).scalars().all())
    covenants = list(db.execute(select(Covenant).where(Covenant.fund_id == fund_id)).scalars().all())

    db.execute(delete(CovenantStatusRegister).where(CovenantStatusRegister.fund_id == fund_id))

    all_tests = list(db.execute(
        select(CovenantTest).where(CovenantTest.fund_id == fund_id)
        .order_by(CovenantTest.covenant_id, CovenantTest.tested_at.desc()),
    ).scalars().all())
    latest_test_by_covenant: dict[uuid.UUID, CovenantTest] = {}
    for t in all_tests:
        if t.covenant_id not in latest_test_by_covenant:
            latest_test_by_covenant[t.covenant_id] = t

    test_ids = [t.id for t in latest_test_by_covenant.values()]
    all_breaches = list(db.execute(
        select(CovenantBreach).where(
            CovenantBreach.fund_id == fund_id,
            CovenantBreach.covenant_test_id.in_(test_ids),
        ),
    ).scalars().all()) if test_ids else []
    breach_by_test: dict[uuid.UUID, CovenantBreach] = {b.covenant_test_id: b for b in all_breaches}

    saved: list[CovenantStatusRegister] = []
    for inv in investments:
        matched = covenants
        if matched:
            for covenant in matched:
                latest_test = latest_test_by_covenant.get(covenant.id)
                breach = breach_by_test.get(latest_test.id) if latest_test else None

                status = "PASS"
                severity = "LOW"
                details = "Latest covenant test passed or no breach evidence registered."
                if breach is not None:
                    status = "BREACH"
                    severity = "HIGH" if (breach.severity or "").lower() in {"critical", "high"} else "MEDIUM"
                    details = f"Breach detected with severity {breach.severity}."
                elif latest_test is None:
                    status = "NOT_TESTED"
                    severity = "MEDIUM"
                    details = "No covenant test found for current monitoring cycle."
                elif latest_test.passed is False:
                    status = "WARNING"
                    severity = "MEDIUM"
                    details = latest_test.notes or "Covenant test failed and requires review."

                last_tested_at = None
                if latest_test and latest_test.tested_at:
                    last_tested_at = dt.datetime.combine(latest_test.tested_at, dt.time.min, tzinfo=dt.UTC)
                next_due = (last_tested_at + dt.timedelta(days=30)) if last_tested_at else None

                row = CovenantStatusRegister(
                    fund_id=fund_id,
                    access_level="internal",
                    investment_id=inv.id,
                    covenant_id=covenant.id,
                    covenant_test_id=latest_test.id if latest_test else None,
                    breach_id=breach.id if breach else None,
                    covenant_name=covenant.name,
                    status=status,
                    severity=severity,
                    details=details,
                    last_tested_at=last_tested_at,
                    next_test_due_at=next_due,
                    as_of=as_of,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                db.add(row)
                saved.append(row)
        else:
            db.add(
                CovenantStatusRegister(
                    fund_id=fund_id,
                    access_level="internal",
                    investment_id=inv.id,
                    covenant_id=None,
                    covenant_test_id=None,
                    breach_id=None,
                    covenant_name="Portfolio Covenant Set",
                    status="NOT_CONFIGURED",
                    severity="MEDIUM",
                    details="No covenant configuration found for fund; monitoring requires covenant setup.",
                    last_tested_at=None,
                    next_test_due_at=None,
                    as_of=as_of,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            )

    db.flush()
    return list(db.execute(select(CovenantStatusRegister).where(CovenantStatusRegister.fund_id == fund_id)).scalars().all())


def evaluate_liquidity_cash_impact(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[CashImpactFlag]:
    """Evaluate liquidity/cash impact for investments.

    NOTE: Cash management domain has been removed from scope.
    This function now returns an empty list. It will be re-implemented
    when cash management is brought back or replaced by an external
    cash data feed.
    """
    db.execute(delete(CashImpactFlag).where(CashImpactFlag.fund_id == fund_id))
    db.flush()
    logger.info(
        "evaluate_liquidity_cash_impact: cash_management removed from scope, "
        "returning empty — fund=%s",
        fund_id,
    )
    return []


def reclassify_investment_risk(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[InvestmentRiskRegistry]:
    investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id)).scalars().all())

    drifts = list(db.execute(select(PerformanceDriftFlag).where(PerformanceDriftFlag.fund_id == fund_id)).scalars().all())
    covenants = list(db.execute(select(CovenantStatusRegister).where(CovenantStatusRegister.fund_id == fund_id)).scalars().all())
    cash_flags = list(db.execute(select(CashImpactFlag).where(CashImpactFlag.fund_id == fund_id)).scalars().all())

    by_inv_drift: dict[uuid.UUID, list[PerformanceDriftFlag]] = defaultdict(list)
    for row in drifts:
        by_inv_drift[row.investment_id].append(row)

    by_inv_cov: dict[uuid.UUID, list[CovenantStatusRegister]] = defaultdict(list)
    for row in covenants:
        by_inv_cov[row.investment_id].append(row)

    by_inv_cash: dict[uuid.UUID, list[CashImpactFlag]] = defaultdict(list)
    for row in cash_flags:
        by_inv_cash[row.investment_id].append(row)

    db.execute(delete(InvestmentRiskRegistry).where(InvestmentRiskRegistry.fund_id == fund_id))

    saved: list[InvestmentRiskRegistry] = []
    for inv in investments:
        drift_high = any(flag.severity == "HIGH" for flag in by_inv_drift.get(inv.id, []))
        covenant_breach = any(row.status in {"BREACH", "WARNING"} for row in by_inv_cov.get(inv.id, []))
        cash_high = any(flag.severity == "HIGH" for flag in by_inv_cash.get(inv.id, []))

        performance_level = "MEDIUM" if by_inv_drift.get(inv.id) else "LOW"
        if drift_high:
            performance_level = "HIGH"

        covenant_level = "HIGH" if covenant_breach else ("MEDIUM" if by_inv_cov.get(inv.id) else "LOW")
        liquidity_level = "HIGH" if cash_high else ("MEDIUM" if by_inv_cash.get(inv.id) else "LOW")

        overall = "LOW"
        if "HIGH" in {performance_level, covenant_level, liquidity_level}:
            overall = "HIGH"
        elif "MEDIUM" in {performance_level, covenant_level, liquidity_level}:
            overall = "MEDIUM"

        risk_rows = [
            (
                "PERFORMANCE",
                performance_level,
                "STABLE" if performance_level == "LOW" else "UP",
                f"Performance monitoring derived from {len(by_inv_drift.get(inv.id, []))} drift flags.",
            ),
            (
                "COVENANT",
                covenant_level,
                "UP" if covenant_level in {"MEDIUM", "HIGH"} else "STABLE",
                f"Covenant surveillance shows {len(by_inv_cov.get(inv.id, []))} status records.",
            ),
            (
                "LIQUIDITY",
                liquidity_level,
                "UP" if liquidity_level in {"MEDIUM", "HIGH"} else "STABLE",
                f"Cash impact monitoring produced {len(by_inv_cash.get(inv.id, []))} flags.",
            ),
            (
                "OVERALL",
                overall,
                "UP" if overall in {"MEDIUM", "HIGH"} else "STABLE",
                "Overall risk reclassification computed from performance, covenant, and liquidity dimensions.",
            ),
        ]

        for risk_type, level, trend, rationale in risk_rows:
            row = InvestmentRiskRegistry(
                fund_id=fund_id,
                access_level="internal",
                investment_id=inv.id,
                risk_type=risk_type,
                risk_level=level,
                trend=trend,
                rationale=rationale,
                source_evidence={
                    "driftFlags": [str(x.id) for x in by_inv_drift.get(inv.id, [])],
                    "covenantRows": [str(x.id) for x in by_inv_cov.get(inv.id, [])],
                    "cashFlags": [str(x.id) for x in by_inv_cash.get(inv.id, [])],
                },
                as_of=as_of,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(row)
            saved.append(row)

    db.flush()
    return saved


def build_board_monitoring_briefs(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
    investments: list[ActiveInvestment] | None = None,
    drifts: list[PerformanceDriftFlag] | None = None,
    covenants: list[CovenantStatusRegister] | None = None,
    cash_flags: list[CashImpactFlag] | None = None,
    risks: list[InvestmentRiskRegistry] | None = None,
) -> list[BoardMonitoringBrief]:
    if investments is None:
        investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id)).scalars().all())
    if drifts is None:
        drifts = list(db.execute(select(PerformanceDriftFlag).where(PerformanceDriftFlag.fund_id == fund_id)).scalars().all())
    if covenants is None:
        covenants = list(db.execute(select(CovenantStatusRegister).where(CovenantStatusRegister.fund_id == fund_id)).scalars().all())
    if cash_flags is None:
        cash_flags = list(db.execute(select(CashImpactFlag).where(CashImpactFlag.fund_id == fund_id)).scalars().all())
    if risks is None:
        risks = list(db.execute(select(InvestmentRiskRegistry).where(InvestmentRiskRegistry.fund_id == fund_id)).scalars().all())

    by_inv_drift: dict[uuid.UUID, list[PerformanceDriftFlag]] = defaultdict(list)
    for row in drifts:
        by_inv_drift[row.investment_id].append(row)

    by_inv_cov: dict[uuid.UUID, list[CovenantStatusRegister]] = defaultdict(list)
    for row in covenants:
        by_inv_cov[row.investment_id].append(row)

    by_inv_cash: dict[uuid.UUID, list[CashImpactFlag]] = defaultdict(list)
    for row in cash_flags:
        by_inv_cash[row.investment_id].append(row)

    by_inv_risk: dict[uuid.UUID, list[InvestmentRiskRegistry]] = defaultdict(list)
    for row in risks:
        by_inv_risk[row.investment_id].append(row)

    saved: list[BoardMonitoringBrief] = []
    for inv in investments:
        drift_rows = by_inv_drift.get(inv.id, [])
        cov_rows = by_inv_cov.get(inv.id, [])
        cash_rows = by_inv_cash.get(inv.id, [])
        risk_rows = by_inv_risk.get(inv.id, [])

        overall = next((r for r in risk_rows if r.risk_type == "OVERALL"), None)
        overall_level = overall.risk_level if overall else "LOW"

        performance_view = f"{len(drift_rows)} drift events registered; high severity count: {sum(1 for r in drift_rows if r.severity == 'HIGH')}."
        covenant_view = f"{len(cov_rows)} covenant status entries; breach/warning count: {sum(1 for r in cov_rows if r.status in {'BREACH', 'WARNING'})}."
        liquidity_view = f"{len(cash_rows)} cash impact events; high severity count: {sum(1 for r in cash_rows if r.severity == 'HIGH')}."
        risk_view = f"Current overall risk level is {overall_level}; lifecycle status {inv.lifecycle_status}."

        actions = [
            "Review high-severity drift flags and validate baseline assumptions.",
            "Confirm covenant testing cadence and remediation ownership.",
            "Validate liquidity forecast against projected capital calls/distributions.",
        ]

        brief_payload = {
            "fund_id": fund_id,
            "access_level": "internal",
            "investment_id": inv.id,
            "executive_summary": (
                f"{inv.investment_name} monitored as of {as_of.isoformat()} with overall risk {overall_level}."
            ),
            "performance_view": performance_view,
            "covenant_view": covenant_view,
            "liquidity_view": liquidity_view,
            "risk_reclassification_view": risk_view,
            "recommended_actions": actions,
            "last_generated_at": as_of,
            "as_of": as_of,
            "created_by": actor_id,
            "updated_by": actor_id,
        }

        existing = db.execute(
            select(BoardMonitoringBrief).where(
                BoardMonitoringBrief.fund_id == fund_id,
                BoardMonitoringBrief.investment_id == inv.id,
            ),
        ).scalar_one_or_none()

        if existing is None:
            row = BoardMonitoringBrief(**brief_payload)
            db.add(row)
            db.flush()
        else:
            for key_name, value in brief_payload.items():
                if key_name == "created_by":
                    continue
                setattr(existing, key_name, value)
            db.flush()
            row = existing

        saved.append(row)

    db.flush()
    return saved


def run_portfolio_ingest(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
    as_of: dt.datetime | None = None,
) -> dict[str, int | str]:
    monitoring_as_of = as_of or _now_utc()

    try:
        investments = discover_active_investments(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        metrics = extract_portfolio_metrics(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        drifts = detect_performance_drift(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        covenants = build_covenant_surveillance(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        cash_flags = evaluate_liquidity_cash_impact(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        risk_registry = reclassify_investment_risk(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        briefs = build_board_monitoring_briefs(
            db,
            fund_id=fund_id,
            as_of=monitoring_as_of,
            actor_id=actor_id,
            investments=investments,
            drifts=drifts,
            covenants=covenants,
            cash_flags=cash_flags,
            risks=risk_registry,
        )

        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "PORTFOLIO_INGEST_FAILED fund_id=%s — all changes rolled back",
            fund_id,
        )
        raise

    return {
        "asOf": monitoring_as_of.isoformat(),
        "investments": len(investments),
        "metrics": len(metrics),
        "drifts": len(drifts),
        "covenants": len(covenants),
        "cashFlags": len(cash_flags),
        "riskRegistry": len(risk_registry),
        "briefs": len(briefs),
    }
