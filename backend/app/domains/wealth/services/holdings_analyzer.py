"""
Holdings composition analyzer.

Pure compute function: given a list of holdings from sec_nport_holdings for a
single fund at a single report_date, produce a HoldingsAnalysis summary with
asset mix, sector concentration, geography, and style indicators.

Used by Layer 0 of the classification cascade and by StyleDriftAnalyzer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

# ── Asset class bucketing (N-PORT codes → canonical buckets) ──
ASSET_CLASS_BUCKETS = {
    # Equity
    "EC": "equity",      # Common stock
    "EP": "equity",      # Preferred stock
    # Fixed Income
    "DBT": "fixed_income",  # Corporate debt
    "CORP": "fixed_income",
    "UST": "fixed_income",  # US Treasury
    "USGA": "fixed_income",  # US Gov Agency
    "USGSE": "fixed_income",  # US Gov Sponsored Enterprise
    "MUN": "fixed_income",  # Municipal
    # Short-term / cash
    "ST": "cash",          # Short-term securities
    "RA": "cash",          # Repurchase agreements
    # Derivatives
    "DE": "derivatives",    # Equity derivatives
    "DCR": "derivatives",   # Credit derivatives
    "DFE": "derivatives",   # FX derivatives
    "DIR": "derivatives",   # Interest rate derivatives
    "DCO": "derivatives",   # Commodity derivatives
    # Other
    "OT": "other",
    "OTHER": "other",
    "RF": "other",         # Restricted foreign
    "PF": "equity",        # Preferred foreign (treat as equity)
    "NUSS": "fixed_income",  # Non-US sovereign
}


@dataclass(frozen=True)
class HoldingsAnalysis:
    """Fund composition summary from N-PORT holdings."""

    as_of_date: date
    n_holdings: int
    total_nav_covered_pct: float  # sum of pct_of_nav (should be ~100)

    # Asset mix (percentages 0-100, sum to ~100)
    equity_pct: float
    fixed_income_pct: float
    cash_pct: float
    derivatives_pct: float
    other_pct: float

    # Sector concentration (equity-weighted)
    top_sectors: list[tuple[str, float]]  # [(sector, pct_of_equity), ...]
    sector_hhi: float  # Herfindahl: sum(pct**2), 0-10000, higher = more concentrated
    distinct_sectors: int

    # Geography (derived from ISIN[0:2])
    geography_us_pct: float
    geography_europe_pct: float
    geography_asia_developed_pct: float
    geography_em_pct: float
    geography_other_pct: float

    # Style indicators (equity-dominant funds only)
    growth_tilt: float | None = None  # -1 (value) to +1 (growth), None if not equity
    size_tilt: float | None = None    # -1 (small) to +1 (large), None if not equity

    # Derivative signatures (for Global Macro detection)
    derivatives_fx_pct: float = 0.0
    derivatives_ir_pct: float = 0.0
    derivatives_commodity_pct: float = 0.0
    derivatives_equity_pct: float = 0.0
    derivatives_credit_pct: float = 0.0

    # Currency exposure (non-USD)
    non_usd_currency_pct: float = 0.0

    # Metadata
    coverage_quality: str = "unknown"  # "high" (>=90), "medium" (70-90), "low" (<70)


def analyze_holdings(holdings: list[dict[str, Any]]) -> HoldingsAnalysis:
    """Compute composition summary from N-PORT holdings rows.

    Args:
        holdings: list of dicts with keys matching SecNportHolding columns.
                  Each dict must have: asset_class, pct_of_nav, sector,
                  isin (nullable), currency (nullable), report_date.

    Returns:
        HoldingsAnalysis frozen dataclass.
    """
    if not holdings:
        return _empty_analysis()

    as_of = max(h["report_date"] for h in holdings)
    n = len(holdings)

    total_pct = sum(float(h.get("pct_of_nav") or 0) for h in holdings)
    coverage = total_pct  # proxy for data quality

    bucket_pcts: dict[str, float] = {
        "equity": 0.0,
        "fixed_income": 0.0,
        "cash": 0.0,
        "derivatives": 0.0,
        "other": 0.0,
    }

    derivative_subtypes: dict[str, float] = {
        "DE": 0.0, "DCR": 0.0, "DFE": 0.0, "DIR": 0.0, "DCO": 0.0,
    }

    for h in holdings:
        pct = float(h.get("pct_of_nav") or 0)
        ac = (h.get("asset_class") or "").upper().strip()
        bucket = ASSET_CLASS_BUCKETS.get(ac, "other")
        bucket_pcts[bucket] += pct
        if ac in derivative_subtypes:
            derivative_subtypes[ac] += pct

    # Normalize to 100 (in case coverage < 100)
    scale = 100.0 / coverage if coverage > 0 else 1.0

    equity_pct = bucket_pcts["equity"] * scale
    fi_pct = bucket_pcts["fixed_income"] * scale
    cash_pct = bucket_pcts["cash"] * scale
    deriv_pct = bucket_pcts["derivatives"] * scale
    other_pct = bucket_pcts["other"] * scale

    # Sector concentration (within equity only)
    sector_weights: dict[str, float] = {}
    for h in holdings:
        ac = (h.get("asset_class") or "").upper().strip()
        if ASSET_CLASS_BUCKETS.get(ac) != "equity":
            continue
        sector = (h.get("sector") or "Unknown").strip() or "Unknown"
        sector_weights[sector] = sector_weights.get(sector, 0.0) + float(
            h.get("pct_of_nav") or 0
        )

    total_equity = sum(sector_weights.values())
    if total_equity > 0:
        sector_pcts = {s: (v / total_equity) * 100 for s, v in sector_weights.items()}
        top_sectors = sorted(sector_pcts.items(), key=lambda x: -x[1])[:5]
        hhi = sum(p * p for p in sector_pcts.values())
    else:
        sector_pcts = {}
        top_sectors = []
        hhi = 0.0

    # Geography via ISIN[0:2]
    geo_buckets = {"us": 0.0, "europe": 0.0, "asia_dev": 0.0, "em": 0.0, "other": 0.0}
    for h in holdings:
        pct = float(h.get("pct_of_nav") or 0)
        iso = _country_from_isin(h.get("isin"))
        geo_buckets[_geo_bucket(iso)] += pct

    if coverage > 0:
        geo_us = geo_buckets["us"] * scale
        geo_eu = geo_buckets["europe"] * scale
        geo_asia = geo_buckets["asia_dev"] * scale
        geo_em = geo_buckets["em"] * scale
        geo_other = geo_buckets["other"] * scale
    else:
        geo_us = geo_eu = geo_asia = geo_em = geo_other = 0.0

    # Style tilts (only compute for equity-dominant funds)
    growth_tilt: float | None = None
    size_tilt: float | None = None
    if equity_pct >= 50.0:
        growth_tilt = _estimate_growth_tilt(sector_pcts) if total_equity > 0 else None
        size_tilt = _estimate_size_tilt(holdings)

    # Non-USD currency exposure
    non_usd_raw = 0.0
    for h in holdings:
        curr = (h.get("currency") or "").upper().strip()
        if curr and curr != "USD":
            non_usd_raw += float(h.get("pct_of_nav") or 0)
    non_usd_pct = non_usd_raw * scale if coverage > 0 else 0.0

    # Coverage quality
    if coverage >= 90:
        qual = "high"
    elif coverage >= 70:
        qual = "medium"
    else:
        qual = "low"

    return HoldingsAnalysis(
        as_of_date=as_of,
        n_holdings=n,
        total_nav_covered_pct=coverage,
        equity_pct=equity_pct,
        fixed_income_pct=fi_pct,
        cash_pct=cash_pct,
        derivatives_pct=deriv_pct,
        other_pct=other_pct,
        top_sectors=top_sectors,
        sector_hhi=hhi,
        distinct_sectors=len(sector_weights),
        geography_us_pct=geo_us,
        geography_europe_pct=geo_eu,
        geography_asia_developed_pct=geo_asia,
        geography_em_pct=geo_em,
        geography_other_pct=geo_other,
        growth_tilt=growth_tilt,
        size_tilt=size_tilt,
        derivatives_fx_pct=derivative_subtypes["DFE"] * scale,
        derivatives_ir_pct=derivative_subtypes["DIR"] * scale,
        derivatives_commodity_pct=derivative_subtypes["DCO"] * scale,
        derivatives_equity_pct=derivative_subtypes["DE"] * scale,
        derivatives_credit_pct=derivative_subtypes["DCR"] * scale,
        non_usd_currency_pct=non_usd_pct,
        coverage_quality=qual,
    )


def _country_from_isin(isin: str | None) -> str:
    if not isin or len(isin) < 2:
        return "XX"
    return isin[:2].upper()


EUROPE_ISO = {
    "DE", "FR", "IT", "ES", "GB", "NL", "CH", "SE", "DK", "FI", "NO",
    "BE", "AT", "IE", "LU", "PT", "PL", "CZ", "HU", "GR", "LI",
}
ASIA_DEV_ISO = {"JP", "AU", "HK", "SG", "KR", "NZ", "TW"}
EM_ISO = {
    "CN", "IN", "BR", "MX", "RU", "TR", "ZA", "ID", "MY", "TH",
    "PH", "VN", "PK", "BD", "AR", "CL", "CO", "PE", "EG", "KE",
    "NG", "UA", "AE", "SA", "QA", "KW", "IL",
}


def _geo_bucket(iso: str) -> str:
    if iso == "US":
        return "us"
    if iso in EUROPE_ISO:
        return "europe"
    if iso in ASIA_DEV_ISO:
        return "asia_dev"
    if iso in EM_ISO:
        return "em"
    return "other"


# Sectors typically classified as "growth" in GICS
GROWTH_SECTORS = {
    "Technology", "Information Technology", "Communication Services",
    "Consumer Discretionary", "Healthcare", "Health Care",
}
VALUE_SECTORS = {
    "Financials", "Energy", "Utilities", "Materials", "Consumer Staples",
    "Real Estate", "Industrials",
}


def _estimate_growth_tilt(sector_pcts: dict[str, float]) -> float:
    """Estimate growth tilt from sector concentration.

    Returns -1 (pure value) to +1 (pure growth). Neutral = 0.
    """
    growth_w = sum(v for s, v in sector_pcts.items() if s in GROWTH_SECTORS)
    value_w = sum(v for s, v in sector_pcts.items() if s in VALUE_SECTORS)
    total = growth_w + value_w
    if total == 0:
        return 0.0
    return (growth_w - value_w) / total


def _estimate_size_tilt(holdings: list[dict[str, Any]]) -> float:
    """Estimate size tilt without market cap data.

    Proxy: top-10 concentration. Larger top-10 share suggests large-cap bias.
    Returns -1 (small) to +1 (large). Neutral = 0.
    """
    equity_pcts = [
        float(h.get("pct_of_nav") or 0)
        for h in holdings
        if ASSET_CLASS_BUCKETS.get((h.get("asset_class") or "").upper()) == "equity"
    ]
    if len(equity_pcts) < 5:
        return 0.0
    sorted_pcts = sorted(equity_pcts, reverse=True)
    top10_pct = sum(sorted_pcts[:10])
    if top10_pct <= 10:
        return -1.0
    if top10_pct >= 60:
        return 1.0
    return (top10_pct - 35) / 25


def _empty_analysis() -> HoldingsAnalysis:
    return HoldingsAnalysis(
        as_of_date=date.today(),
        n_holdings=0,
        total_nav_covered_pct=0.0,
        equity_pct=0.0, fixed_income_pct=0.0, cash_pct=0.0,
        derivatives_pct=0.0, other_pct=0.0,
        top_sectors=[], sector_hhi=0.0, distinct_sectors=0,
        geography_us_pct=0.0, geography_europe_pct=0.0,
        geography_asia_developed_pct=0.0, geography_em_pct=0.0,
        geography_other_pct=0.0,
        coverage_quality="unknown",
    )
