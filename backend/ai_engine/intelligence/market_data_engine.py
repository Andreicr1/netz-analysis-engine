"""Market Data Engine v2 — deterministic FRED macro overlay for Deep Review v4.

Retrieves macroeconomic time-series from the FRED API (St. Louis Fed), computes
an expanded structured macro snapshot with full 12-month curves, caches results
daily in the ``macro_snapshots`` table, and injects the snapshot into the deep
review context payload.

Design invariants (MUST be preserved):
  * Deterministic — same as_of_date always returns the same snapshot.
  * Snapshot-based — one snapshot per calendar day, immutable once stored.
  * Cached — FRED is called at most once per day per snapshot type.
  * No LLM involvement — the LLM never calls FRED directly.
  * STRICT — missing CRITICAL series raise RuntimeError. No silent None.
  * Non-critical series use try/except with None fallback (never raise).
  * Versioned — every snapshot persisted with as_of_date.

v2 additions:
  * ~40 series organised into 6 thematic modules (rates_spreads, real_estate_national,
    mortgage, credit_quality, banking_activity, macro_fundamentals).
  * Each non-scalar series returns 12 months of observations (full curve).
  * Derived signals: trend_direction, delta_12m, delta_12m_pct, transform_result.
  * Regional Case-Shiller series pulled dynamically based on deal geography.
  * ``compute_macro_stress_severity()`` returns a graded severity dict (replaces
    previous string-only implementation) with sub-dimension breakdowns.
  * Backward-compatible: all existing consumers work unchanged.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domains.credit.modules.ai.models import MacroSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------

_FRED_BASE_URL = getattr(settings, "FRED_BASE_URL", None) or "https://api.stlouisfed.org/fred"
_FRED_API_KEY  = getattr(settings, "FRED_API_KEY", None) or ""

# FRED rate limit buffer: sleep between calls when bulk-fetching all series
_FRED_SLEEP_BETWEEN_CALLS = 0.1   # seconds — well within 120 req/min

# NFCI threshold for legacy stress flag (v1 compat)
_NFCI_STRESS_THRESHOLD = 0.0


# ---------------------------------------------------------------------------
#  Series Registry
# ---------------------------------------------------------------------------

FRED_SERIES_REGISTRY: dict[str, dict] = {

    # MODULE 1: RATES & SPREADS
    "DGS10": {
        "label": "10Y Treasury Yield",
        "category": "rates_spreads",
        "frequency": "daily",
        "critical": True,
        "observations": 252,
        "transform": None,
    },
    "DGS2": {
        "label": "2Y Treasury Yield",
        "category": "rates_spreads",
        "frequency": "daily",
        "critical": True,
        "observations": 252,
        "transform": None,
    },
    "BAA10Y": {
        "label": "Baa Corporate Spread (Moody's)",
        "category": "rates_spreads",
        "frequency": "daily",
        "critical": True,
        "observations": 252,
        "transform": None,
    },
    "BAMLH0A0HYM2": {
        "label": "ICE BofA HY Spread (OAS)",
        "category": "rates_spreads",
        "frequency": "daily",
        "critical": False,
        "observations": 252,
        "transform": None,
    },
    "SOFR": {
        "label": "SOFR Overnight Rate",
        "category": "rates_spreads",
        "frequency": "daily",
        "critical": False,
        "observations": 252,
        "transform": None,
    },
    "NFCI": {
        "label": "Chicago Fed NFCI (Financial Conditions)",
        "category": "rates_spreads",
        "frequency": "weekly",
        "critical": True,
        "observations": 52,
        "transform": None,
    },

    # MODULE 2: REAL ESTATE — NATIONAL
    "CSUSHPINSA": {
        "label": "Case-Shiller National HPI (NSA)",
        "category": "real_estate_national",
        "frequency": "monthly",
        "critical": False,
        "observations": 24,
        "transform": "yoy_pct",
    },
    "MSPUS": {
        "label": "Median Sales Price of Houses Sold",
        "category": "real_estate_national",
        "frequency": "quarterly",
        "critical": False,
        "observations": 8,
        "transform": "yoy_pct",
    },
    "HOUST": {
        "label": "Housing Starts (Total, SAAR)",
        "category": "real_estate_national",
        "frequency": "monthly",
        "critical": False,
        "observations": 24,
        "transform": "yoy_pct",
    },
    "PERMIT": {
        "label": "Building Permits (Total, SAAR)",
        "category": "real_estate_national",
        "frequency": "monthly",
        "critical": False,
        "observations": 24,
        "transform": "yoy_pct",
    },
    "EXHOSLUSM495S": {
        "label": "Existing Home Sales",
        "category": "real_estate_national",
        "frequency": "monthly",
        "critical": False,
        "observations": 24,
        "transform": "yoy_pct",
    },
    "MSACSR": {
        "label": "Monthly Supply of Houses (months of inventory)",
        "category": "real_estate_national",
        "frequency": "monthly",
        "critical": False,
        "observations": 24,
        "transform": None,
    },

    # MODULE 3: MORTGAGE
    "MORTGAGE30US": {
        "label": "30-Year Fixed Mortgage Rate",
        "category": "mortgage",
        "frequency": "weekly",
        "critical": False,
        "observations": 52,
        "transform": None,
    },
    "MORTGAGE15US": {
        "label": "15-Year Fixed Mortgage Rate",
        "category": "mortgage",
        "frequency": "weekly",
        "critical": False,
        "observations": 52,
        "transform": None,
    },
    "OBMMIFHA30YF": {
        "label": "FHA 30-Year Fixed Mortgage Rate",
        "category": "mortgage",
        "frequency": "weekly",
        "critical": False,
        "observations": 52,
        "transform": None,
    },
    "DRCCLACBS": {
        "label": "Credit Card Delinquency Rate (commercial banks)",
        "category": "mortgage",
        "frequency": "quarterly",
        "critical": False,
        "observations": 8,
        "transform": None,
    },
    "DRSFRMACBS": {
        "label": "Single-Family Mortgage Delinquency Rate",
        "category": "mortgage",
        "frequency": "quarterly",
        "critical": False,
        "observations": 8,
        "transform": None,
    },
    "DRHMACBS": {
        "label": "Home Equity Loan Delinquency Rate",
        "category": "mortgage",
        "frequency": "quarterly",
        "critical": False,
        "observations": 8,
        "transform": None,
    },

    # MODULE 4: CREDIT QUALITY & DEFAULT
    "DRALACBN": {
        "label": "Delinquency Rate — All Loans & Leases (all banks)",
        "category": "credit_quality",
        "frequency": "quarterly",
        "critical": False,
        "observations": 8,
        "transform": None,
    },
    "NETCIBAL": {
        "label": "Net Charge-Off Rate — All Loans (all banks)",
        "category": "credit_quality",
        "frequency": "quarterly",
        "critical": False,
        "observations": 8,
        "transform": None,
    },
    "CCLACBW027SBOG": {
        "label": "Commercial Real Estate Loans (all commercial banks, $B)",
        "category": "credit_quality",
        "frequency": "weekly",
        "critical": False,
        "observations": 52,
        "transform": "yoy_pct",
    },
    "DRCILNFNQ": {
        "label": "Delinquency Rate — C&I Loans (large banks)",
        "category": "credit_quality",
        "frequency": "quarterly",
        "critical": False,
        "observations": 8,
        "transform": None,
    },

    # MODULE 5: BANKING ACTIVITY
    "TOTLL": {
        "label": "Total Loans & Leases (all commercial banks, $B)",
        "category": "banking_activity",
        "frequency": "weekly",
        "critical": False,
        "observations": 52,
        "transform": "yoy_pct",
    },
    "DPSACBW027SBOG": {
        "label": "Total Deposits (all commercial banks, $B)",
        "category": "banking_activity",
        "frequency": "weekly",
        "critical": False,
        "observations": 52,
        "transform": "yoy_pct",
    },
    "STLFSI4": {
        "label": "St. Louis Fed Financial Stress Index",
        "category": "banking_activity",
        "frequency": "weekly",
        "critical": False,
        "observations": 52,
        "transform": None,
    },
    "WRMFSL": {
        "label": "Money Market Fund Assets (retail, $B)",
        "category": "banking_activity",
        "frequency": "weekly",
        "critical": False,
        "observations": 52,
        "transform": "yoy_pct",
    },

    # MODULE 6: MACRO FUNDAMENTALS
    "CPIAUCSL": {
        "label": "CPI All Urban Consumers (Index)",
        "category": "macro_fundamentals",
        "frequency": "monthly",
        "critical": True,
        "observations": 15,
        "transform": "yoy_pct_cpi",
    },
    "A191RL1Q225SBEA": {
        "label": "Real GDP Growth Rate (QoQ annualized, %)",
        "category": "macro_fundamentals",
        "frequency": "quarterly",
        "critical": False,
        "observations": 8,
        "transform": None,
    },
    "UNRATE": {
        "label": "Unemployment Rate",
        "category": "macro_fundamentals",
        "frequency": "monthly",
        "critical": True,
        "observations": 13,
        "transform": None,
    },
    "USREC": {
        "label": "NBER Recession Indicator",
        "category": "macro_fundamentals",
        "frequency": "monthly",
        "critical": True,
        "observations": 3,
        "transform": None,
    },
    "PAYEMS": {
        "label": "Total Nonfarm Payrolls (thousands)",
        "category": "macro_fundamentals",
        "frequency": "monthly",
        "critical": False,
        "observations": 13,
        "transform": "mom_delta",
    },
    "UMCSENT": {
        "label": "University of Michigan Consumer Sentiment",
        "category": "macro_fundamentals",
        "frequency": "monthly",
        "critical": False,
        "observations": 13,
        "transform": None,
    },
}

# Regional Case-Shiller series — pulled dynamically per deal geography
CASE_SHILLER_METRO_MAP: dict[str, str] = {
    "new_york":      "NYXRSA",
    "los_angeles":   "LXXRSA",
    "miami":         "MFHXRSA",
    "chicago":       "CHXRSA",
    "dallas":        "DAXRSA",
    "houston":       "HIOXRSA",
    "washington_dc": "WDXRSA",
    "boston":        "BOXRSA",
    "atlanta":       "ATXRSA",
    "seattle":       "SEXRSA",
    "phoenix":       "PHXRSA",
    "denver":        "DNXRSA",
    "san_francisco": "SFXRSA",
    "tampa":         "TPXRSA",
    "charlotte":     "CRXRSA",
    "minneapolis":   "MNXRSA",
    "portland":      "POXRSA",
    "san_diego":     "SDXRSA",
    "detroit":       "DEXRSA",
    "cleveland":     "CLXRSA",
}

# Geography resolution — map common deal location strings to metro keys
GEOGRAPHY_TO_METRO: dict[str, str] = {
    # Florida
    "miami": "miami", "miami-dade": "miami", "broward": "miami",
    "palm beach": "miami", "fort lauderdale": "miami", "fl": "miami",
    # New York
    "new york": "new_york", "nyc": "new_york", "manhattan": "new_york",
    "brooklyn": "new_york", "queens": "new_york", "bronx": "new_york",
    "new jersey": "new_york", "ny": "new_york",
    # California
    "los angeles": "los_angeles", "la": "los_angeles", "orange county": "los_angeles",
    "san francisco": "san_francisco", "bay area": "san_francisco",
    "san diego": "san_diego",
    # Texas
    "dallas": "dallas", "fort worth": "dallas", "dfw": "dallas",
    "houston": "houston", "tx": "houston",
    # Other majors
    "chicago": "chicago", "il": "chicago",
    "washington": "washington_dc", "dc": "washington_dc", "virginia": "washington_dc",
    "boston": "boston", "ma": "boston",
    "atlanta": "atlanta", "ga": "atlanta",
    "seattle": "seattle", "wa": "seattle",
    "phoenix": "phoenix", "scottsdale": "phoenix", "az": "phoenix",
    "denver": "denver", "co": "denver",
    "tampa": "tampa",
    "charlotte": "charlotte", "nc": "charlotte",
}


# ---------------------------------------------------------------------------
#  FRED API retrieval (deterministic, no LLM)
# ---------------------------------------------------------------------------


def _fetch_fred_series(
    series_id: str,
    *,
    observation_start: str | None = None,
    limit: int = 10,
) -> list[dict[str, str]]:
    """Fetch recent observations for a FRED series.

    Returns list of {date, value} dicts sorted descending (newest first).
    Raises on HTTP error.  Never fabricates values.
    """
    if not _FRED_API_KEY:
        raise ValueError("FRED_API_KEY not configured — cannot fetch macro data.")

    url = f"{_FRED_BASE_URL}/series/observations"
    params: dict[str, Any] = {
        "series_id": series_id,
        "api_key": _FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    if observation_start:
        params["observation_start"] = observation_start

    response = httpx.get(url, params=params, timeout=30.0)
    response.raise_for_status()

    data = response.json()
    observations = data.get("observations", [])
    return [
        {"date": obs["date"], "value": obs["value"]}
        for obs in observations
        if obs.get("value") not in (None, "", ".")
    ]


def _fetch_latest_strict(series_id: str, *, limit: int = 10) -> float:
    """Get the most recent numeric value for a FRED series.

    Raises ``ValueError`` if no valid observation exists.
    NEVER returns None — fail loudly instead of silently.
    """
    obs = _fetch_fred_series(series_id, limit=limit)
    if not obs:
        raise ValueError(f"No observations returned for FRED series '{series_id}'")
    for o in obs:
        try:
            return float(o["value"])
        except (ValueError, TypeError):
            continue
    raise ValueError(f"No valid numeric value in FRED series '{series_id}'")


def _latest_value(series_id: str, *, limit: int = 10) -> float | None:
    """Backward-compatible lenient latest-value helper for tests/legacy callers."""
    try:
        return _fetch_latest_strict(series_id, limit=limit)
    except Exception:
        return None


def _latest_two_values(
    series_id: str,
    *,
    limit: int = 10,
) -> tuple[float | None, float | None]:
    """Return the two newest numeric observations, or ``(None, None)``."""
    try:
        obs = _fetch_fred_series(series_id, limit=limit)
    except Exception:
        return (None, None)

    values: list[float] = []
    for entry in obs:
        try:
            values.append(float(entry["value"]))
        except (ValueError, TypeError):
            continue
        if len(values) == 2:
            break

    if len(values) < 2:
        return (None, None)
    return (values[0], values[1])


def _compute_yield_curve_2s10s(
    risk_free_10y: float | None,
    risk_free_2y: float | None,
) -> float | None:
    """Compute 10Y minus 2Y Treasury spread."""
    if risk_free_10y is None or risk_free_2y is None:
        return None
    return round(risk_free_10y - risk_free_2y, 4)


def _compute_cpi_yoy(
    current_cpi: float | None,
    prior_cpi: float | None,
) -> float | None:
    """Compute CPI year-over-year percentage change."""
    if current_cpi is None or prior_cpi in (None, 0):
        return None
    return round(((current_cpi / prior_cpi) - 1.0) * 100.0, 4)


def _compute_gdp_growth(
    current_gdp: float | None,
    prior_gdp: float | None,
) -> float | None:
    """Compute annualized quarter-over-quarter GDP growth."""
    if current_gdp is None or prior_gdp in (None, 0):
        return None
    return round((((current_gdp / prior_gdp) ** 4) - 1.0) * 100.0, 4)


# ---------------------------------------------------------------------------
#  Transform functions (deterministic, pure)
# ---------------------------------------------------------------------------

_EMPTY_TRANSFORM: dict[str, Any] = {
    "series": [], "latest": None, "latest_date": None,
    "transform_result": None, "trend_direction": None,
    "delta_12m": None, "delta_12m_pct": None,
}


def _apply_transform(
    series_id: str,
    observations: list[dict],
    transform: str | None,
) -> dict[str, Any]:
    """Apply a transform to a raw list of {date, value} observations.

    Returns a dict with:
      series           -- full curve (list of {date, value})
      latest           -- most recent float value
      latest_date      -- ISO date string of latest observation
      transform_result -- computed derived value (YoY%, MoM delta, etc.)
      trend_direction  -- "rising" | "falling" | "stable"
      delta_12m        -- absolute change latest vs oldest in window
      delta_12m_pct    -- % change latest vs oldest in window

    Observations are assumed sorted descending (newest first), which is
    the default FRED sort order.
    """
    if not observations:
        return dict(_EMPTY_TRANSFORM)

    parsed: list[dict[str, Any]] = []
    for o in observations:
        try:
            parsed.append({"date": o["date"], "value": float(o["value"])})
        except (ValueError, TypeError):
            continue

    if not parsed:
        return dict(_EMPTY_TRANSFORM)

    latest      = parsed[0]["value"]
    latest_date = parsed[0]["date"]

    # delta vs oldest available in window
    delta_12m     = None
    delta_12m_pct = None
    if len(parsed) >= 2:
        oldest = parsed[-1]["value"]
        delta_12m = round(latest - oldest, 4)
        if oldest != 0:
            delta_12m_pct = round((latest / oldest - 1) * 100, 2)

    # trend: 3-obs rolling vs full-window average
    trend_direction = "stable"
    if len(parsed) >= 6:
        recent_avg = sum(p["value"] for p in parsed[:3]) / 3
        full_avg   = sum(p["value"] for p in parsed) / len(parsed)
        if recent_avg > full_avg * 1.02:
            trend_direction = "rising"
        elif recent_avg < full_avg * 0.98:
            trend_direction = "falling"

    # transform_result
    transform_result = None
    if transform == "yoy_pct":
        transform_result = delta_12m_pct
    elif transform == "yoy_pct_cpi":
        if len(parsed) >= 13:
            cpi_now     = parsed[0]["value"]
            cpi_12m_ago = parsed[12]["value"]
            if cpi_12m_ago > 0:
                transform_result = round((cpi_now / cpi_12m_ago - 1) * 100, 2)
    elif transform == "mom_delta":
        if len(parsed) >= 2:
            transform_result = round(parsed[0]["value"] - parsed[1]["value"], 1)

    return {
        "series":           parsed,
        "latest":           latest,
        "latest_date":      latest_date,
        "transform_result": transform_result,
        "trend_direction":  trend_direction,
        "delta_12m":        delta_12m,
        "delta_12m_pct":    delta_12m_pct,
    }


# ---------------------------------------------------------------------------
#  Regional Case-Shiller: dynamic fetch based on deal geography
# ---------------------------------------------------------------------------


def resolve_metro_key(deal_geography: str | None) -> str | None:
    """Resolve a free-form deal geography string to a Case-Shiller metro key.

    Uses substring matching against GEOGRAPHY_TO_METRO.
    Returns metro key (e.g. "miami") or None if unresolvable.
    """
    if not deal_geography:
        return None
    geo_lower = deal_geography.lower()
    for pattern, metro_key in GEOGRAPHY_TO_METRO.items():
        if pattern in geo_lower:
            return metro_key
    return None


def fetch_regional_case_shiller(
    deal_geography: str | None,
    *,
    observations: int = 24,
) -> dict[str, Any] | None:
    """Fetch the regional Case-Shiller HPI series for a deal's geography.

    Returns a dict with: metro_key, fred_series, label + full _apply_transform output.
    Returns None if geography is unresolvable or FRED fetch fails.
    """
    metro_key = resolve_metro_key(deal_geography)
    if not metro_key:
        logger.info("CASE_SHILLER_REGIONAL_NO_MATCH geography=%s", deal_geography)
        return None

    fred_series = CASE_SHILLER_METRO_MAP.get(metro_key)
    if not fred_series:
        return None

    try:
        obs    = _fetch_fred_series(fred_series, limit=observations)
        result = _apply_transform(fred_series, obs, transform="yoy_pct")
        result["metro_key"]   = metro_key
        result["fred_series"] = fred_series
        result["label"]       = f"Case-Shiller HPI — {metro_key.replace('_', ' ').title()}"
        logger.info(
            "CASE_SHILLER_REGIONAL_OK metro=%s series=%s latest=%s trend=%s",
            metro_key, fred_series,
            result.get("latest"),
            result.get("trend_direction"),
        )
        return result
    except Exception as exc:
        logger.warning(
            "CASE_SHILLER_REGIONAL_FAILED metro=%s series=%s error=%s",
            metro_key, fred_series, exc,
        )
        return None


# ---------------------------------------------------------------------------
#  Utilities
# ---------------------------------------------------------------------------


def _snapshot_hash(data: dict[str, Any]) -> str:
    """Deterministic hash of a snapshot for integrity verification."""
    encoded = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


# ---------------------------------------------------------------------------
#  Stress scenario assessment (fully deterministic, no LLM)
# ---------------------------------------------------------------------------


def compute_macro_stress_severity(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compute a graded stress assessment from the expanded macro snapshot.

    Returns:
    {
      "level":              "NONE" | "MILD" | "MODERATE" | "SEVERE",
      "score":              int (0-100),
      "triggers":           list[str],
      "real_estate_stress": "NONE" | "MILD" | "MODERATE" | "SEVERE",
      "credit_stress":      "NONE" | "MILD" | "MODERATE" | "SEVERE",
      "rate_stress":        "NONE" | "MILD" | "MODERATE" | "SEVERE",
    }

    Score scale:
      0-15:  NONE
      16-35: MILD
      36-65: MODERATE
      66+:   SEVERE

    Fully deterministic — no LLM, no randomness.
    """
    score    = 0
    triggers: list[str] = []

    # RECESSION
    if snapshot.get("recession_flag"):
        score += 40
        triggers.append("NBER recession indicator active")

    # FINANCIAL CONDITIONS (NFCI)
    nfci = snapshot.get("financial_conditions_index")
    if nfci is not None:
        if nfci > 1.0:
            score += 25
            triggers.append(f"NFCI severely tight ({nfci:.2f} > 1.0)")
        elif nfci > 0.0:
            score += 10
            triggers.append(f"NFCI above neutral ({nfci:.2f} > 0.0)")

    # YIELD CURVE
    curve = snapshot.get("yield_curve_2s10s")
    if curve is not None:
        if curve < -0.50:
            score += 20
            triggers.append(f"Deep yield curve inversion ({curve:.2f}%)")
        elif curve < 0:
            score += 10
            triggers.append(f"Yield curve inverted ({curve:.2f}%)")

    # CREDIT SPREADS (track separately for rate_stress sub-dim)
    rate_sub_start = score
    baa = snapshot.get("baa_spread")
    if baa is not None:
        if baa > 3.0:
            score += 20
            triggers.append(f"Baa spread elevated ({baa:.2f}% > 3.0%)")
        elif baa > 2.0:
            score += 8
            triggers.append(f"Baa spread above normal ({baa:.2f}%)")

    hy = snapshot.get("hy_spread_proxy")
    if hy is not None:
        if hy > 8.0:
            score += 15
            triggers.append(f"HY spread stressed ({hy:.2f}% > 8.0%)")
        elif hy > 5.0:
            score += 5
            triggers.append(f"HY spread elevated ({hy:.2f}%)")

    rate_sub = score - rate_sub_start

    # REAL ESTATE
    re_score = 0
    re_data  = snapshot.get("real_estate_national", {})
    hpi      = (re_data.get("CSUSHPINSA") or {})
    hpi_yoy  = hpi.get("delta_12m_pct")
    if hpi_yoy is not None:
        if hpi_yoy < -5.0:
            re_score += 20
            triggers.append(f"National HPI declining sharply ({hpi_yoy:.1f}% YoY)")
        elif hpi_yoy < 0:
            re_score += 10
            triggers.append(f"National HPI negative ({hpi_yoy:.1f}% YoY)")

    mtg_data = snapshot.get("mortgage", {})
    mtg_del  = (mtg_data.get("DRSFRMACBS") or {}).get("latest")
    if mtg_del is not None and mtg_del > 4.0:
        re_score += 15
        triggers.append(f"Mortgage delinquency elevated ({mtg_del:.1f}%)")

    score += re_score

    # CREDIT QUALITY
    cq_score = 0
    cq_data  = snapshot.get("credit_quality", {})
    all_del  = (cq_data.get("DRALACBN") or {}).get("latest")
    if all_del is not None and all_del > 2.5:
        cq_score += 10
        triggers.append(f"Overall loan delinquency elevated ({all_del:.1f}%)")

    score += cq_score

    # GRADE
    score = min(score, 100)
    if score <= 15:
        level = "NONE"
    elif score <= 35:
        level = "MILD"
    elif score <= 65:
        level = "MODERATE"
    else:
        level = "SEVERE"

    def _grade(s: int) -> str:
        return "NONE" if s == 0 else ("MILD" if s < 15 else ("MODERATE" if s < 30 else "SEVERE"))

    return {
        "level":              level,
        "score":              score,
        "triggers":           triggers,
        "real_estate_stress": _grade(re_score),
        "credit_stress":      "NONE" if cq_score == 0 else ("MILD" if cq_score < 10 else "MODERATE"),
        "rate_stress":        _grade(rate_sub),
    }


def compute_macro_stress_flag(snapshot: dict[str, Any]) -> bool:
    """Legacy API — preserve simple recession/NFCI threshold behavior.

    Backward-compatible wrapper around compute_macro_stress_severity().
    All existing callers that test the bool flag continue to work.
    """
    if snapshot.get("recession_flag") is True:
        return True

    nfci = snapshot.get("financial_conditions_index")
    if nfci is not None and nfci > _NFCI_STRESS_THRESHOLD:
        return True

    sev = compute_macro_stress_severity(snapshot)
    return sev["level"] in ("MODERATE", "SEVERE")


# ---------------------------------------------------------------------------
#  Legacy snapshot builder (v1 — kept for backward-compat / testing)
# ---------------------------------------------------------------------------


def _build_macro_snapshot_legacy() -> dict[str, Any]:
    """Legacy v1 snapshot builder — 8 scalar series only.

    Kept for testing and fallback.  New code should use
    _build_macro_snapshot_expanded() instead.
    """
    logger.info("MARKET_DATA_FETCH_START (legacy)")

    risk_free_10y  = _fetch_latest_strict("DGS10")
    risk_free_2y   = _fetch_latest_strict("DGS2")
    baa_spread     = _fetch_latest_strict("BAA10Y")
    unemployment   = _fetch_latest_strict("UNRATE")
    financial_cond = _fetch_latest_strict("NFCI")
    recession_raw  = _fetch_latest_strict("USREC")

    # CPI YoY (computed from index levels)
    obs_cpi   = _fetch_fred_series("CPIAUCSL", limit=15)
    valid_cpi = [float(o["value"]) for o in obs_cpi if o["value"] not in ("", ".")]
    if len(valid_cpi) < 13:
        raise ValueError(f"CPIAUCSL: need >=13 monthly obs, got {len(valid_cpi)}")
    cpi_yoy = _compute_cpi_yoy(valid_cpi[0], valid_cpi[12])

    gdp_yoy: float | None = None
    try:
        gdp_yoy = _fetch_latest_strict("A191RL1Q225SBEA")
    except Exception as exc:
        logger.warning("FRED_GDP_YOY_UNAVAILABLE: %s", exc)

    hy_spread_proxy: float | None = None
    try:
        hy_spread_proxy = _fetch_latest_strict("BAMLH0A0HYM2")
    except Exception:
        pass

    sofr_rate: float | None = None
    try:
        sofr_rate = _fetch_latest_strict("SOFR")
    except Exception:
        pass

    yield_curve    = _compute_yield_curve_2s10s(risk_free_10y, risk_free_2y)
    recession_flag = recession_raw >= 1.0

    snapshot: dict[str, Any] = {
        "risk_free_10y":              risk_free_10y,
        "risk_free_2y":               risk_free_2y,
        "yield_curve_2s10s":          yield_curve,
        "baa_spread":                 baa_spread,
        "hy_spread_proxy":            hy_spread_proxy,
        "sofr_rate":                  sofr_rate,
        "base_rate_short":            sofr_rate if sofr_rate is not None else risk_free_2y,
        "cpi_yoy":                    cpi_yoy,
        "gdp_yoy":                    gdp_yoy,
        "unemployment_rate":          unemployment,
        "financial_conditions_index": financial_cond,
        "recession_flag":             recession_flag,
        "as_of_date":                 dt.date.today().isoformat(),
    }

    _CRITICAL = (
        "risk_free_10y", "risk_free_2y", "yield_curve_2s10s",
        "baa_spread", "cpi_yoy", "unemployment_rate",
        "financial_conditions_index", "recession_flag", "base_rate_short",
    )
    missing = [f for f in _CRITICAL if snapshot.get(f) is None]
    if missing:
        raise RuntimeError(
            f"MACRO_SNAPSHOT_INCOMPLETE — critical fields are None: {missing}"
        )
    return snapshot


def _build_macro_snapshot(*, deal_geography: str | None = None) -> dict[str, Any]:
    """Backward-compatible entrypoint used by tests and cache orchestration."""
    return _build_macro_snapshot_expanded(deal_geography=deal_geography)


# ---------------------------------------------------------------------------
#  Expanded snapshot builder (v2 — full time-series)
# ---------------------------------------------------------------------------


def _build_macro_snapshot_expanded(
    *,
    deal_geography: str | None = None,
) -> dict[str, Any]:
    """Fetch all FRED series from FRED_SERIES_REGISTRY and build expanded snapshot.

    Each series returns a full 12-month time-series curve + derived signals.
    Critical series raise RuntimeError on failure; non-critical use None fallback.

    deal_geography: optional free-form location string for regional Case-Shiller.
    Note: regional data is NOT persisted in the base cache (deal-specific).
    """
    logger.info("MACRO_SNAPSHOT_EXPANDED_START")

    result: dict[str, Any] = {
        "rates_spreads":        {},
        "real_estate_national": {},
        "mortgage":             {},
        "credit_quality":       {},
        "banking_activity":     {},
        "macro_fundamentals":   {},
        "regional":             {},
        "as_of_date":           dt.date.today().isoformat(),
        "schema_version":       "v2_expanded",
    }

    # Fetch all registry series
    for series_id, entry in FRED_SERIES_REGISTRY.items():
        category    = entry["category"]
        is_critical = entry["critical"]
        n_obs       = entry["observations"]
        transform   = entry["transform"]

        try:
            obs         = _fetch_fred_series(series_id, limit=n_obs)
            transformed = _apply_transform(series_id, obs, transform)
            transformed["label"]       = entry["label"]
            transformed["fred_series"] = series_id
            result[category][series_id] = transformed

            logger.debug(
                "FRED_SERIES_OK series=%s latest=%s trend=%s",
                series_id, transformed.get("latest"), transformed.get("trend_direction"),
            )
        except Exception as exc:
            if is_critical:
                raise RuntimeError(
                    f"MACRO_SNAPSHOT_CRITICAL_FAILURE — series '{series_id}' "
                    f"({entry['label']}) failed: {exc}"
                ) from exc
            else:
                result[category][series_id] = {
                    "series": [], "latest": None, "latest_date": None,
                    "transform_result": None, "trend_direction": None,
                    "delta_12m": None, "delta_12m_pct": None,
                    "label":       entry["label"],
                    "fred_series": series_id,
                    "error":       str(exc),
                }
                logger.warning("FRED_SERIES_FAILED series=%s error=%s", series_id, exc)

        # Rate-limit buffer (120 req/min; ~35 calls — well within limit)
        time.sleep(_FRED_SLEEP_BETWEEN_CALLS)

    # Regional Case-Shiller (optional, deal-specific)
    if deal_geography:
        regional = fetch_regional_case_shiller(deal_geography, observations=24)
        if regional:
            result["regional"]["case_shiller_metro"] = regional
            result["regional"]["national_vs_metro_delta"] = None
            national  = result["real_estate_national"].get("CSUSHPINSA", {})
            nat_yoy   = national.get("delta_12m_pct")
            metro_yoy = regional.get("delta_12m_pct")
            if nat_yoy is not None and metro_yoy is not None:
                result["regional"]["national_vs_metro_delta"] = round(
                    metro_yoy - nat_yoy, 2
                )

    # Compute backward-compatible scalar fields
    rates = result["rates_spreads"]
    macro = result["macro_fundamentals"]

    def _latest(cat: dict, sid: str) -> float | None:
        return (cat.get(sid) or {}).get("latest")

    risk_free_10y = _latest(rates, "DGS10")
    risk_free_2y  = _latest(rates, "DGS2")
    baa_spread    = _latest(rates, "BAA10Y")
    sofr_rate     = _latest(rates, "SOFR")
    nfci          = _latest(rates, "NFCI")
    recession_raw = _latest(macro, "USREC")
    unemployment  = _latest(macro, "UNRATE")
    cpi_yoy       = (macro.get("CPIAUCSL") or {}).get("transform_result")
    gdp_yoy       = _latest(macro, "A191RL1Q225SBEA")
    hy_spread     = _latest(rates, "BAMLH0A0HYM2")

    # Validate critical scalars
    _CRITICAL_SCALARS = {
        "risk_free_10y":              risk_free_10y,
        "risk_free_2y":               risk_free_2y,
        "baa_spread":                 baa_spread,
        "unemployment_rate":          unemployment,
        "financial_conditions_index": nfci,
        "cpi_yoy":                    cpi_yoy,
    }
    missing = [k for k, v in _CRITICAL_SCALARS.items() if v is None]
    if missing:
        raise RuntimeError(
            f"MACRO_SNAPSHOT_INCOMPLETE — critical scalars None after fetch: {missing}"
        )

    risk_free_10y_value = risk_free_10y
    risk_free_2y_value = risk_free_2y
    assert risk_free_10y_value is not None
    assert risk_free_2y_value is not None
    base_rate      = sofr_rate if sofr_rate is not None else risk_free_2y
    yield_curve    = round(risk_free_10y_value - risk_free_2y_value, 4)
    recession_flag = (recession_raw or 0) >= 1.0

    # Inject flat scalars at top level for backward compatibility
    result.update({
        "risk_free_10y":              risk_free_10y,
        "risk_free_2y":               risk_free_2y,
        "yield_curve_2s10s":          yield_curve,
        "baa_spread":                 baa_spread,
        "hy_spread_proxy":            hy_spread,
        "sofr_rate":                  sofr_rate,
        "base_rate_short":            base_rate,
        "cpi_yoy":                    cpi_yoy,
        "gdp_yoy":                    gdp_yoy,
        "unemployment_rate":          unemployment,
        "financial_conditions_index": nfci,
        "recession_flag":             recession_flag,
    })

    # Embed stress severity into snapshot (Task 9)
    result["stress_severity"] = compute_macro_stress_severity(result)

    # Summary counters for logging
    _MODULE_KEYS = [
        "rates_spreads", "real_estate_national", "mortgage",
        "credit_quality", "banking_activity", "macro_fundamentals",
    ]
    series_ok     = sum(1 for k in _MODULE_KEYS for s in result[k].values() if s.get("latest") is not None)
    series_failed = sum(1 for k in _MODULE_KEYS for s in result[k].values() if s.get("latest") is None)

    logger.info(
        "MACRO_SNAPSHOT_EXPANDED_COMPLETE as_of=%s hash=%s series_ok=%d series_failed=%d stress=%s",
        result["as_of_date"],
        _snapshot_hash(result),
        series_ok,
        series_failed,
        result["stress_severity"]["level"],
    )

    return result


# ---------------------------------------------------------------------------
#  Public API — daily-cached macro snapshot
# ---------------------------------------------------------------------------


def get_macro_snapshot(
    db: Session,
    *,
    force_refresh: bool = False,
    deal_geography: str | None = None,
) -> dict[str, Any]:
    """Return today's macro snapshot, fetching from FRED if not cached.

    NEW in v2: deal_geography triggers regional Case-Shiller fetch.
    Regional data is NOT cached (deal-specific) — always fetched live
    and merged into the cached base snapshot at runtime.

    Cache logic:
      1. Check macro_snapshots table for today's date.
      2. If found AND populated AND valid schema -> return cached.
         If deal_geography -> merge regional data before returning.
      3. If found but all-null or legacy schema (no schema_version key) -> delete + refetch.
      4. If not found -> build expanded snapshot, persist base, return.
      5. force_refresh -> always delete today's cache + refetch.

    Backward compatible: callers without deal_geography get the same
    behavior, with additional time-series fields in the v2 snapshot.
    """
    today = dt.date.today()

    # Check / invalidate cache
    cached = db.execute(
        select(MacroSnapshot).where(MacroSnapshot.as_of_date == today)
    ).scalar_one_or_none()

    _VALUE_KEYS = (
        "risk_free_10y", "risk_free_2y", "baa_spread",
        "unemployment_rate", "financial_conditions_index",
    )

    if cached is not None:
        data             = cached.data_json or {}
        is_empty = all(data.get(k) is None for k in _VALUE_KEYS)

        if force_refresh or is_empty:
            reason = "force_refresh" if force_refresh else "all_null_poisoned_cache"
            logger.warning(
                "MARKET_DATA_CACHE_INVALIDATED as_of=%s reason=%s",
                today.isoformat(), reason,
            )
            with db.begin_nested():
                db.delete(cached)
            cached = None
        else:
            logger.info("MARKET_DATA_CACHE_HIT as_of=%s", today.isoformat())
            base_snapshot = data
            # Merge deal-specific regional data (never stored in cache)
            if deal_geography:
                regional = fetch_regional_case_shiller(deal_geography, observations=24)
                if regional:
                    base_snapshot = dict(base_snapshot)
                    base_snapshot["regional"] = {"case_shiller_metro": regional}
                    nat_yoy = (
                        (base_snapshot.get("real_estate_national") or {})
                        .get("CSUSHPINSA", {})
                        .get("delta_12m_pct")
                    )
                    metro_yoy = regional.get("delta_12m_pct")
                    if nat_yoy is not None and metro_yoy is not None:
                        base_snapshot["regional"]["national_vs_metro_delta"] = round(
                            metro_yoy - nat_yoy, 2
                        )
            return base_snapshot

    # Fetch from FRED using the backward-compatible builder entrypoint.
    # Build base snapshot WITHOUT regional (base is deal-agnostic/cacheable)
    try:
        snapshot = _build_macro_snapshot(deal_geography=None)
    except Exception as exc:
        fallback = db.execute(
            select(MacroSnapshot)
            .where(MacroSnapshot.as_of_date < today)
            .order_by(MacroSnapshot.as_of_date.desc())
        ).scalar_one_or_none()
        if fallback and fallback.data_json:
            logger.warning(
                "MARKET_DATA_FALLBACK_CACHE_HIT as_of=%s fallback_as_of=%s error=%s",
                today.isoformat(),
                fallback.as_of_date.isoformat(),
                exc,
            )
            snapshot = fallback.data_json
        else:
            raise ValueError("FRED failed and no cached macro snapshot available") from exc

    # Persist base snapshot
    new_snapshot = MacroSnapshot(as_of_date=today, data_json=snapshot)
    try:
        with db.begin_nested():
            db.add(new_snapshot)
    except Exception:
        db.rollback()
        cached = db.execute(
            select(MacroSnapshot).where(MacroSnapshot.as_of_date == today)
        ).scalar_one_or_none()
        if cached and cached.data_json:
            logger.info("MARKET_DATA_RACE_RECOVERED as_of=%s", today.isoformat())
            snapshot = cached.data_json
        else:
            logger.warning("MARKET_DATA_PERSIST_FAILED as_of=%s", today.isoformat())

    logger.info(
        "MARKET_DATA_PERSISTED as_of=%s hash=%s",
        today.isoformat(), _snapshot_hash(snapshot),
    )

    # Merge regional AFTER persisting (deal-specific, not stored)
    if deal_geography:
        regional = fetch_regional_case_shiller(deal_geography, observations=24)
        if regional:
            snapshot = dict(snapshot)
            snapshot["regional"] = {"case_shiller_metro": regional}
            nat_yoy = (
                (snapshot.get("real_estate_national") or {})
                .get("CSUSHPINSA", {})
                .get("delta_12m_pct")
            )
            metro_yoy = regional.get("delta_12m_pct")
            if nat_yoy is not None and metro_yoy is not None:
                snapshot["regional"]["national_vs_metro_delta"] = round(
                    metro_yoy - nat_yoy, 2
                )

    return snapshot
