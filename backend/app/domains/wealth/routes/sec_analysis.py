"""SEC Analysis API routes — US Fund Analysis page.

CIK-based manager search, holdings with quarter selection, style drift,
reverse CUSIP lookup, and peer comparison. All queries hit global SEC tables
(no RLS, no organization_id).

GET  /sec/managers/search          — paginated text search + filters
GET  /sec/managers/{cik}           — manager detail + latest holdings summary
GET  /sec/managers/{cik}/holdings  — holdings by quarter (default: latest)
GET  /sec/managers/{cik}/style-drift — sector allocation history
GET  /sec/holdings/reverse         — reverse lookup by CUSIP
GET  /sec/managers/compare         — peer comparison (max 5 CIKs)
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from itertools import combinations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import route_cache
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.schemas.sec_analysis import (
    PeerHoldingOverlap,
    ReverseLookupItem,
    SecHoldingItem,
    SecHoldingsHistory,
    SecHoldingsHistoryPoint,
    SecHoldingsPage,
    SecManagerDetail,
    SecManagerFundBreakdown,
    SecManagerFundItem,
    SecManagerItem,
    SecManagerSearchPage,
    SecPeerCompare,
    SecReverseLookup,
    SecSicCodeItem,
    SecStyleDrift,
    SectorWeight,
    StyleDriftSignal,
)
from app.shared.enums import Role
from app.shared.models import Sec13fDiff, Sec13fHolding, SecManager, SecManagerFund

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


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/search — paginated search with filters
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/search",
    response_model=SecManagerSearchPage,
    summary="Search SEC managers with filters",
    dependencies=[Depends(_require_investment_role_dep)],
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:search")
async def search_managers(
    q: str | None = Query(None, max_length=200),
    entity_type: str | None = Query(None),
    state: str | None = Query(None),
    has_cik: bool | None = Query(None),
    aum_min: int | None = Query(None),
    aum_max: int | None = Query(None),
    filed_within_days: int | None = Query(None, ge=1, le=730),
    sic: str | None = Query(None, max_length=10),
    has_disclosures: bool | None = Query(None),
    sort_by: str = Query("aum_total"),
    sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db_with_rls),
) -> SecManagerSearchPage:
    stmt = select(SecManager)
    count_stmt = select(func.count()).select_from(SecManager)

    conditions = []

    if q:
        q_lower = f"%{q.lower()}%"
        conditions.append(
            or_(
                SecManager.firm_name.ilike(q_lower),
                SecManager.cik == q if q.isdigit() else False,  # type: ignore[arg-type]
                SecManager.crd_number == q,
            )
        )

    if entity_type:
        conditions.append(SecManager.registration_status == entity_type)

    if state:
        conditions.append(SecManager.state == state)

    if has_cik is True:
        conditions.append(SecManager.cik.isnot(None))
    elif has_cik is False:
        conditions.append(SecManager.cik.is_(None))

    if aum_min is not None:
        conditions.append(SecManager.aum_total >= aum_min)

    if aum_max is not None:
        conditions.append(SecManager.aum_total <= aum_max)

    if filed_within_days is not None:
        cutoff = date.today() - timedelta(days=filed_within_days)
        conditions.append(SecManager.last_adv_filed_at >= cutoff)

    if sic:
        conditions.append(
            SecManager.client_types["sic"].astext == sic
        )

    if has_disclosures is True:
        conditions.append(SecManager.compliance_disclosures > 0)
    elif has_disclosures is False:
        conditions.append(
            (SecManager.compliance_disclosures.is_(None))
            | (SecManager.compliance_disclosures == 0)
        )

    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    # Sorting
    sort_col = getattr(SecManager, sort_by, SecManager.aum_total)
    if sort_dir == "asc":
        stmt = stmt.order_by(sort_col.asc().nulls_last())
    else:
        stmt = stmt.order_by(sort_col.desc().nulls_last())

    offset = (page - 1) * page_size
    stmt = stmt.limit(page_size).offset(offset)

    data_result = await db.execute(stmt)
    count_result = await db.execute(count_stmt)

    total_count = count_result.scalar_one()
    rows = data_result.scalars().all()

    managers = [
        SecManagerItem(
            crd_number=m.crd_number,
            cik=m.cik,
            firm_name=m.firm_name,
            registration_status=m.registration_status,
            aum_total=m.aum_total,
            state=m.state,
            country=m.country,
            sic=(m.client_types or {}).get("sic"),
            sic_description=(m.client_types or {}).get("sic_description"),
            last_adv_filed_at=m.last_adv_filed_at,
            compliance_disclosures=m.compliance_disclosures,
        )
        for m in rows
    ]

    return SecManagerSearchPage(
        managers=managers,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total_count,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{cik} — detail with latest holdings summary
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{cik}",
    response_model=SecManagerDetail,
    summary="Manager detail by CIK",
)
async def get_manager_detail(
    cik: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> SecManagerDetail:
    _require_investment_role(actor)
    cik = _validate_cik(cik)

    stmt = select(SecManager).where(SecManager.cik == cik)
    result = await db.execute(stmt)
    manager = result.scalar_one_or_none()
    if not manager:
        raise HTTPException(status_code=404, detail=f"Manager with CIK {cik} not found")

    today = date.today()

    # Latest quarter summary — always filter report_date for chunk pruning
    latest_q_stmt = (
        select(func.max(Sec13fHolding.report_date))
        .where(Sec13fHolding.cik == cik)
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
            .where(Sec13fHolding.cik == cik)
            .where(Sec13fHolding.report_date == latest_quarter)
        )
        s_result = await db.execute(summary_stmt)
        row = s_result.mappings().first()
        if row:
            holdings_count = int(row["cnt"])
            total_value = int(row["total"]) if row["total"] else None

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
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{cik}/holdings — holdings by quarter with deltas
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{cik}/holdings",
    response_model=SecHoldingsPage,
    summary="Manager holdings for a specific quarter",
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:holdings")
async def get_holdings(
    cik: str = Path(...),
    quarter: str | None = Query(None, description="YYYY-MM-DD format"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> SecHoldingsPage:
    _require_investment_role(actor)
    cik = _validate_cik(cik)

    today = date.today()

    # Available quarters
    quarters_stmt = (
        select(Sec13fHolding.report_date)
        .where(Sec13fHolding.cik == cik)
        .where(Sec13fHolding.report_date <= today)
        .distinct()
        .order_by(Sec13fHolding.report_date.desc())
        .limit(12)
    )
    q_result = await db.execute(quarters_stmt)
    available_quarters = [row[0].isoformat() for row in q_result.all()]

    if not available_quarters:
        return SecHoldingsPage(cik=cik)

    # Resolve target quarter
    if quarter:
        target_date = date.fromisoformat(quarter)
    else:
        target_date = date.fromisoformat(available_quarters[0])

    # Count total holdings for this quarter
    count_stmt = (
        select(func.count())
        .select_from(Sec13fHolding)
        .where(Sec13fHolding.cik == cik)
        .where(Sec13fHolding.report_date == target_date)
    )
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar_one()

    # Total value
    value_stmt = (
        select(func.sum(Sec13fHolding.market_value))
        .where(Sec13fHolding.cik == cik)
        .where(Sec13fHolding.report_date == target_date)
    )
    value_result = await db.execute(value_stmt)
    total_value = value_result.scalar_one()

    # Paginated holdings
    offset = (page - 1) * page_size
    holdings_stmt = (
        select(Sec13fHolding)
        .where(Sec13fHolding.cik == cik)
        .where(Sec13fHolding.report_date == target_date)
        .order_by(Sec13fHolding.market_value.desc().nulls_last())
        .limit(page_size)
        .offset(offset)
    )
    h_result = await db.execute(holdings_stmt)
    holdings = h_result.scalars().all()

    # Get diffs for this quarter to annotate deltas
    diff_map: dict[str, tuple[int | None, int | None, str | None]] = {}
    diff_stmt = (
        select(Sec13fDiff)
        .where(Sec13fDiff.cik == cik)
        .where(Sec13fDiff.quarter_to == target_date)
    )
    d_result = await db.execute(diff_stmt)
    for d in d_result.scalars().all():
        value_delta = None
        if d.value_after is not None and d.value_before is not None:
            value_delta = d.value_after - d.value_before
        diff_map[d.cusip] = (d.shares_delta, value_delta, d.action)

    total_val = int(total_value) if total_value else 0
    items = []
    for h in holdings:
        delta = diff_map.get(h.cusip, (None, None, None))
        items.append(
            SecHoldingItem(
                cusip=h.cusip,
                company_name=h.issuer_name or "Unknown",
                sector=h.sector,
                shares=h.shares,
                market_value=h.market_value,
                pct_portfolio=(h.market_value or 0) / total_val if total_val > 0 else None,
                delta_shares=delta[0],
                delta_value=delta[1],
                delta_action=delta[2],
            )
        )

    return SecHoldingsPage(
        cik=cik,
        quarter=target_date.isoformat(),
        available_quarters=available_quarters,
        holdings=items,
        total_count=total_count,
        total_value=int(total_value) if total_value else None,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total_count,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  GET /managers/{cik}/style-drift — sector allocation history
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/{cik}/style-drift",
    response_model=SecStyleDrift,
    summary="Sector allocation history and drift signals",
)
@route_cache(ttl=300, global_key=True, key_prefix="sec:drift")
async def get_style_drift(
    cik: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> SecStyleDrift:
    _require_investment_role(actor)
    cik = _validate_cik(cik)

    today = date.today()
    cutoff = date(today.year - 2, today.month, today.day)

    # Sector allocation per quarter — always filter report_date for chunk pruning
    stmt = (
        select(
            Sec13fHolding.report_date,
            Sec13fHolding.sector,
            func.sum(Sec13fHolding.market_value).label("value"),
        )
        .where(Sec13fHolding.cik == cik)
        .where(Sec13fHolding.report_date >= cutoff)
        .where(Sec13fHolding.report_date <= today)
        .group_by(Sec13fHolding.report_date, Sec13fHolding.sector)
        .order_by(Sec13fHolding.report_date)
    )
    result = await db.execute(stmt)
    rows = result.mappings().all()

    # Group by quarter to compute weights
    quarter_totals: dict[date, int] = {}
    quarter_sectors: dict[date, dict[str, int]] = {}
    for row in rows:
        q = row["report_date"]
        sector = row["sector"] or "Unknown"
        val = int(row["value"] or 0)
        quarter_totals[q] = quarter_totals.get(q, 0) + val
        if q not in quarter_sectors:
            quarter_sectors[q] = {}
        quarter_sectors[q][sector] = quarter_sectors[q].get(sector, 0) + val

    # Build history points
    history: list[SectorWeight] = []
    for q in sorted(quarter_totals.keys()):
        total = quarter_totals[q]
        if total <= 0:
            continue
        for sector, val in quarter_sectors[q].items():
            history.append(
                SectorWeight(
                    quarter=q.isoformat(),
                    sector=sector,
                    weight_pct=val / total,
                )
            )

    # Drift signals: compare last two quarters
    sorted_quarters = sorted(quarter_totals.keys())
    drift_signals: list[StyleDriftSignal] = []
    if len(sorted_quarters) >= 2:
        prev_q = sorted_quarters[-2]
        curr_q = sorted_quarters[-1]
        prev_total = quarter_totals[prev_q]
        curr_total = quarter_totals[curr_q]

        all_sectors = set(quarter_sectors.get(prev_q, {}).keys()) | set(
            quarter_sectors.get(curr_q, {}).keys()
        )

        for sector in sorted(all_sectors):
            w_prev = (
                quarter_sectors.get(prev_q, {}).get(sector, 0) / prev_total
                if prev_total > 0
                else 0.0
            )
            w_curr = (
                quarter_sectors.get(curr_q, {}).get(sector, 0) / curr_total
                if curr_total > 0
                else 0.0
            )
            delta = w_curr - w_prev
            signal = "DRIFT" if abs(delta) > 0.05 else "STABLE"
            drift_signals.append(
                StyleDriftSignal(
                    sector=sector,
                    weight_current=w_curr,
                    weight_prev=w_prev,
                    delta=delta,
                    signal=signal,
                )
            )

    return SecStyleDrift(cik=cik, history=history, drift_signals=drift_signals)


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

    # All holders of this CUSIP in the target quarter
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

    # Total value for % calculation
    total_value = sum(int(r["market_value"] or 0) for r in holding_rows)

    holders = [
        ReverseLookupItem(
            cik=r["cik"],
            firm_name=cik_to_name.get(r["cik"], f"CIK {r['cik']}"),
            shares=r["shares_or_principal"],
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
        total_holders=len(holders),
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

        # Latest quarter
        lq_stmt = (
            select(func.max(Sec13fHolding.report_date))
            .where(Sec13fHolding.cik == cik)
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
                .where(Sec13fHolding.cik == cik)
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
            )
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
#  GET /managers/sic-codes — available SIC codes with counts (A-04)
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/managers/sic-codes",
    response_model=list[SecSicCodeItem],
    summary="SIC codes with manager counts",
    dependencies=[Depends(_require_investment_role_dep)],
)
@route_cache(ttl=3600, global_key=True, key_prefix="sec:sic_codes")
async def get_sic_codes(
    db: AsyncSession = Depends(get_db_with_rls),
) -> list[SecSicCodeItem]:
    stmt = (
        select(
            SecManager.client_types["sic"].astext.label("sic"),
            SecManager.client_types["sic_description"].astext.label("sic_desc"),
            func.count().label("cnt"),
        )
        .where(SecManager.client_types["sic"].astext.isnot(None))
        .where(SecManager.client_types["sic"].astext != "")
        .group_by(
            SecManager.client_types["sic"].astext,
            SecManager.client_types["sic_description"].astext,
        )
        .order_by(func.count().desc())
    )
    result = await db.execute(stmt)
    return [
        SecSicCodeItem(sic=row.sic, sic_description=row.sic_desc, count=row.cnt)
        for row in result.all()
    ]


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
