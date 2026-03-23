"""AI Portfolio sub-router — investments, alerts, reviews, monitoring."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.session import get_sync_db_with_rls
from app.core.security.clerk_auth import Actor, get_actor, require_readonly_allowed, require_roles
from app.domains.credit.deals.models.deals import Deal as PortfolioDeal
from app.domains.credit.modules.ai._helpers import _utcnow
from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
    BoardMonitoringBrief,
    CashImpactFlag,
    CovenantStatusRegister,
    InvestmentRiskRegistry,
    PerformanceDriftFlag,
    PeriodicReviewReport,
)
from app.domains.credit.modules.ai.schemas import (
    CashflowEventItem,
    CashflowSummary,
    CovenantMonitoringItem,
    DeepReviewRequest,
    PeriodicReviewOut,
    PeriodicReviewPdfResponse,
    PeriodicReviewResponse,
    PeriodicReviewsListResponse,
    PortfolioAlertOut,
    PortfolioAlertsResponse,
    PortfolioBatchReviewResponse,
    PortfolioBriefOut,
    PortfolioCashImpactOut,
    PortfolioCovenantOut,
    PortfolioDealMonitoringResponse,
    PortfolioDriftOut,
    PortfolioIngestResponse,
    PortfolioInvestmentDetailResponse,
    PortfolioInvestmentItem,
    PortfolioInvestmentsResponse,
    PortfolioReviewResponse,
    PortfolioRiskOut,
    RiskMonitoringItem,
)
from app.domains.credit.modules.deals import cashflow_service as cf_svc
from app.shared.enums import Role
from vertical_engines.credit.deep_review import (
    run_all_portfolio_reviews,
    run_portfolio_review,
)
from vertical_engines.credit.portfolio import run_portfolio_ingest

router = APIRouter()


@router.post("/portfolio/ingest", response_model=PortfolioIngestResponse)
def ingest_portfolio_intelligence(
    fund_id: uuid.UUID,
    as_of: dt.datetime | None = Query(default=None),
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM])),
) -> PortfolioIngestResponse:
    result = run_portfolio_ingest(db, fund_id=fund_id, actor_id=actor.actor_id, as_of=as_of)
    payload_as_of = dt.datetime.fromisoformat(str(result["asOf"]))
    return PortfolioIngestResponse(
        asOf=payload_as_of,
        investments=int(result["investments"]),
        metrics=int(result["metrics"]),
        drifts=int(result["drifts"]),
        covenants=int(result["covenants"]),
        cashFlags=int(result["cashFlags"]),
        riskRegistry=int(result["riskRegistry"]),
        briefs=int(result["briefs"]),
    )


@router.get("/portfolio/investments", response_model=PortfolioInvestmentsResponse)
def list_portfolio_investments(
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> PortfolioInvestmentsResponse:
    investments = list(
        db.execute(
            select(ActiveInvestment)
            .where(ActiveInvestment.fund_id == fund_id)
            .order_by(ActiveInvestment.last_monitoring_at.desc().nullslast(), ActiveInvestment.updated_at.desc()),
        ).scalars().all(),
    )
    risks = list(
        db.execute(
            select(InvestmentRiskRegistry).where(
                InvestmentRiskRegistry.fund_id == fund_id,
                InvestmentRiskRegistry.risk_type == "OVERALL",
            ),
        ).scalars().all(),
    )
    risk_by_investment = {row.investment_id: row for row in risks}

    items = [
        PortfolioInvestmentItem(
            investmentId=row.id,
            investmentName=row.investment_name,
            managerName=row.manager_name,
            lifecycleStatus=row.lifecycle_status,
            strategyType=row.strategy_type,
            targetReturn=row.target_return,
            committedCapitalUsd=float(row.committed_capital_usd) if row.committed_capital_usd is not None else None,
            deployedCapitalUsd=float(row.deployed_capital_usd) if row.deployed_capital_usd is not None else None,
            currentNavUsd=float(row.current_nav_usd) if row.current_nav_usd is not None else None,
            overallRiskLevel=risk_by_investment.get(row.id).risk_level if risk_by_investment.get(row.id) else None,
            asOf=row.as_of,
        )
        for row in investments
    ]

    as_of = max((item.asOf for item in items), default=_utcnow())
    return PortfolioInvestmentsResponse(asOf=as_of, dataLatency=None, dataQuality="OK", items=items)


@router.get("/portfolio/investments/{investment_id}", response_model=PortfolioInvestmentDetailResponse)
def get_portfolio_investment_detail(
    investment_id: uuid.UUID,
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> PortfolioInvestmentDetailResponse:
    investment = db.execute(
        select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id, ActiveInvestment.id == investment_id),
    ).scalar_one_or_none()
    if investment is None:
        raise HTTPException(status_code=404, detail="Active investment not found")

    drifts = list(
        db.execute(
            select(PerformanceDriftFlag)
            .where(PerformanceDriftFlag.fund_id == fund_id, PerformanceDriftFlag.investment_id == investment_id)
            .order_by(PerformanceDriftFlag.created_at.desc()),
        ).scalars().all(),
    )
    covenants = list(
        db.execute(
            select(CovenantStatusRegister)
            .where(CovenantStatusRegister.fund_id == fund_id, CovenantStatusRegister.investment_id == investment_id)
            .order_by(CovenantStatusRegister.created_at.desc()),
        ).scalars().all(),
    )
    cash_impacts = list(
        db.execute(
            select(CashImpactFlag)
            .where(CashImpactFlag.fund_id == fund_id, CashImpactFlag.investment_id == investment_id)
            .order_by(CashImpactFlag.created_at.desc()),
        ).scalars().all(),
    )
    risks = list(
        db.execute(
            select(InvestmentRiskRegistry)
            .where(InvestmentRiskRegistry.fund_id == fund_id, InvestmentRiskRegistry.investment_id == investment_id)
            .order_by(InvestmentRiskRegistry.created_at.desc()),
        ).scalars().all(),
    )
    brief = db.execute(
        select(BoardMonitoringBrief).where(BoardMonitoringBrief.fund_id == fund_id, BoardMonitoringBrief.investment_id == investment_id),
    ).scalar_one_or_none()

    drift_out = [
        PortfolioDriftOut(
            metricName=row.metric_name,
            baselineValue=float(row.baseline_value) if row.baseline_value is not None else None,
            currentValue=float(row.current_value) if row.current_value is not None else None,
            driftPct=float(row.drift_pct) if row.drift_pct is not None else None,
            severity=row.severity,
            reasoning=row.reasoning,
        )
        for row in drifts
    ]
    covenant_out = [
        PortfolioCovenantOut(
            covenantName=row.covenant_name,
            status=row.status,
            severity=row.severity,
            details=row.details,
            lastTestedAt=row.last_tested_at,
            nextTestDueAt=row.next_test_due_at,
        )
        for row in covenants
    ]
    cash_out = [
        PortfolioCashImpactOut(
            impactType=row.impact_type,
            severity=row.severity,
            estimatedImpactUsd=float(row.estimated_impact_usd) if row.estimated_impact_usd is not None else None,
            liquidityDays=row.liquidity_days,
            message=row.message,
            resolvedFlag=row.resolved_flag,
        )
        for row in cash_impacts
    ]
    risk_out = [
        PortfolioRiskOut(
            riskType=row.risk_type,
            riskLevel=row.risk_level,
            trend=row.trend,
            rationale=row.rationale,
        )
        for row in risks
    ]
    brief_out = (
        PortfolioBriefOut(
            executiveSummary=brief.executive_summary,
            performanceView=brief.performance_view,
            covenantView=brief.covenant_view,
            liquidityView=brief.liquidity_view,
            riskReclassificationView=brief.risk_reclassification_view,
            recommendedActions=brief.recommended_actions or [],
            lastGeneratedAt=brief.last_generated_at,
        )
        if brief
        else None
    )

    as_of = max(
        [
            investment.as_of,
            *[row.as_of for row in drifts],
            *[row.as_of for row in covenants],
            *[row.as_of for row in cash_impacts],
            *[row.as_of for row in risks],
            brief.as_of if brief else investment.as_of,
        ],
    )

    return PortfolioInvestmentDetailResponse(
        asOf=as_of,
        dataLatency=investment.data_latency,
        dataQuality=investment.data_quality,
        investmentId=investment.id,
        investmentName=investment.investment_name,
        managerName=investment.manager_name,
        lifecycleStatus=investment.lifecycle_status,
        sourceContainer=investment.source_container,
        sourceFolder=investment.source_folder,
        profile={
            "strategyType": investment.strategy_type,
            "targetReturn": investment.target_return,
            "committedCapitalUsd": float(investment.committed_capital_usd) if investment.committed_capital_usd is not None else None,
            "deployedCapitalUsd": float(investment.deployed_capital_usd) if investment.deployed_capital_usd is not None else None,
            "currentNavUsd": float(investment.current_nav_usd) if investment.current_nav_usd is not None else None,
            "lastMonitoringAt": investment.last_monitoring_at,
            "transitionLog": investment.transition_log or [],
        },
        drifts=drift_out,
        covenants=covenant_out,
        cashImpacts=cash_out,
        risks=risk_out,
        boardBrief=brief_out,
    )


@router.get("/portfolio/alerts", response_model=PortfolioAlertsResponse)
def list_portfolio_alerts(
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> PortfolioAlertsResponse:
    drift_rows = list(
        db.execute(
            select(PerformanceDriftFlag)
            .where(PerformanceDriftFlag.fund_id == fund_id, PerformanceDriftFlag.status == "OPEN")
            .order_by(PerformanceDriftFlag.created_at.desc())
            .limit(200),
        ).scalars().all(),
    )
    covenant_rows = list(
        db.execute(
            select(CovenantStatusRegister)
            .where(CovenantStatusRegister.fund_id == fund_id, CovenantStatusRegister.status.in_(["BREACH", "WARNING", "NOT_TESTED", "NOT_CONFIGURED"]))
            .order_by(CovenantStatusRegister.created_at.desc())
            .limit(200),
        ).scalars().all(),
    )
    cash_rows = list(
        db.execute(
            select(CashImpactFlag)
            .where(CashImpactFlag.fund_id == fund_id, CashImpactFlag.resolved_flag.is_(False))
            .order_by(CashImpactFlag.created_at.desc())
            .limit(200),
        ).scalars().all(),
    )
    risk_rows = list(
        db.execute(
            select(InvestmentRiskRegistry)
            .where(InvestmentRiskRegistry.fund_id == fund_id, InvestmentRiskRegistry.risk_type == "OVERALL", InvestmentRiskRegistry.risk_level.in_(["HIGH", "MEDIUM"]))
            .order_by(InvestmentRiskRegistry.created_at.desc())
            .limit(200),
        ).scalars().all(),
    )

    referenced_inv_ids: set[uuid.UUID] = set()
    for row in drift_rows:
        referenced_inv_ids.add(row.investment_id)
    for row in covenant_rows:
        if row.investment_id:
            referenced_inv_ids.add(row.investment_id)
    for row in cash_rows:
        referenced_inv_ids.add(row.investment_id)
    for row in risk_rows:
        referenced_inv_ids.add(row.investment_id)

    investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.id.in_(referenced_inv_ids))).scalars().all()) if referenced_inv_ids else []
    by_id = {row.id: row for row in investments}

    items: list[PortfolioAlertOut] = []
    for row in drift_rows:
        inv = by_id.get(row.investment_id)
        if inv is None:
            continue
        items.append(
            PortfolioAlertOut(
                alertType="PERFORMANCE_DRIFT",
                severity=row.severity,
                investmentId=inv.id,
                investmentName=inv.investment_name,
                message=row.reasoning,
                createdAt=row.created_at,
            ),
        )
    for row in covenant_rows:
        inv = by_id.get(row.investment_id)
        if inv is None:
            continue
        items.append(
            PortfolioAlertOut(
                alertType="COVENANT_SURVEILLANCE",
                severity=row.severity,
                investmentId=inv.id,
                investmentName=inv.investment_name,
                message=row.details or f"Covenant status {row.status} for {row.covenant_name}.",
                createdAt=row.created_at,
            ),
        )
    for row in cash_rows:
        inv = by_id.get(row.investment_id)
        if inv is None:
            continue
        items.append(
            PortfolioAlertOut(
                alertType="CASH_IMPACT",
                severity=row.severity,
                investmentId=inv.id,
                investmentName=inv.investment_name,
                message=row.message,
                createdAt=row.created_at,
            ),
        )
    for row in risk_rows:
        inv = by_id.get(row.investment_id)
        if inv is None:
            continue
        items.append(
            PortfolioAlertOut(
                alertType="RISK_RECLASSIFICATION",
                severity=row.risk_level,
                investmentId=inv.id,
                investmentName=inv.investment_name,
                message=row.rationale,
                createdAt=row.created_at,
            ),
        )

    items.sort(key=lambda i: i.createdAt, reverse=True)
    items = items[:300]

    as_of = max((item.createdAt for item in items), default=_utcnow())
    return PortfolioAlertsResponse(asOf=as_of, dataLatency=None, dataQuality="OK", items=items)


@router.post("/portfolio/investments/{investment_id}/review", response_model=PortfolioReviewResponse)
def trigger_portfolio_review(
    fund_id: uuid.UUID,
    investment_id: uuid.UUID,
    body: DeepReviewRequest | None = None,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
) -> PortfolioReviewResponse:
    """Run AI periodic review for a single active investment."""
    actor = body.actor_id if body else "ai-engine"
    result = run_portfolio_review(db, fund_id=fund_id, investment_id=investment_id, actor_id=actor)
    return PortfolioReviewResponse(**result)


@router.post("/portfolio/deep-review", response_model=PortfolioBatchReviewResponse)
def trigger_portfolio_batch_review(
    fund_id: uuid.UUID,
    body: DeepReviewRequest | None = None,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
) -> PortfolioBatchReviewResponse:
    """Run AI periodic review for ALL active investments."""
    actor = body.actor_id if body else "ai-engine"
    result = run_all_portfolio_reviews(db, fund_id=fund_id, actor_id=actor)
    return PortfolioBatchReviewResponse(**result)


@router.get("/portfolio/investments/{investment_id}/reviews", response_model=PeriodicReviewsListResponse)
def list_investment_reviews(
    fund_id: uuid.UUID,
    investment_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> PeriodicReviewsListResponse:
    """List all periodic reviews for an investment, newest first."""
    rows = list(
        db.execute(
            select(PeriodicReviewReport)
            .where(
                PeriodicReviewReport.fund_id == fund_id,
                PeriodicReviewReport.investment_id == investment_id,
            )
            .order_by(PeriodicReviewReport.reviewed_at.desc())
            .limit(50),
        )
        .scalars()
        .all(),
    )
    as_of = rows[0].reviewed_at if rows else _utcnow()
    items = [PeriodicReviewOut.model_validate(r) for r in rows]
    return PeriodicReviewsListResponse(asOf=as_of, dataLatency=None, dataQuality="OK", items=items)


@router.get("/portfolio/investments/{investment_id}/reviews/latest", response_model=PeriodicReviewResponse)
def get_latest_investment_review(
    fund_id: uuid.UUID,
    investment_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> PeriodicReviewResponse:
    """Retrieve the latest periodic review for an investment."""
    row = db.execute(
        select(PeriodicReviewReport)
        .where(
            PeriodicReviewReport.fund_id == fund_id,
            PeriodicReviewReport.investment_id == investment_id,
        )
        .order_by(PeriodicReviewReport.reviewed_at.desc())
        .limit(1),
    ).scalar_one_or_none()

    return PeriodicReviewResponse(
        asOf=row.reviewed_at if row else _utcnow(),
        dataLatency=None,
        dataQuality="OK",
        item=PeriodicReviewOut.model_validate(row) if row else None,
    )


@router.get(
    "/portfolio/investments/{investment_id}/monitoring",
    response_model=PortfolioDealMonitoringResponse,
)
def get_portfolio_deal_monitoring(
    fund_id: uuid.UUID,
    investment_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> PortfolioDealMonitoringResponse:
    """Full portfolio deal monitoring record (capital-at-risk)."""

    investment = db.execute(
        select(ActiveInvestment).where(
            ActiveInvestment.fund_id == fund_id,
            ActiveInvestment.id == investment_id,
        ),
    ).scalar_one_or_none()
    if investment is None:
        raise HTTPException(status_code=404, detail="Active investment not found")

    portfolio_deal = None
    portfolio_deal_id = None
    monitoring_output: dict | None = None

    if investment.deal_id:
        portfolio_deal = db.execute(
            select(PortfolioDeal).where(PortfolioDeal.id == investment.deal_id),
        ).scalar_one_or_none()
        if portfolio_deal:
            portfolio_deal_id = portfolio_deal.id
            monitoring_output = portfolio_deal.monitoring_output

    cf_summary = CashflowSummary()
    cf_events: list[CashflowEventItem] = []

    if portfolio_deal_id:
        try:
            metrics = cf_svc.calculate_portfolio_monitoring_metrics(
                db, fund_id=fund_id, deal_id=portfolio_deal_id,
            )
            cf_summary = CashflowSummary(
                totalContributions=metrics["total_contributions"],
                totalDistributions=metrics["total_distributions"],
                interestReceived=metrics["interest_received"],
                principalReturned=metrics["principal_returned"],
                netCashPosition=metrics["net_cash_position"],
                cashToCashMultiple=metrics["cash_to_cash_multiple"],
                irrEstimate=metrics["irr_estimate"],
            )
            cf_events = [CashflowEventItem(**e) for e in metrics["cashflow_events"]]
        except Exception:
            pass

    cov_rows = list(
        db.execute(
            select(CovenantStatusRegister)
            .where(
                CovenantStatusRegister.fund_id == fund_id,
                CovenantStatusRegister.investment_id == investment_id,
            )
            .order_by(CovenantStatusRegister.created_at.desc()),
        ).scalars().all(),
    )
    covenant_items = [
        CovenantMonitoringItem(
            covenantName=c.covenant_name,
            status=c.status,
            severity=c.severity,
            details=c.details,
            lastTestedAt=c.last_tested_at,
            nextTestDueAt=c.next_test_due_at,
        )
        for c in cov_rows
    ]

    risk_rows = list(
        db.execute(
            select(InvestmentRiskRegistry)
            .where(
                InvestmentRiskRegistry.fund_id == fund_id,
                InvestmentRiskRegistry.investment_id == investment_id,
            )
            .order_by(InvestmentRiskRegistry.created_at.desc()),
        ).scalars().all(),
    )
    risk_items = [
        RiskMonitoringItem(
            riskType=r.risk_type,
            riskLevel=r.risk_level,
            trend=r.trend,
            rationale=r.rationale,
        )
        for r in risk_rows
    ]

    brief = db.execute(
        select(BoardMonitoringBrief).where(
            BoardMonitoringBrief.fund_id == fund_id,
            BoardMonitoringBrief.investment_id == investment_id,
        ),
    ).scalar_one_or_none()
    brief_out = (
        PortfolioBriefOut(
            executiveSummary=brief.executive_summary,
            performanceView=brief.performance_view,
            covenantView=brief.covenant_view,
            liquidityView=brief.liquidity_view,
            riskReclassificationView=brief.risk_reclassification_view,
            recommendedActions=brief.recommended_actions or [],
            lastGeneratedAt=brief.last_generated_at,
        )
        if brief else None
    )

    latest_review_row = db.execute(
        select(PeriodicReviewReport)
        .where(
            PeriodicReviewReport.fund_id == fund_id,
            PeriodicReviewReport.investment_id == investment_id,
        )
        .order_by(PeriodicReviewReport.reviewed_at.desc())
        .limit(1),
    ).scalar_one_or_none()
    latest_review_out = (
        PeriodicReviewOut.model_validate(latest_review_row)
        if latest_review_row else None
    )

    ai_summary = None
    if monitoring_output and isinstance(monitoring_output, dict):
        ai_summary = monitoring_output.get("ai_monitoring_summary")

    as_of_candidates = [investment.as_of]
    if brief:
        as_of_candidates.append(brief.as_of)
    if latest_review_row:
        as_of_candidates.append(latest_review_row.reviewed_at)

    return PortfolioDealMonitoringResponse(
        asOf=max(as_of_candidates),
        dataLatency=investment.data_latency,
        dataQuality=investment.data_quality,
        investmentId=investment.id,
        dealId=portfolio_deal_id,
        dealName=investment.investment_name,
        sponsorName=investment.manager_name,
        jurisdiction=monitoring_output.get("deal_overview", {}).get("jurisdiction") if monitoring_output else None,
        instrument=monitoring_output.get("deal_overview", {}).get("instrument") if monitoring_output else None,
        status=investment.lifecycle_status or "ACTIVE",
        commitment=float(investment.committed_capital_usd) if investment.committed_capital_usd else None,
        deployedCapital=float(investment.deployed_capital_usd) if investment.deployed_capital_usd else None,
        currentNav=float(investment.current_nav_usd) if investment.current_nav_usd else None,
        strategyType=investment.strategy_type,
        targetReturn=investment.target_return,
        cashflowSummary=cf_summary,
        cashflowEvents=cf_events,
        covenantMonitoring=covenant_items,
        riskMonitoring=risk_items,
        monitoringOutput=monitoring_output,
        aiMonitoringSummary=ai_summary,
        boardBrief=brief_out,
        latestReview=latest_review_out,
        lastReviewedAt=investment.last_monitoring_at,
    )


@router.get(
    "/portfolio/investments/{investment_id}/review-pdf",
    response_model=PeriodicReviewPdfResponse,
)
async def get_periodic_review_pdf(
    fund_id: uuid.UUID,
    investment_id: uuid.UUID,
    review_id: uuid.UUID | None = Query(default=None, description="Optional specific review ID; defaults to latest"),
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> PeriodicReviewPdfResponse:
    """Generate and return a signed URL for the Periodic Review PDF."""
    import os
    import tempfile

    from ai_engine.pdf.generate_periodic_review_pdf import _load_review_data, generate_pdf
    from ai_engine.pipeline.storage_routing import gold_portfolio_review_path
    from app.services.storage_client import get_storage_client

    storage = get_storage_client()

    investment = db.execute(
        select(ActiveInvestment).where(
            ActiveInvestment.fund_id == fund_id,
            ActiveInvestment.id == investment_id,
        ),
    ).scalar_one_or_none()
    if investment is None:
        raise HTTPException(status_code=404, detail="Active investment not found")

    if review_id:
        review_row = db.execute(
            select(PeriodicReviewReport).where(
                PeriodicReviewReport.id == review_id,
                PeriodicReviewReport.investment_id == investment_id,
                PeriodicReviewReport.fund_id == fund_id,
            ),
        ).scalar_one_or_none()
    else:
        review_row = db.execute(
            select(PeriodicReviewReport)
            .where(
                PeriodicReviewReport.fund_id == fund_id,
                PeriodicReviewReport.investment_id == investment_id,
            )
            .order_by(PeriodicReviewReport.reviewed_at.desc())
            .limit(1),
        ).scalar_one_or_none()

    if not review_row:
        raise HTTPException(status_code=404, detail="No periodic review found for this investment.")

    reviewed_at = review_row.reviewed_at
    model_version = review_row.model_version or "unknown"

    version_tag = f"review-{reviewed_at.isoformat()}"
    filename = f"{version_tag}.pdf"
    path = gold_portfolio_review_path(
        org_id=actor.organization_id,
        investment_id=str(investment_id),
        filename=filename,
    )

    if not await storage.exists(path):
        data = _load_review_data(
            investment_id=str(investment_id),
            review_id=str(review_row.id),
        )

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            generate_pdf(data, output_path=tmp_path)
            with open(tmp_path, "rb") as f:
                pdf_bytes = f.read()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        await storage.write(path, pdf_bytes, content_type="application/pdf")

    signed_url = await storage.generate_read_url(path)

    return PeriodicReviewPdfResponse(
        signedPdfUrl=signed_url,
        versionTag=version_tag,
        reviewedAt=reviewed_at,
        modelVersion=model_version,
    )
