"""SEC Fund endpoints — registered fund catalog, detail, holdings, style.

GET  /sec/managers/{crd}/registered-funds  — mutual/ETF funds for an adviser
GET  /sec/managers/{crd}/private-funds     — Schedule D private funds
GET  /sec/funds/{cik}                      — fund detail (fact sheet)
GET  /sec/funds/{cik}/holdings             — N-PORT holdings by quarter
GET  /sec/funds/{cik}/style-history        — style classification history

All queries hit global SEC tables (no RLS, no organization_id).
"""

from __future__ import annotations

import asyncio
import re
from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import route_cache
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.schemas.sec_funds import (
    FundDataAvailabilitySchema,
    FundDetailResponse,
    FundFirmInfo,
    FundStyleInfo,
    FundTeamMember,
    NportHoldingItem,
    NportHoldingsPage,
    PrivateFundListResponse,
    PrivateFundSummary,
    RegisteredFundListResponse,
    RegisteredFundSummary,
    StyleHistoryResponse,
    StyleSnapshotItem,
)
from app.shared.enums import Role
from app.shared.models import (
    SecFundStyleSnapshot,
    SecManager,
    SecManagerFund,
    SecManagerTeam,
    SecRegisteredFund,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/sec", tags=["sec-funds"])

_CRD_RE = re.compile(r"^\d{1,10}$")
_CIK_RE = re.compile(r"^\d{1,10}$")


def _require_investment_role(actor: Actor) -> None:
    if not actor.has_role(Role.INVESTMENT_TEAM) and not actor.has_role(Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Team or Admin role required",
        )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /sec/managers/{crd}/registered-funds
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{crd}/registered-funds",
    response_model=RegisteredFundListResponse,
    summary="Registered funds (mutual/ETF) for an adviser",
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:reg_funds")
async def get_registered_funds(
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> RegisteredFundListResponse:
    _require_investment_role(actor)
    if not _CRD_RE.match(crd):
        raise HTTPException(status_code=400, detail="Invalid CRD number")

    # Main query with latest style via lateral join
    result = await db.execute(
        text("""
            SELECT rf.cik, rf.fund_name, rf.fund_type, rf.ticker,
                   rf.total_assets, rf.last_nport_date,
                   sfs.style_label, sfs.confidence
            FROM sec_registered_funds rf
            LEFT JOIN LATERAL (
                SELECT style_label, confidence
                FROM sec_fund_style_snapshots
                WHERE cik = rf.cik
                ORDER BY report_date DESC
                LIMIT 1
            ) sfs ON true
            WHERE rf.crd_number = :crd
              AND rf.aum_below_threshold = FALSE
            ORDER BY rf.total_assets DESC NULLS LAST
        """),
        {"crd": crd},
    )
    rows = result.fetchall()

    funds = [
        RegisteredFundSummary(
            cik=r[0],
            fund_name=r[1],
            fund_type=r[2],
            ticker=r[3],
            total_assets=r[4],
            last_nport_date=r[5],
            style_label=r[6],
            style_confidence=float(r[7]) if r[7] is not None else None,
        )
        for r in rows
    ]

    return RegisteredFundListResponse(funds=funds, total=len(funds))


# ═══════════════════════════════════════════════════════════════════════════
#  GET /sec/managers/{crd}/private-funds
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{crd}/private-funds",
    response_model=PrivateFundListResponse,
    summary="Private funds (Schedule D) for an adviser",
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:priv_funds")
async def get_private_funds(
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> PrivateFundListResponse:
    _require_investment_role(actor)
    if not _CRD_RE.match(crd):
        raise HTTPException(status_code=400, detail="Invalid CRD number")

    result = await db.execute(
        select(
            SecManagerFund.fund_name,
            SecManagerFund.fund_type,
            SecManagerFund.gross_asset_value,
            SecManagerFund.investor_count,
            SecManagerFund.is_fund_of_funds,
        )
        .where(SecManagerFund.crd_number == crd)
        .order_by(SecManagerFund.gross_asset_value.desc().nullslast()),
    )
    rows = result.all()

    funds = [
        PrivateFundSummary(
            fund_name=r[0],
            fund_type=r[1],
            gross_asset_value=r[2],
            investor_count=r[3],
            is_fund_of_funds=r[4],
        )
        for r in rows
    ]

    # Fallback: if no Schedule D records, derive from aggregated counts
    if not funds:
        mgr = await db.execute(
            select(SecManager).where(SecManager.crd_number == crd),
        )
        manager = mgr.scalars().first()
        if manager and manager.private_fund_count and manager.private_fund_count > 0:
            type_map = [
                ("Hedge Fund", manager.hedge_fund_count),
                ("Private Equity", manager.pe_fund_count),
                ("Venture Capital", manager.vc_fund_count),
                ("Real Estate", manager.real_estate_fund_count),
                ("Securitized Asset", manager.securitized_fund_count),
                ("Liquidity", manager.liquidity_fund_count),
                ("Other", manager.other_fund_count),
            ]
            funds = [
                PrivateFundSummary(
                    fund_name=f"{ft} ({count} fund{'s' if count > 1 else ''})",
                    fund_type=ft,
                    gross_asset_value=None,
                    investor_count=None,
                    is_fund_of_funds=None,
                )
                for ft, count in type_map
                if count and count > 0
            ]

    return PrivateFundListResponse(funds=funds, total=len(funds))


# ═══════════════════════════════════════════════════════════════════════════
#  GET /sec/funds/{cik}
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/funds/{cik}",
    response_model=FundDetailResponse,
    summary="Fund detail for fact sheet",
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:fund_detail")
async def get_fund_detail(
    cik: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> FundDetailResponse:
    _require_investment_role(actor)
    if not _CIK_RE.match(cik):
        raise HTTPException(status_code=400, detail="Invalid CIK number")

    # 1. Load fund record
    fund_result = await db.execute(
        select(SecRegisteredFund).where(SecRegisteredFund.cik == cik),
    )
    fund = fund_result.scalars().first()
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    # 2. Parallel queries for related data
    from data_providers.sec.adv_service import compute_fund_data_availability

    style_q = db.execute(
        select(SecFundStyleSnapshot)
        .where(SecFundStyleSnapshot.cik == cik)
        .order_by(SecFundStyleSnapshot.report_date.desc())
        .limit(1),
    )
    avail_q = compute_fund_data_availability(cik, "registered", db)

    # Manager + team (only if crd_number linked)
    manager_q = None
    team_q = None
    if fund.crd_number:
        manager_q = db.execute(
            select(SecManager).where(SecManager.crd_number == fund.crd_number),
        )
        team_q = db.execute(
            select(SecManagerTeam).where(SecManagerTeam.crd_number == fund.crd_number),
        )

    # Await in parallel
    tasks = [style_q, avail_q]
    if manager_q:
        tasks.append(manager_q)
    if team_q:
        tasks.append(team_q)

    results = await asyncio.gather(*tasks)

    style_result = results[0]
    avail = results[1]
    manager = None
    team_rows = []
    if manager_q:
        manager = results[2].scalars().first()
    if team_q:
        team_rows = results[3].scalars().all()

    # Build style info
    style_row = style_result.scalars().first()
    latest_style = None
    if style_row:
        latest_style = FundStyleInfo(
            style_label=style_row.style_label,
            growth_tilt=style_row.growth_tilt,
            sector_weights=style_row.sector_weights or {},
            equity_pct=style_row.equity_pct,
            fixed_income_pct=style_row.fixed_income_pct,
            cash_pct=style_row.cash_pct,
            confidence=style_row.confidence,
            report_date=style_row.report_date,
        )

    # Build firm info
    firm = None
    if manager:
        firm = FundFirmInfo(
            crd_number=manager.crd_number,
            firm_name=manager.firm_name,
            aum_total=manager.aum_total,
            compliance_disclosures=manager.compliance_disclosures,
            state=manager.state,
            website=manager.website,
        )

    # Build team
    team = [
        FundTeamMember(
            person_name=t.person_name,
            title=t.title,
            role=t.role,
            years_experience=t.years_experience,
            certifications=t.certifications or [],
        )
        for t in team_rows
    ]

    return FundDetailResponse(
        cik=fund.cik,
        fund_name=fund.fund_name,
        fund_type=fund.fund_type,
        ticker=fund.ticker,
        isin=fund.isin,
        total_assets=fund.total_assets,
        total_shareholder_accounts=fund.total_shareholder_accounts,
        inception_date=fund.inception_date,
        currency=fund.currency,
        domicile=fund.domicile,
        last_nport_date=fund.last_nport_date,
        firm=firm,
        team=team,
        latest_style=latest_style,
        data_availability=FundDataAvailabilitySchema(
            fund_universe=avail.fund_universe,
            has_holdings=avail.has_holdings,
            has_nav_history=avail.has_nav_history,
            has_style_analysis=avail.has_style_analysis,
            has_portfolio_manager=avail.has_portfolio_manager,
            has_peer_analysis=avail.has_peer_analysis,
            disclosure_note=avail.disclosure_note,
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /sec/funds/{cik}/holdings
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/funds/{cik}/holdings",
    response_model=NportHoldingsPage,
    summary="N-PORT holdings by quarter",
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:nport_holdings")
async def get_fund_holdings(
    cik: str = Path(...),
    quarter: date | None = Query(None, description="Quarter date (default: latest)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> NportHoldingsPage:
    _require_investment_role(actor)
    if not _CIK_RE.match(cik):
        raise HTTPException(status_code=400, detail="Invalid CIK number")

    # Get available quarters
    q_result = await db.execute(
        text("""
            SELECT DISTINCT report_date
            FROM sec_nport_holdings
            WHERE cik = :cik
            ORDER BY report_date DESC
        """),
        {"cik": cik},
    )
    available_quarters = [r[0] for r in q_result.fetchall()]

    if not available_quarters:
        return NportHoldingsPage()

    target_quarter = quarter or available_quarters[0]

    # Holdings for target quarter
    result = await db.execute(
        text("""
            SELECT cusip, isin, issuer_name, asset_class, sector,
                   market_value, quantity, pct_of_nav, currency, fair_value_level
            FROM sec_nport_holdings
            WHERE cik = :cik AND report_date = :quarter
            ORDER BY market_value DESC NULLS LAST
            LIMIT :lim OFFSET :off
        """),
        {"cik": cik, "quarter": target_quarter, "lim": limit, "off": offset},
    )
    rows = result.fetchall()

    # Total count + value
    agg = await db.execute(
        text("""
            SELECT COUNT(*), COALESCE(SUM(market_value), 0)
            FROM sec_nport_holdings
            WHERE cik = :cik AND report_date = :quarter
        """),
        {"cik": cik, "quarter": target_quarter},
    )
    agg_row = agg.fetchone()
    total_count = agg_row[0] if agg_row else 0
    total_value = agg_row[1] if agg_row else None

    holdings = [
        NportHoldingItem(
            cusip=r[0],
            isin=r[1],
            issuer_name=r[2],
            asset_class=r[3],
            sector=r[4],
            market_value=r[5],
            quantity=float(r[6]) if r[6] is not None else None,
            pct_of_nav=float(r[7]) if r[7] is not None else None,
            currency=r[8],
            fair_value_level=r[9],
        )
        for r in rows
    ]

    return NportHoldingsPage(
        holdings=holdings,
        available_quarters=available_quarters,
        total_count=total_count,
        total_value=int(total_value) if total_value else None,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /sec/funds/{cik}/style-history
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/funds/{cik}/style-history",
    response_model=StyleHistoryResponse,
    summary="Style classification history with drift detection",
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:style_hist")
async def get_style_history(
    cik: str = Path(...),
    limit: int = Query(8, ge=1, le=40),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> StyleHistoryResponse:
    _require_investment_role(actor)
    if not _CIK_RE.match(cik):
        raise HTTPException(status_code=400, detail="Invalid CIK number")

    result = await db.execute(
        select(SecFundStyleSnapshot)
        .where(SecFundStyleSnapshot.cik == cik)
        .order_by(SecFundStyleSnapshot.report_date.desc())
        .limit(limit),
    )
    rows = result.scalars().all()

    snapshots = [
        StyleSnapshotItem(
            report_date=r.report_date,
            style_label=r.style_label,
            growth_tilt=r.growth_tilt,
            sector_weights=r.sector_weights or {},
            equity_pct=r.equity_pct,
            fixed_income_pct=r.fixed_income_pct,
            cash_pct=r.cash_pct,
            confidence=r.confidence,
        )
        for r in rows
    ]

    drift_detected = False
    if len(snapshots) >= 2:
        drift_detected = snapshots[0].style_label != snapshots[1].style_label

    return StyleHistoryResponse(
        snapshots=snapshots,
        drift_detected=drift_detected,
        quarters_analyzed=len(snapshots),
    )
