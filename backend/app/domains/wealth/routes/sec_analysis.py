"""SEC Analysis API routes — US Fund Analysis page.

CIK-based manager detail, reverse CUSIP lookup, peer comparison,
fund-type breakdown, and holdings history. All queries hit global SEC tables
(no RLS, no organization_id).

GET  /sec/managers/{cik_or_crd}      — manager detail + latest holdings summary
GET  /sec/holdings/reverse           — reverse lookup by CUSIP
GET  /sec/managers/compare           — peer comparison (max 5 CIKs)
GET  /sec/managers/{crd_number}/funds — fund-type breakdown
GET  /sec/holdings/history           — quarterly holdings history
"""

from __future__ import annotations

import re
from datetime import date
from itertools import combinations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import route_cache
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.schemas.sec_analysis import (
    BrochureSection,
    PeerHoldingOverlap,
    ReverseLookupItem,
    SecHoldingsHistory,
    SecHoldingsHistoryPoint,
    SecManagerDetail,
    SecManagerFundBreakdown,
    SecManagerFundItem,
    SecPeerCompare,
    SecReverseLookup,
)
from app.shared.enums import Role
from app.shared.models import (
    Sec13fHolding,
    SecEntityLink,
    SecManager,
    SecManagerBrochureText,
    SecManagerFund,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/sec", tags=["sec-analysis"])

_CIK_RE = re.compile(r"^\d{1,10}$")


def _require_investment_role(actor: Actor) -> None:
    if not actor.has_role(Role.INVESTMENT_TEAM) and not actor.has_role(Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Team or Admin role required",
        )


def _validate_cik(cik: str) -> str:
    if not _CIK_RE.match(cik):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CIK number",
        )
    return cik


def _require_investment_role_dep(actor: Actor = Depends(get_actor)) -> None:
    _require_investment_role(actor)


async def _resolve_ciks(db: AsyncSession, cik: str, *, crd: str | None = None) -> list[str]:
    """Resolve all CIKs for a manager: own CIK + parent 13F filer CIKs via entity links.

    RIAs file ADV with one CIK, but parent holding companies file 13F
    with a different CIK. This resolves both for holdings queries.
    """
    cik_list = [cik]

    # Resolve via CRD if provided, otherwise look up CRD from CIK
    if crd:
        link_stmt = (
            select(SecEntityLink.related_cik)
            .where(SecEntityLink.manager_crd == crd)
            .where(SecEntityLink.relationship == "parent_13f")
        )
    else:
        link_stmt = (
            select(SecEntityLink.related_cik)
            .join(SecManager, SecManager.crd_number == SecEntityLink.manager_crd)
            .where(SecManager.cik == cik)
            .where(SecEntityLink.relationship == "parent_13f")
        )

    link_result = await db.execute(link_stmt)
    linked_ciks = [row[0] for row in link_result.all()]
    cik_list.extend(linked_ciks)
    return cik_list



# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{cik_or_crd} — detail with latest holdings summary
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{cik_or_crd}",
    response_model=SecManagerDetail,
    summary="Manager detail by CIK or CRD",
)
async def get_manager_detail(
    cik_or_crd: str = Path(..., description="SEC CIK or IARD CRD number"),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> SecManagerDetail:
    _require_investment_role(actor)
    identifier = _validate_cik(cik_or_crd)

    # Try CIK first, then fall back to CRD (frontend catalog sends CRD as manager_id)
    stmt = select(SecManager).where(SecManager.cik == identifier)
    result = await db.execute(stmt)
    manager = result.scalar_one_or_none()
    if not manager:
        stmt_crd = select(SecManager).where(SecManager.crd_number == identifier)
        result_crd = await db.execute(stmt_crd)
        manager = result_crd.scalar_one_or_none()
    if not manager:
        raise HTTPException(status_code=404, detail=f"Manager with CIK/CRD {identifier} not found")

    today = date.today()

    # Resolve all CIKs (own + parent 13F filers via entity links)
    resolved_cik = manager.cik or identifier
    cik_list = await _resolve_ciks(db, resolved_cik, crd=manager.crd_number)

    # Latest quarter summary — always filter report_date for chunk pruning
    latest_q_stmt = (
        select(func.max(Sec13fHolding.report_date))
        .where(Sec13fHolding.cik.in_(cik_list))
        .where(Sec13fHolding.report_date <= today)
    )
    lq_result = await db.execute(latest_q_stmt)
    latest_quarter = lq_result.scalar_one_or_none()

    holdings_count = 0
    total_value = None
    if latest_quarter:
        summary_stmt = (
            select(
                func.count().label("cnt"),
                func.sum(Sec13fHolding.market_value).label("total"),
            )
            .where(Sec13fHolding.cik.in_(cik_list))
            .where(Sec13fHolding.report_date == latest_quarter)
        )
        s_result = await db.execute(summary_stmt)
        row = s_result.mappings().first()
        if row:
            holdings_count = int(row["cnt"])
            total_value = int(row["total"]) if row["total"] else None

    # Linked 13F CIKs for frontend display
    linked_13f_ciks = [c for c in cik_list if c != resolved_cik] or None

    # Brochure sections
    brochure_stmt = (
        select(SecManagerBrochureText)
        .where(SecManagerBrochureText.crd_number == manager.crd_number)
        .order_by(SecManagerBrochureText.section)
    )
    brochure_result = await db.execute(brochure_stmt)
    brochure_rows = brochure_result.scalars().all()
    brochure_sections = [
        BrochureSection(
            section=b.section,
            content=b.content[:2000],
            filing_date=b.filing_date.isoformat() if b.filing_date else None,
        )
        for b in brochure_rows
    ] or None

    return SecManagerDetail(
        crd_number=manager.crd_number,
        cik=manager.cik,
        firm_name=manager.firm_name,
        registration_status=manager.registration_status,
        aum_total=manager.aum_total,
        state=manager.state,
        country=manager.country,
        website=manager.website,
        sic=(manager.client_types or {}).get("sic"),
        sic_description=(manager.client_types or {}).get("sic_description"),
        last_adv_filed_at=manager.last_adv_filed_at,
        latest_quarter=latest_quarter.isoformat() if latest_quarter else None,
        holdings_count=holdings_count,
        total_portfolio_value=total_value,
        private_fund_count=manager.private_fund_count,
        hedge_fund_count=manager.hedge_fund_count,
        pe_fund_count=manager.pe_fund_count,
        vc_fund_count=manager.vc_fund_count,
        total_private_fund_assets=manager.total_private_fund_assets,
        brochure_sections=brochure_sections,
        linked_13f_ciks=linked_13f_ciks,
    )



# ═══════════════════════════════════════════════════════════════════════════
#  GET /holdings/reverse — reverse CUSIP lookup
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/holdings/reverse",
    response_model=SecReverseLookup,
    summary="Reverse lookup: all holders of a given CUSIP",
    dependencies=[Depends(_require_investment_role_dep)],
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:reverse")
async def reverse_lookup(
    cusip: str = Query(..., min_length=6, max_length=9),
    quarter: str | None = Query(None, description="YYYY-MM-DD format"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_with_rls),
) -> SecReverseLookup:
    today = date.today()

    # Resolve quarter
    if quarter:
        target_date = date.fromisoformat(quarter)
    else:
        latest_stmt = (
            select(func.max(Sec13fHolding.report_date))
            .where(Sec13fHolding.cusip == cusip)
            .where(Sec13fHolding.report_date <= today)
        )
        lr = await db.execute(latest_stmt)
        target_date = lr.scalar_one_or_none()

    if not target_date:
        return SecReverseLookup(cusip=cusip)

    # Get company name from first holding
    name_stmt = (
        select(Sec13fHolding.issuer_name)
        .where(Sec13fHolding.cusip == cusip)
        .where(Sec13fHolding.report_date == target_date)
        .limit(1)
    )
    name_result = await db.execute(name_stmt)
    company_name = name_result.scalar_one_or_none()

    totals_stmt = (
        select(
            func.count().label("holder_count"),
            func.coalesce(func.sum(Sec13fHolding.market_value), 0).label("total_value"),
        )
        .where(Sec13fHolding.cusip == cusip)
        .where(Sec13fHolding.report_date == target_date)
    )
    totals_result = await db.execute(totals_stmt)
    totals_row = totals_result.mappings().one()
    total_holders = int(totals_row["holder_count"] or 0)
    total_value = int(totals_row["total_value"] or 0)

    # Top holders of this CUSIP in the target quarter
    stmt = (
        select(
            Sec13fHolding.cik,
            Sec13fHolding.shares,
            Sec13fHolding.market_value,
            Sec13fHolding.report_date,
        )
        .where(Sec13fHolding.cusip == cusip)
        .where(Sec13fHolding.report_date == target_date)
        .order_by(Sec13fHolding.market_value.desc().nulls_last())
        .limit(limit)
    )
    result = await db.execute(stmt)
    holding_rows = result.mappings().all()

    if not holding_rows:
        return SecReverseLookup(cusip=cusip, company_name=company_name)

    # Resolve CIK → firm_name from sec_managers
    ciks = list({r["cik"] for r in holding_rows})
    mgr_stmt = select(SecManager.cik, SecManager.firm_name).where(SecManager.cik.in_(ciks))
    mgr_result = await db.execute(mgr_stmt)
    cik_to_name: dict[str, str] = {r[0]: r[1] for r in mgr_result.all()}

    holders = [
        ReverseLookupItem(
            cik=r["cik"],
            firm_name=cik_to_name.get(r["cik"], f"CIK {r['cik']}"),
            shares=r["shares"],
            market_value=r["market_value"],
            pct_of_total=(
                (r["market_value"] or 0) / total_value if total_value > 0 else None
            ),
            report_date=r["report_date"].isoformat(),
        )
        for r in holding_rows
    ]

    return SecReverseLookup(
        cusip=cusip,
        company_name=company_name,
        holders=holders,
        total_holders=total_holders,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/compare — peer comparison (max 5 CIKs)
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/compare",
    response_model=SecPeerCompare,
    summary="Compare 2-5 managers by CIK",
    dependencies=[Depends(_require_investment_role_dep)],
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:compare")
async def compare_managers(
    ciks: list[str] = Query(..., min_length=2, max_length=5),
    db: AsyncSession = Depends(get_db_with_rls),
) -> SecPeerCompare:
    for c in ciks:
        _validate_cik(c)

    # Fetch managers
    stmt = select(SecManager).where(SecManager.cik.in_(ciks))
    result = await db.execute(stmt)
    managers = result.scalars().all()

    if len(managers) < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="At least 2 valid managers required",
        )

    today = date.today()

    details: list[SecManagerDetail] = []
    sector_allocations: dict[str, dict[str, float]] = {}
    hhi_scores: dict[str, float] = {}
    cusip_sets: dict[str, set[str]] = {}

    for m in managers:
        cik = m.cik or ""

        # Resolve all CIKs (own + parent 13F filers via entity links)
        m_cik_list = await _resolve_ciks(db, cik, crd=m.crd_number)

        # Latest quarter
        lq_stmt = (
            select(func.max(Sec13fHolding.report_date))
            .where(Sec13fHolding.cik.in_(m_cik_list))
            .where(Sec13fHolding.report_date <= today)
        )
        lq_result = await db.execute(lq_stmt)
        latest_quarter = lq_result.scalar_one_or_none()

        holdings_count = 0
        total_value = None
        sectors: dict[str, int] = {}
        cusips: set[str] = set()

        if latest_quarter:
            h_stmt = (
                select(Sec13fHolding)
                .where(Sec13fHolding.cik.in_(m_cik_list))
                .where(Sec13fHolding.report_date == latest_quarter)
            )
            h_result = await db.execute(h_stmt)
            holdings = h_result.scalars().all()

            holdings_count = len(holdings)
            total_val = sum(h.market_value or 0 for h in holdings)
            total_value = total_val if total_val > 0 else None

            for h in holdings:
                s = h.sector or "Unknown"
                sectors[s] = sectors.get(s, 0) + (h.market_value or 0)
                cusips.add(h.cusip)

            if total_val > 0:
                sector_allocations[cik] = {
                    s: v / total_val for s, v in sorted(sectors.items(), key=lambda x: -x[1])
                }
                weights = list(sector_allocations[cik].values())
                hhi_scores[cik] = sum(w * w for w in weights)
            else:
                sector_allocations[cik] = {}

        cusip_sets[cik] = cusips

        details.append(
            SecManagerDetail(
                crd_number=m.crd_number,
                cik=m.cik,
                firm_name=m.firm_name,
                registration_status=m.registration_status,
                aum_total=m.aum_total,
                state=m.state,
                country=m.country,
                website=m.website,
                sic=(m.client_types or {}).get("sic"),
                sic_description=(m.client_types or {}).get("sic_description"),
                last_adv_filed_at=m.last_adv_filed_at,
                latest_quarter=latest_quarter.isoformat() if latest_quarter else None,
                holdings_count=holdings_count,
                total_portfolio_value=total_value,
            ),
        )

    # Pairwise CUSIP overlap
    overlaps: list[PeerHoldingOverlap] = []
    cik_list = [m.cik or "" for m in managers]
    for a, b in combinations(cik_list, 2):
        set_a = cusip_sets.get(a, set())
        set_b = cusip_sets.get(b, set())
        union = set_a | set_b
        if union:
            overlap_pct = len(set_a & set_b) / len(union)
        else:
            overlap_pct = 0.0
        overlaps.append(PeerHoldingOverlap(cik_a=a, cik_b=b, overlap_pct=overlap_pct))

    # Fund structure breakdowns (F-02)
    fund_breakdowns: dict[str, SecManagerFundBreakdown] = {}
    crd_numbers = [m.crd_number for m in managers if m.crd_number]
    if crd_numbers:
        fund_stmt = (
            select(
                SecManagerFund.crd_number,
                SecManagerFund.fund_type,
                func.count().label("fund_count"),
            )
            .where(SecManagerFund.crd_number.in_(crd_numbers))
            .group_by(SecManagerFund.crd_number, SecManagerFund.fund_type)
            .order_by(SecManagerFund.crd_number, func.count().desc())
        )
        fund_rows = (await db.execute(fund_stmt)).all()

        from collections import defaultdict
        crd_buckets: dict[str, list] = defaultdict(list)
        for row in fund_rows:
            crd_buckets[row.crd_number].append(row)

        for crd, rows in crd_buckets.items():
            total = sum(r.fund_count for r in rows)
            breakdown = [
                SecManagerFundItem(
                    fund_type=r.fund_type or "Other",
                    fund_count=r.fund_count,
                    pct_of_total=r.fund_count / total if total > 0 else 0.0,
                )
                for r in rows
            ]
            # Map by CIK for frontend consumption
            mgr = next((m for m in managers if m.crd_number == crd), None)
            key = (mgr.cik or crd) if mgr else crd
            fund_breakdowns[key] = SecManagerFundBreakdown(
                crd_number=crd, total_funds=total, breakdown=breakdown,
            )

    return SecPeerCompare(
        managers=details,
        sector_allocations=sector_allocations,
        overlaps=overlaps,
        hhi_scores=hhi_scores,
        fund_breakdowns=fund_breakdowns,
    )



# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{crd_number}/funds — fund-type breakdown (A-05)
# ═══════════════════════════════════════════════════════════════════════════


_CRD_RE = re.compile(r"^\d{1,10}$")


@router.get(
    "/managers/{crd_number}/funds",
    response_model=SecManagerFundBreakdown,
    summary="Fund-type breakdown for a manager",
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:manager_funds")
async def get_manager_funds(
    crd_number: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> SecManagerFundBreakdown:
    _require_investment_role(actor)
    if not _CRD_RE.match(crd_number):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CRD number",
        )

    # Try detailed fund records first
    stmt = (
        select(
            SecManagerFund.fund_type,
            func.count().label("fund_count"),
        )
        .where(SecManagerFund.crd_number == crd_number)
        .group_by(SecManagerFund.fund_type)
        .order_by(func.count().desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    if rows:
        total = sum(r.fund_count for r in rows)
        breakdown = [
            SecManagerFundItem(
                fund_type=r.fund_type or "Other",
                fund_count=r.fund_count,
                pct_of_total=r.fund_count / total if total > 0 else 0.0,
            )
            for r in rows
        ]
        return SecManagerFundBreakdown(
            crd_number=crd_number,
            total_funds=total,
            breakdown=breakdown,
        )

    # Fallback: derive from aggregated counts on sec_managers
    mgr = await db.execute(
        select(SecManager).where(SecManager.crd_number == crd_number),
    )
    manager = mgr.scalars().first()
    if not manager:
        raise HTTPException(status_code=404, detail="Manager not found")

    type_counts = [
        ("Hedge Fund", manager.hedge_fund_count),
        ("Private Equity", manager.pe_fund_count),
        ("Venture Capital", manager.vc_fund_count),
        ("Real Estate", manager.real_estate_fund_count),
        ("Securitized Asset", manager.securitized_fund_count),
        ("Liquidity", manager.liquidity_fund_count),
        ("Other", manager.other_fund_count),
    ]
    breakdown = []
    total = manager.private_fund_count or 0
    for fund_type, count in type_counts:
        if count and count > 0:
            breakdown.append(SecManagerFundItem(
                fund_type=fund_type,
                fund_count=count,
                pct_of_total=count / total if total > 0 else 0.0,
            ))

    return SecManagerFundBreakdown(
        crd_number=crd_number,
        total_funds=total,
        breakdown=breakdown,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /holdings/history — quarterly ownership history for a CUSIP (C-03)
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/holdings/history",
    response_model=SecHoldingsHistory,
    summary="Quarterly institutional ownership history for a CUSIP",
    dependencies=[Depends(_require_investment_role_dep)],
)
@route_cache(ttl=3600, global_key=True, key_prefix="sec:holdings_history")
async def get_holdings_history(
    cusip: str = Query(..., min_length=6, max_length=9),
    db: AsyncSession = Depends(get_db_with_rls),
) -> SecHoldingsHistory:
    today = date.today()

    stmt = (
        select(
            Sec13fHolding.report_date,
            func.count().label("total_holders"),
            func.sum(Sec13fHolding.market_value).label("total_value"),
        )
        .where(Sec13fHolding.cusip == cusip)
        .where(Sec13fHolding.report_date <= today)
        .group_by(Sec13fHolding.report_date)
        .order_by(Sec13fHolding.report_date.desc())
        .limit(8)
    )
    result = await db.execute(stmt)
    rows = result.all()

    quarters = [
        SecHoldingsHistoryPoint(
            quarter=row.report_date.isoformat(),
            total_holders=row.total_holders,
            total_market_value=int(row.total_value or 0),
        )
        for row in reversed(rows)  # chronological order
    ]

    return SecHoldingsHistory(cusip=cusip, quarters=quarters)
