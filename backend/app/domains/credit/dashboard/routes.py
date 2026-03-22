"""Dashboard aggregate endpoints -- OVP-style summaries for the Operations Dashboard.

Endpoints:
  GET /dashboard/portfolio-summary    -> portfolio KPIs
  GET /dashboard/pipeline-summary     -> deal pipeline KPIs
  GET /dashboard/pipeline-analytics   -> stage/strategy/bubble chart data
  GET /dashboard/macro-snapshot       -> FRED macro indicators (latest)
  GET /dashboard/macro-history        -> FRED 30-day series for sparklines
  GET /dashboard/compliance-alerts    -> upcoming regulatory deadlines
  GET /dashboard/fred-search          -> FRED series search proxy (Phase 3)
  GET /dashboard/macro-fred-multi     -> multi-series FRED observations (Phase 3)
  GET /dashboard/credit-market-data   -> credit market time-series from macro_data hypertable
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.modules.ai.models import (
    DealIntelligenceProfile,
    MacroSnapshot,
)
from app.domains.credit.modules.deals.models import PipelineDeal
from app.domains.credit.modules.portfolio.models import Loan
from app.shared.models import MacroData

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _stress_level_from_snapshot(data: dict[str, Any]) -> str:
    """Derive a stress level string (NONE/MILD/MODERATE/SEVERE) from raw data_json.

    Avoids importing the full market_data_engine which requires FRED credentials
    at import time.  Mirrors the scoring logic from compute_macro_stress_severity.
    """
    score = 0

    if data.get("recession_flag"):
        score += 40

    nfci = data.get("financial_conditions_index")
    if nfci is not None:
        if nfci > 1.0:
            score += 25
        elif nfci > 0.0:
            score += 10

    curve = data.get("yield_curve_2s10s")
    if curve is not None:
        if curve < -0.50:
            score += 20
        elif curve < 0:
            score += 10

    baa = data.get("baa_spread")
    if baa is not None:
        if baa > 3.0:
            score += 20
        elif baa > 2.0:
            score += 8

    if score <= 15:
        return "NONE"
    if score <= 35:
        return "MILD"
    if score <= 65:
        return "MODERATE"
    return "SEVERE"


# ---------------------------------------------------------------------------
#  Portfolio Summary
# ---------------------------------------------------------------------------

@router.get("/portfolio-summary")
async def portfolio_summary(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    """Portfolio KPIs: AUM, active count, high-risk count, avg confidence."""

    # Active loans
    result = await db.execute(
        select(Loan).where(
            Loan.fund_id == fund_id,
            Loan.status == "active",
        ),
    )
    loans: list[Loan] = list(result.scalars().all())

    active_count = len(loans)
    total_principal = sum((float(ln.principal_amount or 0) for ln in loans), 0.0)

    # Format AUM
    if total_principal >= 1_000_000_000:
        aum_formatted = f"{total_principal / 1_000_000_000:.1f}B"
    elif total_principal >= 1_000_000:
        aum_formatted = f"{total_principal / 1_000_000:.1f}M"
    else:
        aum_formatted = f"{total_principal:,.0f}"

    # High-risk profiles
    hr_result = await db.execute(
        select(func.count(DealIntelligenceProfile.id)).where(
            DealIntelligenceProfile.fund_id == fund_id,
            DealIntelligenceProfile.risk_band.in_(["HIGH", "High"]),
        ),
    )
    high_risk_count = int(hr_result.scalar_one_or_none() or 0)

    # Avg confidence from research_output.deal_overview.confidence_score
    ready_result = await db.execute(
        select(PipelineDeal).where(
            PipelineDeal.fund_id == fund_id,
            PipelineDeal.intelligence_status == "READY",
            PipelineDeal.is_archived.is_(False),
        ),
    )
    ready_deals: list[PipelineDeal] = list(ready_result.scalars().all())

    confidence_scores: list[float] = []
    for deal in ready_deals:
        ro = deal.research_output or {}
        overview = ro.get("deal_overview") or {}
        raw = overview.get("confidence_score") or overview.get("confidenceScore")
        if raw is not None:
            try:
                val = float(str(raw).replace("%", "").strip())
                if 0 <= val <= 100:
                    confidence_scores.append(val)
            except (ValueError, TypeError):
                pass

    avg_confidence = round(sum(confidence_scores) / len(confidence_scores), 1) if confidence_scores else 0

    return {
        "aumFormatted": aum_formatted,
        "aumIndicator": "Up" if total_principal > 0 else "None",
        "activeCount": active_count,
        "highRiskCount": high_risk_count,
        "avgConfidence": avg_confidence,
    }


# ---------------------------------------------------------------------------
#  Pipeline Summary
# ---------------------------------------------------------------------------

@router.get("/pipeline-summary")
async def pipeline_summary(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    """Deal pipeline KPIs: totals, AI-ready, pending IC, converted QTD."""

    result = await db.execute(
        select(PipelineDeal).where(
            PipelineDeal.fund_id == fund_id,
            PipelineDeal.is_archived.is_(False),
        ),
    )
    all_active: list[PipelineDeal] = list(result.scalars().all())

    total_count = len(all_active)
    analysis_ready = sum(1 for d in all_active if d.intelligence_status == "READY")
    pending_ic = sum(
        1 for d in all_active
        if d.intelligence_status == "READY" and d.approved_deal_id is None
    )

    # Converted this quarter
    now = dt.datetime.now(dt.UTC)
    quarter_start = dt.datetime(now.year, ((now.month - 1) // 3) * 3 + 1, 1, tzinfo=dt.UTC)
    converted_qtd = sum(
        1 for d in all_active
        if d.approved_deal_id is not None
        and d.approved_at is not None
        and d.approved_at.replace(tzinfo=None) >= quarter_start.replace(tzinfo=None)
    )

    return {
        "totalCount": total_count,
        "analysisReadyCount": analysis_ready,
        "pendingIcCount": pending_ic,
        "convertedQtdCount": converted_qtd,
    }


# ---------------------------------------------------------------------------
#  Macro Snapshot
# ---------------------------------------------------------------------------

@router.get("/macro-snapshot")
async def macro_snapshot(
    fund_id: uuid.UUID,  # noqa: ARG001 -- required for fund_router path prefix
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    """Latest FRED macro indicators from cached MacroSnapshot."""

    today = dt.date.today()
    result = await db.execute(
        select(MacroSnapshot).where(MacroSnapshot.as_of_date == today),
    )
    row: MacroSnapshot | None = result.scalar_one_or_none()

    # Fallback: most recent available snapshot
    if row is None:
        result = await db.execute(
            select(MacroSnapshot).order_by(MacroSnapshot.as_of_date.desc()).limit(1),
        )
        row = result.scalar_one_or_none()

    if row is None:
        return {
            "stressLevel": "NONE",
            "treasury10y": None,
            "baaSpread": None,
            "yieldCurve2s10s": None,
            "cpiYoy": None,
            "nfci": None,
            "asOfDate": today.isoformat(),
        }

    data = row.data_json or {}
    stress_level = _stress_level_from_snapshot(data)

    return {
        "stressLevel": stress_level,
        "treasury10y": data.get("risk_free_10y"),
        "baaSpread": data.get("baa_spread"),
        "yieldCurve2s10s": data.get("yield_curve_2s10s"),
        "cpiYoy": data.get("cpi_yoy"),
        "nfci": data.get("financial_conditions_index"),
        "asOfDate": row.as_of_date.isoformat(),
    }


# ---------------------------------------------------------------------------
#  Compliance Alerts
# ---------------------------------------------------------------------------

@router.get("/compliance-alerts")
async def compliance_alerts(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    """Upcoming regulatory deadlines extracted from deal research_output.compliance."""

    today = dt.date.today()
    days_ahead = 90  # look-ahead window

    result = await db.execute(
        select(PipelineDeal).where(
            PipelineDeal.fund_id == fund_id,
            PipelineDeal.intelligence_status == "READY",
            PipelineDeal.is_archived.is_(False),
        ),
    )
    ready_deals: list[PipelineDeal] = list(result.scalars().all())

    upcoming: list[dict[str, Any]] = []

    for deal in ready_deals:
        ro = deal.research_output or {}
        compliance_section = ro.get("compliance") or {}
        regulatory_deadlines = compliance_section.get("regulatory_deadlines") or []

        for item in regulatory_deadlines:
            raw_date = item.get("due_date")
            if not raw_date:
                continue
            try:
                due = dt.date.fromisoformat(str(raw_date)[:10])
            except ValueError:
                continue

            days_left = (due - today).days
            if days_left < 0 or days_left > days_ahead:
                continue

            upcoming.append({
                "dealName": deal.deal_name or deal.title or str(deal.id),
                "description": item.get("requirement") or item.get("detail") or "",
                "dueDate": due.strftime("%b %d, %Y"),
                "daysLeft": days_left,
            })

    # Sort by urgency
    upcoming.sort(key=lambda x: x["daysLeft"])

    critical = sum(1 for x in upcoming if x["daysLeft"] <= 7)

    return {
        "upcomingCount": len(upcoming),
        "criticalCount": critical,
        "upcomingDeadlines": upcoming,
    }


# ---------------------------------------------------------------------------
#  Pipeline Analytics (charts)
# ---------------------------------------------------------------------------

_RISK_BAND_SCORE = {"HIGH": 80, "High": 80, "MEDIUM": 50, "Medium": 50, "LOW": 20, "Low": 20}

_STAGE_ORDER = [
    "Intake", "Qualification", "Initial Review", "Underwriting",
    "IC Memo Draft", "IC Decision", "Execution",
]


def _parse_return(raw: str | None) -> float | None:
    if not raw:
        return None
    m = re.search(r"(\d+(?:\.\d+))", str(raw).replace("%", "").strip())
    return float(m.group(1)) if m else None


@router.get("/pipeline-analytics")
async def pipeline_analytics(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    result = await db.execute(
        select(PipelineDeal).where(
            PipelineDeal.fund_id == fund_id,
            PipelineDeal.is_archived.is_(False),
        ),
    )
    deals: list[PipelineDeal] = list(result.scalars().all())

    profiles: dict[uuid.UUID, DealIntelligenceProfile] = {}
    if deals:
        deal_ids = [d.id for d in deals]
        p_result = await db.execute(
            select(DealIntelligenceProfile).where(
                DealIntelligenceProfile.deal_id.in_(deal_ids),
            ),
        )
        for p in p_result.scalars().all():
            profiles[p.deal_id] = p

    stage_counts: dict[str, int] = defaultdict(int)
    strategy_agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"dealCount": 0, "returnSum": 0.0, "returnN": 0, "totalTicket": 0.0},
    )
    bubbles: list[dict[str, Any]] = []

    for deal in deals:
        stage_label = deal.stage or deal.lifecycle_stage or "Intake"
        stage_counts[stage_label] += 1

        profile = profiles.get(deal.id)
        ro = deal.research_output or {}
        overview = ro.get("deal_overview") or {}

        strategy = (profile.strategy_type if profile else None) or overview.get("instrument") or "Other"
        target_ret = _parse_return(profile.target_return if profile else None) or _parse_return(overview.get("yield"))
        ticket = float(deal.requested_amount or 0)
        risk_band = (profile.risk_band if profile else None) or "MEDIUM"
        risk_score = _RISK_BAND_SCORE.get(risk_band, 50)

        agg = strategy_agg[strategy]
        agg["dealCount"] += 1
        agg["totalTicket"] += ticket
        if target_ret is not None:
            agg["returnSum"] += target_ret
            agg["returnN"] += 1

        if deal.intelligence_status == "READY" and ticket > 0:
            bubbles.append({
                "dealName": deal.deal_name or deal.title or str(deal.id),
                "riskScore": risk_score,
                "targetReturn": target_ret or 0,
                "ticketSize": ticket,
                "strategy": strategy,
            })

    stage_distribution = []
    for s in _STAGE_ORDER:
        if stage_counts.get(s, 0) > 0:
            stage_distribution.append({"stage": s, "count": stage_counts[s]})
    for s, c in stage_counts.items():
        if s not in _STAGE_ORDER and c > 0:
            stage_distribution.append({"stage": s, "count": c})

    strategy_breakdown = []
    for strat, agg in strategy_agg.items():
        avg_ret = round(agg["returnSum"] / agg["returnN"], 2) if agg["returnN"] > 0 else 0
        strategy_breakdown.append({
            "strategy": strat,
            "dealCount": agg["dealCount"],
            "avgTargetReturn": avg_ret,
            "totalTicket": agg["totalTicket"],
        })

    # IC Status Breakdown -- mutually exclusive categories
    ic_counts: dict[str, int] = defaultdict(int)
    for deal in deals:
        stage_raw = (deal.stage or deal.lifecycle_stage or "").lower().strip()
        if stage_raw in ("ic_approved", "approved"):
            ic_counts["Approved"] += 1
        elif stage_raw in ("ic_conditional", "conditional"):
            ic_counts["Conditional"] += 1
        elif deal.intelligence_status == "READY" and stage_raw not in (
            "portfolio", "converted_to_asset", "execution",
        ):
            ic_counts["Ready"] += 1
        else:
            ic_counts["Pending"] += 1

    ic_status_breakdown = [
        {"status": k, "count": v} for k, v in ic_counts.items() if v > 0
    ]

    return {
        "stageDistribution": stage_distribution,
        "strategyBreakdown": strategy_breakdown,
        "dealBubbles": bubbles,
        "icStatusBreakdown": ic_status_breakdown,
    }


# ---------------------------------------------------------------------------
#  Macro History (sparklines)
# ---------------------------------------------------------------------------

_SERIES_MAP = {
    "treasury10y": ("rates_spreads", "DGS10"),
    "baaSpread": ("rates_spreads", "BAA10Y"),
    "nfci": ("rates_spreads", "NFCI"),
    "cpiYoy": ("macro_fundamentals", "CPIAUCSL"),
}


@router.get("/macro-history")
async def macro_history(
    fund_id: uuid.UUID,  # noqa: ARG001
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    today = dt.date.today()
    result = await db.execute(
        select(MacroSnapshot).where(MacroSnapshot.as_of_date == today),
    )
    row: MacroSnapshot | None = result.scalar_one_or_none()
    if row is None:
        result = await db.execute(
            select(MacroSnapshot).order_by(MacroSnapshot.as_of_date.desc()).limit(1),
        )
        row = result.scalar_one_or_none()

    macro_result: dict[str, list[dict[str, Any]]] = {
        "treasury10y": [],
        "baaSpread": [],
        "yieldCurve": [],
        "cpiYoy": [],
        "nfci": [],
    }

    if row is None:
        return macro_result

    data = row.data_json or {}

    for key, (module, series_id) in _SERIES_MAP.items():
        block = (data.get(module) or {}).get(series_id) or {}
        points = block.get("series") or []
        macro_result[key] = [{"date": p["date"], "value": p["value"]} for p in points[:30] if p.get("value") is not None]

    dgs10_block = (data.get("rates_spreads") or {}).get("DGS10") or {}
    dgs2_block = (data.get("rates_spreads") or {}).get("DGS2") or {}
    dgs10_pts = {p["date"]: p["value"] for p in (dgs10_block.get("series") or []) if p.get("value") is not None}
    dgs2_pts = {p["date"]: p["value"] for p in (dgs2_block.get("series") or []) if p.get("value") is not None}
    curve_pts = []
    for d in sorted(dgs10_pts.keys(), reverse=True)[:30]:
        if d in dgs2_pts:
            curve_pts.append({"date": d, "value": round(dgs10_pts[d] - dgs2_pts[d], 4)})
    macro_result["yieldCurve"] = curve_pts

    return macro_result


# ---------------------------------------------------------------------------
#  FRED Series Proxy -- hides API key from frontend
# ---------------------------------------------------------------------------

@router.get("/macro-fred-series")
async def macro_fred_series(
    fund_id: uuid.UUID,  # noqa: ARG001 -- required for fund_router path prefix
    actor: Actor = Depends(get_actor),
    series_id: str = "DGS10",
    period: str = "1Y",
) -> dict[str, Any]:
    """Proxy to FRED API -- hides the API key from the frontend bundle.

    Uses httpx.AsyncClient — does not block the event loop.
    """
    from app.core.config.settings import settings
    from app.domains.credit.dashboard.fred_client import (
        _FRED_ID_RE,
        _PERIOD_MONTHS,
        get_shared_client,
    )

    if not _FRED_ID_RE.match(series_id):
        return {"seriesId": series_id, "period": period, "observations": [], "error": "Invalid series ID format"}

    api_key = settings.fred_api_key
    if not api_key:
        return {
            "seriesId": series_id,
            "period": period,
            "observations": [],
            "error": "FRED_API_KEY not configured",
        }

    months = _PERIOD_MONTHS.get(period, 12)
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=months * 30)

    client = await get_shared_client(api_key)
    observations = await client.fetch_observations(
        series_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )

    return {
        "seriesId": series_id,
        "period": period,
        "observations": observations,
    }


# ---------------------------------------------------------------------------
#  FRED Search Proxy -- server-side cached series search
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
#  FRED Search Proxy -- server-side cached series search
# ---------------------------------------------------------------------------

@router.get("/fred-search")
async def fred_search(
    fund_id: uuid.UUID,  # noqa: ARG001 -- required for fund_router path prefix
    actor: Actor = Depends(get_actor),
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(default=20, le=50),
) -> dict[str, Any]:
    """Proxy FRED series/search with server-side caching.

    Uses httpx.AsyncClient — does not block the event loop.
    """
    from app.core.config.settings import settings
    from app.domains.credit.dashboard.fred_client import get_shared_client

    api_key = settings.fred_api_key
    if not api_key:
        return {"series": [], "error": "FRED_API_KEY not configured"}

    client = await get_shared_client(api_key)
    series = await client.search_series(q, limit=limit)
    if not series:
        return {"series": [], "error": "FRED search unavailable"}
    return {"series": series}


# ---------------------------------------------------------------------------
#  Multi-series FRED observations -- up to 4 series in one call (async)
# ---------------------------------------------------------------------------

@router.get("/macro-fred-multi")
async def macro_fred_multi(
    fund_id: uuid.UUID,  # noqa: ARG001 -- required for fund_router path prefix
    actor: Actor = Depends(get_actor),
    series_ids: str = Query(..., description="Comma-separated FRED series IDs (max 4)"),
    period: str = Query(default="1Y"),
) -> dict[str, Any]:
    """Fetch observations for multiple FRED series concurrently.

    Uses asyncio.gather via AsyncFredClient.fetch_multi — does not block
    the event loop. All series fetched concurrently within the same
    event loop iteration.
    """
    from app.core.config.settings import settings
    from app.domains.credit.dashboard.fred_client import (
        _FRED_ID_RE,
        _PERIOD_MONTHS,
        get_shared_client,
    )

    api_key = settings.fred_api_key
    if not api_key:
        return {"series": {}, "error": "FRED_API_KEY not configured"}

    ids = [s.strip().upper() for s in series_ids.split(",") if s.strip()][:4]
    ids = [sid for sid in ids if _FRED_ID_RE.match(sid)]
    if not ids:
        return {"series": {}, "error": "No valid series IDs provided"}

    months = _PERIOD_MONTHS.get(period, 12)
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=months * 30)

    client = await get_shared_client(api_key)
    results = await client.fetch_multi(
        ids,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )
    return {"series": results}


# ---------------------------------------------------------------------------
#  Credit Market Data — time-series from macro_data hypertable
# ---------------------------------------------------------------------------

# Series IDs grouped by section for the credit market data page.
# All sourced from the macro_data global hypertable (ingested by macro_ingestion worker).

_CREDIT_MARKET_SERIES: dict[str, list[str]] = {
    "credit_spreads": ["BAA10Y", "BAMLH0A0HYM2"],
    "yield_curve": ["DFF", "SOFR", "DGS2", "DGS10"],
    "case_shiller_national": ["CSUSHPINSA"],
    "case_shiller_metro": [
        "NYXRSA", "LXXRSA", "MFHXRSA", "CHXRSA", "DAXRSA",
        "HIOXRSA", "WDXRSA", "BOXRSA", "ATXRSA", "SEXRSA",
        "PHXRSA", "DNXRSA", "SFXRSA", "TPXRSA", "CRXRSA",
        "MNXRSA", "POXRSA", "SDXRSA", "DEXRSA", "CLXRSA",
    ],
    "housing": ["MSPUS", "HOUST", "PERMIT", "EXHOSLUSM495S", "MSACSR"],
    "mortgage": ["MORTGAGE30US", "MORTGAGE15US"],
    "delinquency": ["DRCCLACBS", "DRSFRMACBS", "DRHMACBS"],
    "credit_quality": ["DRALACBN", "NETCIBAL", "DRCILNFNQ"],
    "banking": ["TOTLL", "STLFSI4"],
}

# Human-readable labels for each series.
_SERIES_LABELS: dict[str, str] = {
    "BAA10Y": "Baa Corporate Spread",
    "BAMLH0A0HYM2": "ICE BofA HY OAS",
    "DFF": "Fed Funds Rate",
    "SOFR": "SOFR",
    "DGS2": "2Y Treasury",
    "DGS10": "10Y Treasury",
    "CSUSHPINSA": "Case-Shiller National HPI",
    "NYXRSA": "New York",
    "LXXRSA": "Los Angeles",
    "MFHXRSA": "Miami",
    "CHXRSA": "Chicago",
    "DAXRSA": "Dallas",
    "HIOXRSA": "Houston",
    "WDXRSA": "Washington DC",
    "BOXRSA": "Boston",
    "ATXRSA": "Atlanta",
    "SEXRSA": "Seattle",
    "PHXRSA": "Phoenix",
    "DNXRSA": "Denver",
    "SFXRSA": "San Francisco",
    "TPXRSA": "Tampa",
    "CRXRSA": "Charlotte",
    "MNXRSA": "Minneapolis",
    "POXRSA": "Portland",
    "SDXRSA": "San Diego",
    "DEXRSA": "Detroit",
    "CLXRSA": "Cleveland",
    "MSPUS": "Median Sale Price",
    "HOUST": "Housing Starts",
    "PERMIT": "Building Permits",
    "EXHOSLUSM495S": "Existing Home Sales",
    "MSACSR": "Months Supply",
    "MORTGAGE30US": "30Y Fixed Mortgage",
    "MORTGAGE15US": "15Y Fixed Mortgage",
    "DRCCLACBS": "Credit Card Delinquency",
    "DRSFRMACBS": "Mortgage Delinquency",
    "DRHMACBS": "Home Equity Delinquency",
    "DRALACBN": "All Loans Delinquency",
    "NETCIBAL": "Net Charge-Off Rate",
    "DRCILNFNQ": "C&I Loan Delinquency",
    "TOTLL": "Total Loans & Leases",
    "STLFSI4": "Financial Stress Index",
}

# Flat set of all series IDs for the query.
_ALL_CREDIT_MARKET_IDS: list[str] = [
    sid for group in _CREDIT_MARKET_SERIES.values() for sid in group
]


@router.get("/credit-market-data")
async def credit_market_data(
    fund_id: uuid.UUID,  # noqa: ARG001 -- required for fund_router path prefix
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),  # noqa: ARG001
    months: int = Query(default=24, ge=3, le=60),
) -> dict[str, Any]:
    """Credit market time-series from macro_data hypertable.

    Returns series grouped by section for the market data page.
    macro_data is a GLOBAL table (no RLS, no organization_id).
    """
    cutoff = dt.date.today() - dt.timedelta(days=months * 31)

    result = await db.execute(
        select(
            MacroData.series_id,
            MacroData.obs_date,
            MacroData.value,
        )
        .where(
            MacroData.series_id.in_(_ALL_CREDIT_MARKET_IDS),
            MacroData.obs_date >= cutoff,
        )
        .order_by(MacroData.series_id, MacroData.obs_date)
    )
    rows = result.all()

    # Group by series_id
    by_series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for series_id, obs_date, value in rows:
        by_series[series_id].append({
            "date": obs_date.isoformat(),
            "value": float(value),
        })

    # Build grouped response
    sections: dict[str, Any] = {}
    for section_key, series_ids in _CREDIT_MARKET_SERIES.items():
        section_data: dict[str, Any] = {}
        for sid in series_ids:
            points = by_series.get(sid, [])
            section_data[sid] = {
                "label": _SERIES_LABELS.get(sid, sid),
                "points": points,
                "latest": points[-1]["value"] if points else None,
            }
        sections[section_key] = section_data

    # Compute yield curve snapshot (latest values for DFF, SOFR, DGS2, DGS10)
    yield_curve_snapshot: list[dict[str, Any]] = []
    for sid in ["DFF", "SOFR", "DGS2", "DGS10"]:
        points = by_series.get(sid, [])
        if points:
            yield_curve_snapshot.append({
                "seriesId": sid,
                "label": _SERIES_LABELS.get(sid, sid),
                "value": points[-1]["value"],
                "date": points[-1]["date"],
            })

    # 2s10s inversion indicator
    dgs2_latest = by_series.get("DGS2", [])
    dgs10_latest = by_series.get("DGS10", [])
    spread_2s10s: float | None = None
    if dgs2_latest and dgs10_latest:
        spread_2s10s = round(dgs10_latest[-1]["value"] - dgs2_latest[-1]["value"], 4)

    return {
        "sections": sections,
        "yieldCurveSnapshot": yield_curve_snapshot,
        "spread2s10s": spread_2s10s,
        "inverted": spread_2s10s is not None and spread_2s10s < 0,
        "asOfDate": dt.date.today().isoformat(),
        "source": "FRED (via macro_data hypertable)",
    }
