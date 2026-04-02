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
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import route_cache
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.schemas.sec_funds import (
    AnnualReturnItem,
    AvgAnnualReturns,
    FundDataAvailabilitySchema,
    FundDetailResponse,
    FundFirmInfo,
    FundStyleInfo,
    FundTeamMember,
    HoldingsHistoryResponse,
    InstitutionalHolderItem,
    NportHoldingItem,
    NportHoldingsPage,
    PeerAnalysisResponse,
    PeerAnalysisTarget,
    PeerFundItem,
    PrivateFundListResponse,
    PrivateFundSummary,
    ProspectusDataResponse,
    ProspectusExpenseExamples,
    ProspectusFees,
    ReverseHoldingsResponse,
    StyleHistoryResponse,
    StyleSnapshotItem,
    TopHoldingItem,
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
    series_id: str | None = Query(None, description="Series ID to filter umbrella CIKs"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> NportHoldingsPage:
    _require_investment_role(actor)
    if not _CIK_RE.match(cik):
        raise HTTPException(status_code=400, detail="Invalid CIK number")

    # Build optional series_id clause for umbrella CIKs
    sid_clause = "AND series_id = :series_id" if series_id else ""
    params: dict[str, Any] = {"cik": cik}
    if series_id:
        params["series_id"] = series_id

    # Get available quarters
    q_result = await db.execute(
        text(f"""
            SELECT DISTINCT report_date
            FROM sec_nport_holdings
            WHERE cik = :cik {sid_clause}
            ORDER BY report_date DESC
        """),
        params,
    )
    available_quarters = [r[0] for r in q_result.fetchall()]

    if not available_quarters:
        return NportHoldingsPage()

    target_quarter = quarter or available_quarters[0]
    q_params = {**params, "quarter": target_quarter}

    # Holdings for target quarter
    result = await db.execute(
        text(f"""
            SELECT cusip, isin, issuer_name, asset_class, sector,
                   market_value, quantity, pct_of_nav, currency, fair_value_level
            FROM sec_nport_holdings
            WHERE cik = :cik AND report_date = :quarter {sid_clause}
            ORDER BY market_value DESC NULLS LAST
            LIMIT :lim OFFSET :off
        """),
        {**q_params, "lim": limit, "off": offset},
    )
    rows = result.fetchall()

    # Total count + value
    agg = await db.execute(
        text(f"""
            SELECT COUNT(*), COALESCE(SUM(market_value), 0)
            FROM sec_nport_holdings
            WHERE cik = :cik AND report_date = :quarter {sid_clause}
        """),
        q_params,
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


# ═══════════════════════════════════════════════════════════════════════════
#  GET /sec/funds/{cik}/holdings-history
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/funds/{cik}/holdings-history",
    response_model=HoldingsHistoryResponse,
    summary="Holdings sector evolution over time (all available quarters)",
)
@route_cache(ttl=600, global_key=True, key_prefix="sec:holdings_hist")
async def get_holdings_history(
    cik: str = Path(...),
    series_id: str | None = Query(None, description="Series ID to filter umbrella CIKs"),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> HoldingsHistoryResponse:
    _require_investment_role(actor)
    if not _CIK_RE.match(cik):
        raise HTTPException(status_code=400, detail="Invalid CIK number")

    sid_clause = "AND series_id = :series_id" if series_id else ""
    params: dict[str, Any] = {"cik": cik}
    if series_id:
        params["series_id"] = series_id

    result = await db.execute(
        text(f"""
            SELECT
                report_date,
                sector,
                SUM(pct_of_nav) AS sector_pct_nav
            FROM sec_nport_holdings
            WHERE cik = :cik
              AND sector IS NOT NULL
              AND pct_of_nav IS NOT NULL
              {sid_clause}
            GROUP BY report_date, sector
            ORDER BY report_date ASC, sector_pct_nav DESC
        """),
        params,
    )
    rows = result.fetchall()

    from collections import defaultdict

    quarter_sector: dict[str, dict[str, float]] = defaultdict(dict)
    for report_date, sector, sector_pct in rows:
        q = str(report_date)
        quarter_sector[q][sector] = round(float(sector_pct), 4)

    quarters = sorted(quarter_sector.keys())

    all_sectors: set[str] = set()
    for s in quarter_sector.values():
        all_sectors.update(s.keys())

    sector_series: dict[str, list[float | None]] = {}
    for sector in sorted(all_sectors):
        sector_series[sector] = [
            quarter_sector[q].get(sector)
            for q in quarters
        ]

    # Top 20 holdings in latest quarter
    top_result = await db.execute(
        text("""
            SELECT issuer_name, sector, pct_of_nav, cusip, market_value
            FROM sec_nport_holdings
            WHERE cik = :cik
              AND report_date = (
                  SELECT MAX(report_date) FROM sec_nport_holdings WHERE cik = :cik
              )
            ORDER BY market_value DESC NULLS LAST
            LIMIT 20
        """),
        {"cik": cik},
    )
    top = top_result.fetchall()

    return HoldingsHistoryResponse(
        quarters=quarters,
        sector_series=sector_series,
        top_holdings_latest=[
            TopHoldingItem(
                issuer_name=r[0],
                sector=r[1],
                pct_of_nav=round(float(r[2]), 4) if r[2] else None,
                cusip=r[3],
                market_value=r[4],
            )
            for r in top
        ],
        quarters_available=len(quarters),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /sec/funds/{cik}/peer-analysis
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/funds/{cik}/peer-analysis",
    response_model=PeerAnalysisResponse,
    summary="Peer comparison using prospectus stats + style classification",
)
@route_cache(ttl=600, global_key=True, key_prefix="sec:peer_analysis")
async def get_peer_analysis(
    cik: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> PeerAnalysisResponse:
    _require_investment_role(actor)
    if not _CIK_RE.match(cik):
        raise HTTPException(status_code=400, detail="Invalid CIK number")

    # 1. Get fund's style label + fund_type
    fund_result = await db.execute(
        text("""
            SELECT
                rf.fund_name, rf.fund_type, rf.cik,
                sfs.style_label
            FROM sec_registered_funds rf
            LEFT JOIN LATERAL (
                SELECT style_label
                FROM sec_fund_style_snapshots
                WHERE cik = rf.cik
                ORDER BY report_date DESC LIMIT 1
            ) sfs ON true
            WHERE rf.cik = :cik
        """),
        {"cik": cik},
    )
    fund_row = fund_result.fetchone()
    if not fund_row:
        raise HTTPException(status_code=404, detail="Fund not found")

    fund_name, fund_type, _, style_label = fund_row
    peer_group = style_label or fund_type

    # 2. Get target fund's prospectus stats
    target_stats = await db.execute(
        text("""
            SELECT
                ps.expense_ratio_pct, ps.net_expense_ratio_pct,
                ps.avg_annual_return_1y, ps.avg_annual_return_5y,
                ps.avg_annual_return_10y, ps.portfolio_turnover_pct
            FROM sec_fund_classes fc
            JOIN sec_fund_prospectus_stats ps
              ON ps.series_id = fc.series_id
            WHERE fc.cik = :cik
            ORDER BY ps.expense_ratio_pct ASC NULLS LAST
            LIMIT 1
        """),
        {"cik": cik},
    )
    target_row = target_stats.fetchone()

    # 3. Get peers: same style_label, same fund_type
    peers_result = await db.execute(
        text("""
            WITH peer_ciks AS (
                SELECT DISTINCT rf.cik, rf.fund_name, rf.ticker
                FROM sec_registered_funds rf
                JOIN LATERAL (
                    SELECT style_label
                    FROM sec_fund_style_snapshots
                    WHERE cik = rf.cik
                    ORDER BY report_date DESC LIMIT 1
                ) sfs ON sfs.style_label = :style_label
                WHERE rf.fund_type = :fund_type
                  AND rf.aum_below_threshold = FALSE
                  AND rf.cik != :cik
                LIMIT 200
            )
            SELECT
                pc.cik, pc.fund_name, pc.ticker,
                ps.expense_ratio_pct,
                ps.avg_annual_return_1y,
                ps.avg_annual_return_5y,
                ps.avg_annual_return_10y
            FROM peer_ciks pc
            JOIN sec_fund_classes fc ON fc.cik = pc.cik
            JOIN sec_fund_prospectus_stats ps ON ps.series_id = fc.series_id
            ORDER BY ps.expense_ratio_pct ASC NULLS LAST
        """),
        {"cik": cik, "style_label": style_label, "fund_type": fund_type},
    )
    peer_rows = peers_result.fetchall()

    def _percentile_rank(
        value: float | None,
        all_vals: list[float],
        higher_is_better: bool,
    ) -> int | None:
        if value is None or not all_vals:
            return None
        n = len(all_vals)
        rank = sum(1 for v in all_vals if v < value) / n
        return int((1 - rank if not higher_is_better else rank) * 100)

    peer_er = [float(r[3]) for r in peer_rows if r[3] is not None]
    peer_1y = [float(r[4]) for r in peer_rows if r[4] is not None]
    peer_5y = [float(r[5]) for r in peer_rows if r[5] is not None]
    peer_10y = [float(r[6]) for r in peer_rows if r[6] is not None]

    target_er = float(target_row[0]) if target_row and target_row[0] else None
    target_1y = float(target_row[2]) if target_row and target_row[2] else None
    target_5y = float(target_row[3]) if target_row and target_row[3] else None
    target_10y = float(target_row[4]) if target_row and target_row[4] else None

    return PeerAnalysisResponse(
        target=PeerAnalysisTarget(
            cik=cik,
            fund_name=fund_name,
            style_label=style_label,
            expense_ratio_pct=target_er,
            net_expense_ratio_pct=float(target_row[1]) if target_row and target_row[1] else None,
            avg_annual_return_1y=target_1y,
            avg_annual_return_5y=target_5y,
            avg_annual_return_10y=target_10y,
            portfolio_turnover_pct=float(target_row[5]) if target_row and target_row[5] else None,
        ),
        peers=[
            PeerFundItem(
                cik=r[0],
                fund_name=r[1],
                ticker=r[2],
                expense_ratio_pct=float(r[3]) if r[3] else None,
                avg_annual_return_1y=float(r[4]) if r[4] else None,
                avg_annual_return_5y=float(r[5]) if r[5] else None,
                avg_annual_return_10y=float(r[6]) if r[6] else None,
            )
            for r in peer_rows[:50]
        ],
        peer_count=len(peer_rows),
        peer_group=peer_group,
        percentiles={
            "expense_ratio_pct": _percentile_rank(target_er, peer_er, higher_is_better=False),
            "avg_annual_return_1y": _percentile_rank(target_1y, peer_1y, higher_is_better=True),
            "avg_annual_return_5y": _percentile_rank(target_5y, peer_5y, higher_is_better=True),
            "avg_annual_return_10y": _percentile_rank(target_10y, peer_10y, higher_is_better=True),
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /sec/funds/{cik}/reverse-holdings
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/funds/{cik}/reverse-holdings",
    response_model=ReverseHoldingsResponse,
    summary="Institutional holders of this fund (reverse 13F lookup)",
)
@route_cache(ttl=600, global_key=True, key_prefix="sec:reverse_hold")
async def get_reverse_holdings(
    cik: str = Path(...),
    limit: int = Query(25, ge=5, le=100),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ReverseHoldingsResponse:
    _require_investment_role(actor)
    if not _CIK_RE.match(cik):
        raise HTTPException(status_code=400, detail="Invalid CIK number")

    # Resolve CUSIP via fund_classes → cusip_ticker_map
    cusip_result = await db.execute(
        text("""
            SELECT ctm.cusip, ctm.ticker
            FROM sec_fund_classes fc
            JOIN sec_cusip_ticker_map ctm ON ctm.ticker = fc.ticker
            WHERE fc.cik = :cik AND ctm.cusip IS NOT NULL
            LIMIT 1
        """),
        {"cik": cik},
    )
    cusip_row = cusip_result.fetchone()

    if not cusip_row:
        # Fallback: registered fund ticker → cusip map
        cusip_result2 = await db.execute(
            text("""
                SELECT ctm.cusip, rf.ticker
                FROM sec_registered_funds rf
                JOIN sec_cusip_ticker_map ctm ON ctm.ticker = rf.ticker
                WHERE rf.cik = :cik AND ctm.cusip IS NOT NULL
                LIMIT 1
            """),
            {"cik": cik},
        )
        cusip_row = cusip_result2.fetchone()

    if not cusip_row:
        return ReverseHoldingsResponse(
            note="CUSIP could not be resolved for this fund",
        )

    fund_cusip, fund_ticker = cusip_row[0], cusip_row[1]

    # Query institutional allocations (latest quarter)
    holders_result = await db.execute(
        text("""
            SELECT
                filer_cik, filer_name, filer_type,
                market_value, shares, report_date
            FROM sec_institutional_allocations
            WHERE target_cusip = :cusip
              AND report_date = (
                  SELECT MAX(report_date)
                  FROM sec_institutional_allocations
                  WHERE target_cusip = :cusip
              )
            ORDER BY market_value DESC NULLS LAST
            LIMIT :lim
        """),
        {"cusip": fund_cusip, "lim": limit},
    )
    holders = holders_result.fetchall()

    # Aggregate totals
    agg_result = await db.execute(
        text("""
            SELECT COUNT(DISTINCT filer_cik), COALESCE(SUM(market_value), 0)
            FROM sec_institutional_allocations
            WHERE target_cusip = :cusip
              AND report_date = (
                  SELECT MAX(report_date)
                  FROM sec_institutional_allocations
                  WHERE target_cusip = :cusip
              )
        """),
        {"cusip": fund_cusip},
    )
    agg = agg_result.fetchone()

    return ReverseHoldingsResponse(
        fund_cusip=fund_cusip,
        fund_ticker=fund_ticker,
        holders=[
            InstitutionalHolderItem(
                filer_cik=r[0],
                filer_name=r[1],
                filer_type=r[2],
                market_value=r[3],
                shares=r[4],
                report_date=str(r[5]),
            )
            for r in holders
        ],
        total_holders=agg[0] if agg else 0,
        total_market_value=int(agg[1]) if agg else 0,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /sec/funds/{cik}/prospectus
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/funds/{cik}/prospectus",
    response_model=ProspectusDataResponse,
    summary="Prospectus fee table + annual return history (SEC RR1)",
)
@route_cache(ttl=3600, global_key=True, key_prefix="sec:prospectus")
async def get_fund_prospectus(
    cik: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ProspectusDataResponse:
    _require_investment_role(actor)
    if not _CIK_RE.match(cik):
        raise HTTPException(status_code=400, detail="Invalid CIK number")

    from app.core.db.session import sync_session_factory
    from vertical_engines.wealth.dd_report.sec_injection import (
        gather_prospectus_returns,
        gather_prospectus_stats,
    )

    loop = asyncio.get_running_loop()

    def _gather():
        with sync_session_factory() as sync_db:
            stats = gather_prospectus_stats(sync_db, fund_cik=cik)
            returns = gather_prospectus_returns(sync_db, fund_cik=cik, years_back=15)
            return stats, returns

    stats, annual_returns = await loop.run_in_executor(None, _gather)

    if not stats.get("prospectus_stats_available"):
        raise HTTPException(
            status_code=404,
            detail="Prospectus data not available for this fund",
        )

    return ProspectusDataResponse(
        series_id=stats.get("series_id"),
        filing_date=stats.get("filing_date"),
        fees=ProspectusFees(
            expense_ratio_pct=stats.get("expense_ratio_pct"),
            net_expense_ratio_pct=stats.get("net_expense_ratio_pct"),
            management_fee_pct=stats.get("management_fee_pct"),
            fee_waiver_pct=stats.get("fee_waiver_pct"),
            distribution_12b1_pct=stats.get("distribution_12b1_pct"),
            portfolio_turnover_pct=stats.get("portfolio_turnover_pct"),
            expense_examples=ProspectusExpenseExamples(**{
                "1y": stats.get("expense_example_1y"),
                "3y": stats.get("expense_example_3y"),
                "5y": stats.get("expense_example_5y"),
                "10y": stats.get("expense_example_10y"),
            }),
        ),
        annual_returns=[
            AnnualReturnItem(
                year=r.get("year", 0),
                annual_return_pct=r.get("annual_return_pct"),
            )
            for r in annual_returns
        ],
        avg_annual_returns=AvgAnnualReturns(**{
            "1y": stats.get("avg_annual_return_1y"),
            "5y": stats.get("avg_annual_return_5y"),
            "10y": stats.get("avg_annual_return_10y"),
        }),
    )
