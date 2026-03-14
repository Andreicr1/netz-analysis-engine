"""Dashboard aggregate endpoints — OVP-style summaries for the Operations Dashboard.

Endpoints:
  GET /dashboard/portfolio-summary    → portfolio KPIs
  GET /dashboard/pipeline-summary     → deal pipeline KPIs
  GET /dashboard/pipeline-analytics   → stage/strategy/bubble chart data
  GET /dashboard/macro-snapshot       → FRED macro indicators (latest)
  GET /dashboard/macro-history        → FRED 30-day series for sparklines
  GET /dashboard/compliance-alerts    → upcoming regulatory deadlines
  GET /dashboard/fred-search          → FRED series search proxy (Phase 3)
  GET /dashboard/macro-fred-multi     → multi-series FRED observations (Phase 3)
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.core.db.engine import get_db
from app.domains.credit.modules.ai.models import (
    DealIntelligenceProfile,
    MacroSnapshot,
)
from app.domains.credit.modules.deals.models import PipelineDeal
from app.domains.credit.modules.portfolio.models import Loan

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
def portfolio_summary(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Portfolio KPIs: AUM, active count, high-risk count, avg confidence."""

    # Active loans
    loans: list[Loan] = list(
        db.execute(
            select(Loan).where(
                Loan.fund_id == fund_id,
                Loan.status == "active",
            )
        ).scalars().all()
    )

    active_count = len(loans)
    total_principal = sum((float(ln.principal_amount or 0) for ln in loans), 0.0)

    # Format AUM
    if total_principal >= 1_000_000_000:
        aum_formatted = f"{total_principal / 1_000_000_000:.1f}B"
    elif total_principal >= 1_000_000:
        aum_formatted = f"{total_principal / 1_000_000:.1f}M"
    else:
        aum_formatted = f"{total_principal:,.0f}"

    # High-risk profiles (from approved pipeline deals that became portfolio)
    # Approximate: risk_band in (HIGH) from DealIntelligenceProfile
    high_risk_count = int(
        db.execute(
            select(func.count(DealIntelligenceProfile.id)).where(
                DealIntelligenceProfile.fund_id == fund_id,
                DealIntelligenceProfile.risk_band.in_(["HIGH", "High"]),
            )
        ).scalar_one_or_none()
        or 0
    )

    # Avg confidence from research_output.deal_overview.confidence_score
    # Compute a rough average by scanning READY deals
    ready_deals: list[PipelineDeal] = list(
        db.execute(
            select(PipelineDeal).where(
                PipelineDeal.fund_id == fund_id,
                PipelineDeal.intelligence_status == "READY",
                PipelineDeal.is_archived.is_(False),
            )
        ).scalars().all()
    )

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
def pipeline_summary(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Deal pipeline KPIs: totals, AI-ready, pending IC, converted QTD."""

    all_active: list[PipelineDeal] = list(
        db.execute(
            select(PipelineDeal).where(
                PipelineDeal.fund_id == fund_id,
                PipelineDeal.is_archived.is_(False),
            )
        ).scalars().all()
    )

    total_count = len(all_active)
    analysis_ready = sum(1 for d in all_active if d.intelligence_status == "READY")
    pending_ic = sum(
        1 for d in all_active
        if d.intelligence_status == "READY" and d.approved_deal_id is None
    )

    # Converted this quarter
    now = dt.datetime.utcnow()
    quarter_start = dt.datetime(now.year, ((now.month - 1) // 3) * 3 + 1, 1)
    converted_qtd = sum(
        1 for d in all_active
        if d.approved_deal_id is not None
        and d.approved_at is not None
        and d.approved_at.replace(tzinfo=None) >= quarter_start
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
def macro_snapshot(
    fund_id: uuid.UUID,  # noqa: ARG001 — required for fund_router path prefix
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Latest FRED macro indicators from cached MacroSnapshot."""

    today = dt.date.today()
    row: MacroSnapshot | None = db.execute(
        select(MacroSnapshot).where(MacroSnapshot.as_of_date == today)
    ).scalar_one_or_none()

    # Fallback: most recent available snapshot
    if row is None:
        row = db.execute(
            select(MacroSnapshot).order_by(MacroSnapshot.as_of_date.desc()).limit(1)
        ).scalar_one_or_none()

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
def compliance_alerts(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Upcoming regulatory deadlines extracted from deal research_output.compliance."""

    today = dt.date.today()
    days_ahead = 90  # look-ahead window

    ready_deals: list[PipelineDeal] = list(
        db.execute(
            select(PipelineDeal).where(
                PipelineDeal.fund_id == fund_id,
                PipelineDeal.intelligence_status == "READY",
                PipelineDeal.is_archived.is_(False),
            )
        ).scalars().all()
    )

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
def pipeline_analytics(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    deals: list[PipelineDeal] = list(
        db.execute(
            select(PipelineDeal).where(
                PipelineDeal.fund_id == fund_id,
                PipelineDeal.is_archived.is_(False),
            )
        ).scalars().all()
    )

    profiles: dict[uuid.UUID, DealIntelligenceProfile] = {}
    if deals:
        deal_ids = [d.id for d in deals]
        rows = db.execute(
            select(DealIntelligenceProfile).where(
                DealIntelligenceProfile.deal_id.in_(deal_ids),
            )
        ).scalars().all()
        for p in rows:
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

    # IC Status Breakdown — mutually exclusive categories
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
def macro_history(
    fund_id: uuid.UUID,  # noqa: ARG001
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    today = dt.date.today()
    row: MacroSnapshot | None = db.execute(
        select(MacroSnapshot).where(MacroSnapshot.as_of_date == today)
    ).scalar_one_or_none()
    if row is None:
        row = db.execute(
            select(MacroSnapshot).order_by(MacroSnapshot.as_of_date.desc()).limit(1)
        ).scalar_one_or_none()

    result: dict[str, list[dict[str, Any]]] = {
        "treasury10y": [],
        "baaSpread": [],
        "yieldCurve": [],
        "cpiYoy": [],
        "nfci": [],
    }

    if row is None:
        return result

    data = row.data_json or {}

    for key, (module, series_id) in _SERIES_MAP.items():
        block = (data.get(module) or {}).get(series_id) or {}
        points = block.get("series") or []
        result[key] = [{"date": p["date"], "value": p["value"]} for p in points[:30] if p.get("value") is not None]

    dgs10_block = (data.get("rates_spreads") or {}).get("DGS10") or {}
    dgs2_block = (data.get("rates_spreads") or {}).get("DGS2") or {}
    dgs10_pts = {p["date"]: p["value"] for p in (dgs10_block.get("series") or []) if p.get("value") is not None}
    dgs2_pts = {p["date"]: p["value"] for p in (dgs2_block.get("series") or []) if p.get("value") is not None}
    curve_pts = []
    for d in sorted(dgs10_pts.keys(), reverse=True)[:30]:
        if d in dgs2_pts:
            curve_pts.append({"date": d, "value": round(dgs10_pts[d] - dgs2_pts[d], 4)})
    result["yieldCurve"] = curve_pts

    return result


# ---------------------------------------------------------------------------
#  FRED Series Proxy — hides API key from frontend
# ---------------------------------------------------------------------------

@router.get("/macro-fred-series")
def macro_fred_series(
    fund_id: uuid.UUID,  # noqa: ARG001 — required for fund_router path prefix
    series_id: str = "DGS10",
    period: str = "1Y",
) -> dict[str, Any]:
    """Proxy to FRED API — hides the API key from the frontend bundle."""
    import requests as http_requests

    from app.core.config.settings import settings

    if not _FRED_ID_RE.match(series_id):
        return {"seriesId": series_id, "period": period, "observations": [], "error": "Invalid series ID format"}

    api_key = settings.FRED_API_KEY
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

    try:
        resp = http_requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "observation_start": start_date.isoformat(),
                "observation_end": end_date.isoformat(),
                "frequency": "w",
                "file_type": "json",
                "api_key": api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        observations = [
            {"date": o["date"], "value": float(o["value"])}
            for o in data.get("observations", [])
            if o.get("value") and o["value"] != "."
        ]
    except Exception:
        observations = []

    return {
        "seriesId": series_id,
        "period": period,
        "observations": observations,
    }


# ---------------------------------------------------------------------------
#  FRED Search Proxy — server-side cached series search
# ---------------------------------------------------------------------------

# Simple in-memory cache: key → (expire_time, data)
_fred_cache: dict[str, tuple[float, Any]] = {}
_fred_cache_lock = threading.Lock()
_FRED_CACHE_MAX_SIZE = 500
_FRED_SEARCH_TTL = 300  # 5 minutes
_FRED_OBS_TTL = 3600  # 1 hour
_FRED_ID_RE = re.compile(r"^[A-Z0-9_]{1,20}$")
_PERIOD_MONTHS = {"3M": 3, "6M": 6, "1Y": 12, "3Y": 36, "5Y": 60, "10Y": 120, "MAX": 600}
_fred_executor = ThreadPoolExecutor(max_workers=4)


def _cache_get(key: str) -> Any | None:
    with _fred_cache_lock:
        entry = _fred_cache.get(key)
        if entry and entry[0] > time.time():
            return entry[1]
        if entry:
            del _fred_cache[key]
        return None


def _cache_set(key: str, value: Any, ttl: int) -> None:
    with _fred_cache_lock:
        if len(_fred_cache) >= _FRED_CACHE_MAX_SIZE:
            now = time.time()
            expired = [k for k, (exp, _) in _fred_cache.items() if exp <= now]
            for k in expired:
                del _fred_cache[k]
            if len(_fred_cache) >= _FRED_CACHE_MAX_SIZE:
                oldest = min(_fred_cache, key=lambda k: _fred_cache[k][0])
                del _fred_cache[oldest]
        _fred_cache[key] = (time.time() + ttl, value)


@router.get("/fred-search")
def fred_search(
    fund_id: uuid.UUID,  # noqa: ARG001 — required for fund_router path prefix
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(default=20, le=50),
) -> dict[str, Any]:
    """Proxy FRED series/search with server-side caching."""
    import requests as http_requests

    from app.core.config.settings import settings

    api_key = settings.FRED_API_KEY
    if not api_key:
        return {"series": [], "error": "FRED_API_KEY not configured"}

    cache_key = f"fred_search:{q.lower()}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        resp = http_requests.get(
            "https://api.stlouisfed.org/fred/series/search",
            params={
                "search_text": q,
                "api_key": api_key,
                "file_type": "json",
                "limit": limit,
                "order_by": "popularity",
                "sort_order": "desc",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        result: dict[str, Any] = {
            "series": [
                {
                    "id": s["id"],
                    "title": s["title"],
                    "frequency": s.get("frequency_short", ""),
                    "units": s.get("units_short", ""),
                    "popularity": s.get("popularity", 0),
                    "last_updated": s.get("last_updated", ""),
                }
                for s in data.get("seriess", [])
            ]
        }
        _cache_set(cache_key, result, _FRED_SEARCH_TTL)
        return result
    except Exception:
        logger.warning("FRED search failed for q=%s", q, exc_info=True)
        return {"series": [], "error": "FRED search unavailable"}


# ---------------------------------------------------------------------------
#  Multi-series FRED observations — up to 4 series in one call
# ---------------------------------------------------------------------------

def _fetch_fred_observations(
    api_key: str,
    series_id: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Fetch observations for a single FRED series (with caching)."""
    import requests as http_requests

    cache_key = f"fred_obs:{series_id}:{start_date}:{end_date}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        resp = http_requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "observation_start": start_date,
                "observation_end": end_date,
                "frequency": "w",
                "file_type": "json",
                "api_key": api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        observations = [
            {"date": o["date"], "value": float(o["value"])}
            for o in data.get("observations", [])
            if o.get("value") and o["value"] != "."
        ]
        _cache_set(cache_key, observations, _FRED_OBS_TTL)
        return observations
    except Exception:
        logger.warning("FRED observations failed for %s", series_id, exc_info=True)
        return []


@router.get("/macro-fred-multi")
def macro_fred_multi(
    fund_id: uuid.UUID,  # noqa: ARG001 — required for fund_router path prefix
    series_ids: str = Query(..., description="Comma-separated FRED series IDs (max 4)"),
    period: str = Query(default="1Y"),
) -> dict[str, Any]:
    """Fetch observations for multiple FRED series — max 4 concurrent."""
    from app.core.config.settings import settings

    api_key = settings.FRED_API_KEY
    if not api_key:
        return {"series": {}, "error": "FRED_API_KEY not configured"}

    ids = [s.strip().upper() for s in series_ids.split(",") if s.strip()][:4]
    ids = [sid for sid in ids if _FRED_ID_RE.match(sid)]
    if not ids:
        return {"series": {}, "error": "No valid series IDs provided"}

    months = _PERIOD_MONTHS.get(period, 12)
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=months * 30)

    results: dict[str, list[dict[str, Any]]] = {}
    futures = {
        sid: _fred_executor.submit(
            _fetch_fred_observations,
            api_key,
            sid,
            start_date.isoformat(),
            end_date.isoformat(),
        )
        for sid in ids
    }
    for sid, future in futures.items():
        try:
            results[sid] = future.result(timeout=20)
        except Exception:
            logger.warning("FRED fetch timed out for %s", sid)
            results[sid] = []

    return {"series": results}
