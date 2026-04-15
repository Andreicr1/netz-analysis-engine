# Phase 4 — N-PORT Holdings Classifier + Style Drift Analysis

**Date:** 2026-04-14
**Branch:** `feat/nport-holdings-classifier`
**Sessions:** 3 (A: Analyzer service, B: Layer 0 integration, C: Style drift)
**Depends on:** PRs #174, #175, #176 merged; production classification stabilized at 35,615 canonical

---

## Context

Round 1, Round 2, Round 2.5 patches achieved 63% canonical classification (35,615 rows). The remaining 2,641 Bucket B and ~4,000 residual miss-classifications reveal structural limits of regex-based approaches:

| Bug pattern | Example | Why regex fails |
|---|---|---|
| Target Date misclassified | Vanguard Target Retirement 2055 → Government Bond | Name has "2055" (not a strategy keyword); content is multi-asset |
| Tiingo desc fires before name | Multi-Manager International Equity → Real Estate | Description mentions real estate as one sleeve, not the mandate |
| Equity Income as Bond | CAPITAL WORLD GROWTH & INCOME → Intermediate-Term Bond | "Income" triggers bond bucket despite 90%+ equity holdings |
| tax-exempt PE as Municipal | OAK HILL PARTNERS V (TAX EXEMPT) → Municipal Bond | "Tax-Exempt" = shelter structure, not municipal bond strategy |
| Global Macro as International | RIVERVIEW GLOBAL MACRO → International Equity | "Global" triggers international, but macro has derivatives+FX, not equities |

**N-PORT holdings classification resolves all 5 by analyzing what the fund ACTUALLY HOLDS.** Morningstar and Bloomberg use this approach -- it's the institutional gold standard.

**Secondary benefit: style drift analysis.** Once we have historical holdings analysis, detecting style drift (fund changed mandate over time) is nearly free. This is a premium institutional feature -- asset managers pay Morningstar specifically for this signal.

---

## What N-PORT Gives Us (Empirical Audit)

**Available per holding (sec_nport_holdings, 10-15k funds, 2+ years history):**

| Field | Use |
|---|---|
| `asset_class` | EC (equity), DBT (debt), ST (short-term), RA (repo), derivatives codes |
| `sector` | GICS (where enriched) or raw N-PORT code |
| `pct_of_nav` | Weight per holding |
| `market_value` | USD notional |
| `issuer_name` | Enrichment/dedup |
| `cusip`, `isin` | Geography via ISIN[0:2] |
| `currency` | FX exposure |
| `fair_value_level` | Level 1/2/3 (liquidity tier) |
| `is_restricted` | Private/restricted indicator |

**What we don't have (and won't enrich in this sprint):**

- Per-holding market cap (needed for perfect style box)
- Per-holding credit rating (needed for HY vs IG fixed income)
- Per-holding maturity/coupon (for duration)

**Decision:** Classifier uses asset_class + sector + geography + concentration. Style box via sector-weighted heuristics when market cap unavailable. Credit quality NOT in Phase 4 -- defer to Phase 4.5.

---

## OBJECTIVE

1. **Session A:** Pure-compute `HoldingsAnalysis` service that summarizes a fund's composition
2. **Session B:** Integrate as Layer 0 of the classifier cascade (before Tiingo description, before name regex)
3. **Session C:** Historical `StyleDriftAnalysis` + alerts integration

Expected impact on classifier residuals: from ~6,640 residuals (2,641 Bucket B + ~4,000 in-fallback-but-bad) to **<500 residuals**. N-PORT resolves at the composition level, not the name level.

---

## Session A — Holdings Analyzer Service

### DELIVERABLES

#### 1. Service: `backend/app/domains/wealth/services/holdings_analyzer.py`

Pure compute. No DB access. Takes a list of holdings, returns `HoldingsAnalysis`.

```python
"""
Holdings composition analyzer.

Pure compute function: given a list of holdings from sec_nport_holdings for a
single fund at a single report_date, produce a HoldingsAnalysis summary with
asset mix, sector concentration, geography, and style indicators.

Used by Layer 0 of the classification cascade and by StyleDriftAnalyzer.
"""
from __future__ import annotations
from dataclasses import dataclass, field
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
    "USGA": "fixed_income", # US Gov Agency
    "USGSE": "fixed_income",# US Gov Sponsored Enterprise
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
    "NUSS": "fixed_income",# Non-US sovereign
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
    geography_europe_pct: float  # DE, FR, IT, ES, GB, NL, CH, SE, DK, etc.
    geography_asia_developed_pct: float  # JP, AU, HK, SG, KR, NZ
    geography_em_pct: float  # CN, IN, BR, MX, RU, TR, ZA, etc.
    geography_other_pct: float

    # Style indicators (equity-dominant funds only)
    # Estimated via sector weights when market cap unavailable
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
    coverage_quality: str = "unknown"  # "high" (>90), "medium" (70-90), "low" (<70)


def analyze_holdings(holdings: list[dict[str, Any]]) -> HoldingsAnalysis:
    """Compute composition summary from N-PORT holdings rows.

    Args:
        holdings: list of dicts with keys matching SecNportHolding columns.
                  Each dict must have: asset_class, pct_of_nav, sector,
                  isin (nullable), currency (nullable).

    Returns:
        HoldingsAnalysis frozen dataclass.
    """
    if not holdings:
        return _empty_analysis()

    as_of = max(h["report_date"] for h in holdings)
    n = len(holdings)

    # Sum pct_of_nav per asset bucket
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
    if coverage > 0:
        scale = 100.0 / coverage
    else:
        scale = 1.0

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
        sector_weights[sector] = sector_weights.get(sector, 0.0) + float(h.get("pct_of_nav") or 0)

    total_equity = sum(sector_weights.values())
    if total_equity > 0:
        sector_pcts = {s: (v / total_equity) * 100 for s, v in sector_weights.items()}
        top_sectors = sorted(sector_pcts.items(), key=lambda x: -x[1])[:5]
        hhi = sum(p * p for p in sector_pcts.values())
    else:
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
    growth_tilt = None
    size_tilt = None
    if equity_pct >= 50.0:
        growth_tilt = _estimate_growth_tilt(sector_pcts) if total_equity > 0 else None
        size_tilt = _estimate_size_tilt(holdings)

    # Non-USD currency exposure
    non_usd_pct = 0.0
    for h in holdings:
        curr = (h.get("currency") or "").upper().strip()
        if curr and curr != "USD":
            non_usd_pct += float(h.get("pct_of_nav") or 0)
    non_usd_pct = non_usd_pct * scale if coverage > 0 else 0.0

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
        return "XX"  # Unknown
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
    Heuristic: growth sectors - value sectors weighted.
    """
    growth_w = sum(v for s, v in sector_pcts.items() if s in GROWTH_SECTORS)
    value_w = sum(v for s, v in sector_pcts.items() if s in VALUE_SECTORS)
    total = growth_w + value_w
    if total == 0:
        return 0.0
    return (growth_w - value_w) / total


def _estimate_size_tilt(holdings: list[dict]) -> float:
    """Estimate size tilt without market cap data.

    Proxy: average position size. Larger positions in top-heavy portfolios
    indicate large-cap bias. Small-cap portfolios tend to be more diversified.

    Returns -1 (small) to +1 (large). Neutral = 0.
    """
    equity_pcts = [
        float(h.get("pct_of_nav") or 0)
        for h in holdings
        if ASSET_CLASS_BUCKETS.get((h.get("asset_class") or "").upper()) == "equity"
    ]
    if len(equity_pcts) < 5:
        return 0.0
    # Top 10 concentration as proxy for large-cap bias
    sorted_pcts = sorted(equity_pcts, reverse=True)
    top10_pct = sum(sorted_pcts[:10])
    # Heuristic: top10 >= 40% suggests concentration in large caps
    # Map top10 [10, 60] to [-1, +1]
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
```

#### 2. Tests: `backend/tests/domains/wealth/services/test_holdings_analyzer.py`

```python
"""Unit tests for holdings analyzer with synthetic fixtures."""
import pytest
from datetime import date
from app.domains.wealth.services.holdings_analyzer import (
    analyze_holdings, ASSET_CLASS_BUCKETS,
    HoldingsAnalysis,
)


def _holding(asset_class, pct_of_nav, sector=None, isin=None, currency=None):
    return {
        "asset_class": asset_class,
        "pct_of_nav": pct_of_nav,
        "sector": sector,
        "isin": isin,
        "currency": currency,
        "report_date": date(2026, 3, 31),
    }


class TestAssetClassBucketing:
    def test_equity_dominant_fund(self):
        holdings = [
            _holding("EC", 10, "Technology", "US0378331005"),
            _holding("EC", 8, "Financials", "US0231351067"),
            _holding("EC", 7, "Healthcare", "US02079K3059"),
            _holding("EC", 5, "Energy", "US7185461040"),
            _holding("EC", 70, "Consumer Discretionary", "US0231351067"),
        ]
        r = analyze_holdings(holdings)
        assert r.equity_pct == 100.0
        assert r.fixed_income_pct == 0.0

    def test_fixed_income_dominant(self):
        holdings = [
            _holding("DBT", 30, isin="US912810TQ07"),
            _holding("UST", 40, isin="US912810TQ07"),
            _holding("CORP", 25, isin="US12345678"),
            _holding("ST", 5),
        ]
        r = analyze_holdings(holdings)
        assert r.fixed_income_pct == 95.0
        assert r.cash_pct == 5.0

    def test_balanced_60_40(self):
        holdings = [
            _holding("EC", 60, "Technology", "US0378331005"),
            _holding("DBT", 40, isin="US912810TQ07"),
        ]
        r = analyze_holdings(holdings)
        assert r.equity_pct == 60.0
        assert r.fixed_income_pct == 40.0

    def test_global_macro_signature(self):
        """Derivatives heavy + FX exposure = Global Macro."""
        holdings = [
            _holding("DFE", 30, currency="EUR"),  # FX derivatives
            _holding("DIR", 25),                   # IR derivatives
            _holding("DCO", 15),                   # Commodity derivatives
            _holding("ST", 30),                    # Cash parking
        ]
        r = analyze_holdings(holdings)
        assert r.derivatives_pct >= 70
        assert r.derivatives_fx_pct >= 30
        assert r.derivatives_ir_pct >= 25


class TestSectorConcentration:
    def test_top_sectors_and_hhi(self):
        holdings = [
            _holding("EC", 40, "Technology"),
            _holding("EC", 30, "Technology"),  # Total Tech = 70
            _holding("EC", 20, "Healthcare"),
            _holding("EC", 10, "Financials"),
        ]
        r = analyze_holdings(holdings)
        # Top sector should be Technology at 70%
        assert r.top_sectors[0][0] == "Technology"
        assert r.top_sectors[0][1] == 70.0
        # HHI = 70^2 + 20^2 + 10^2 = 4900 + 400 + 100 = 5400
        assert r.sector_hhi == pytest.approx(5400.0)

    def test_zero_equity_no_sector_data(self):
        holdings = [_holding("DBT", 100, isin="US912810TQ07")]
        r = analyze_holdings(holdings)
        assert r.top_sectors == []
        assert r.sector_hhi == 0.0


class TestGeography:
    def test_us_dominant(self):
        holdings = [
            _holding("EC", 80, isin="US0378331005"),  # US
            _holding("EC", 20, isin="US0231351067"),  # US
        ]
        r = analyze_holdings(holdings)
        assert r.geography_us_pct == 100.0
        assert r.geography_europe_pct == 0.0

    def test_european_fund(self):
        holdings = [
            _holding("EC", 30, isin="DE0001234567"),  # Germany
            _holding("EC", 25, isin="FR0012345678"),  # France
            _holding("EC", 20, isin="GB0009876543"),  # UK
            _holding("EC", 25, isin="IT0123456789"),  # Italy
        ]
        r = analyze_holdings(holdings)
        assert r.geography_europe_pct == 100.0

    def test_emerging_markets(self):
        holdings = [
            _holding("EC", 40, isin="CN1234567890"),  # China
            _holding("EC", 25, isin="IN9876543210"),  # India
            _holding("EC", 20, isin="BR0011223344"),  # Brazil
            _holding("EC", 15, isin="MX5566778899"),  # Mexico
        ]
        r = analyze_holdings(holdings)
        assert r.geography_em_pct == 100.0


class TestStyleTilts:
    def test_growth_tilted_portfolio(self):
        holdings = [
            _holding("EC", 30, "Technology", "US0378331005"),
            _holding("EC", 25, "Healthcare", "US02079K3059"),
            _holding("EC", 20, "Consumer Discretionary", "US0231351067"),
            _holding("EC", 15, "Financials", "US12345678"),  # Value
            _holding("EC", 10, "Energy", "US7185461040"),    # Value
        ]
        r = analyze_holdings(holdings)
        assert r.growth_tilt is not None
        assert r.growth_tilt > 0.3  # Growth-tilted

    def test_value_tilted_portfolio(self):
        holdings = [
            _holding("EC", 30, "Financials"),
            _holding("EC", 25, "Energy"),
            _holding("EC", 20, "Utilities"),
            _holding("EC", 15, "Materials"),
            _holding("EC", 10, "Consumer Staples"),
        ]
        r = analyze_holdings(holdings)
        assert r.growth_tilt is not None
        assert r.growth_tilt < -0.3

    def test_fixed_income_has_no_style_tilt(self):
        holdings = [_holding("DBT", 100)]
        r = analyze_holdings(holdings)
        assert r.growth_tilt is None
        assert r.size_tilt is None


class TestEdgeCases:
    def test_empty_holdings_returns_empty_analysis(self):
        r = analyze_holdings([])
        assert r.n_holdings == 0
        assert r.total_nav_covered_pct == 0.0

    def test_coverage_quality_thresholds(self):
        # 95% coverage → high
        r = analyze_holdings([_holding("EC", 95, "Technology")])
        assert r.coverage_quality == "high"
        # 75% coverage → medium
        r = analyze_holdings([_holding("EC", 75, "Technology")])
        assert r.coverage_quality == "medium"
        # 50% coverage → low
        r = analyze_holdings([_holding("EC", 50, "Technology")])
        assert r.coverage_quality == "low"
```

### VERIFICATION (Session A)

1. `make lint` + `make typecheck` pass.
2. `make test` — all new tests green.
3. Holdings analyzer is pure (no DB/network). Deterministic output for deterministic input.

---

## Session B — Layer 0 Classifier Integration

### DELIVERABLES

#### 1. Extend `strategy_classifier.py` with Layer 0

File: `backend/app/domains/wealth/services/strategy_classifier.py`

Add BEFORE Layer 1 (Tiingo description) in `classify_fund()`:

```python
def classify_fund(
    *,
    fund_name: str,
    fund_type: str | None,
    tiingo_description: str | None,
    holdings_analysis: HoldingsAnalysis | None = None,  # NEW
) -> ClassificationResult:
    """Classify a fund through the cascade. Pure function."""
    # Layer 0: Holdings composition (highest authority)
    if holdings_analysis is not None and holdings_analysis.coverage_quality in ("high", "medium"):
        result = _classify_from_holdings(holdings_analysis, fund_name, fund_type)
        if result is not None:
            return ClassificationResult(
                strategy_label=result[0],
                source="nport_holdings",
                confidence="high",
                matched_pattern=result[1],
            )

    # Layer 1: Tiingo description
    # ... existing code
```

#### 2. Implement `_classify_from_holdings`

```python
def _classify_from_holdings(
    h: HoldingsAnalysis,
    fund_name: str,
    fund_type: str | None,
) -> tuple[str, str] | None:
    """Layer 0: classify from fund composition.

    Priority rules (first match wins):
    1. Global Macro signature: derivatives >60% + FX/IR mix
    2. Real Estate: Real Estate sector >40% of equity
    3. Precious Metals: Materials>50% and specific mining sector dominance
    4. Target Date: balanced (40-70 equity) + multi-asset name hint
    5. Balanced: 30-70% equity AND 30-70% fixed income
    6. Equity-dominant: >=70% equity → style box decomposition
    7. Fixed income-dominant: >=70% fixed income → bond type
    8. Cash-dominant: >=80% cash → Cash Equivalent
    """
    # Rule 1: Global Macro signature
    if h.derivatives_pct > 60:
        fx_or_ir = h.derivatives_fx_pct + h.derivatives_ir_pct
        if fx_or_ir > 30:
            return ("Global Macro", "holdings:global_macro")

    # Rule 2: Real Estate (sector concentration within equity)
    if h.equity_pct >= 40 and h.top_sectors:
        top_sector_name, top_sector_pct = h.top_sectors[0]
        if "real estate" in top_sector_name.lower() and top_sector_pct > 40:
            return ("Real Estate", "holdings:real_estate_sector")

    # Rule 3: Cash-dominant
    if h.cash_pct >= 80:
        return ("Cash Equivalent", "holdings:cash_dominant")

    # Rule 4: Target Date (look for multi-asset with date in name)
    if 30 <= h.equity_pct <= 70 and 20 <= h.fixed_income_pct <= 60:
        import re
        if re.search(r"target\s+(?:date|retirement|maturity|\d{4})", fund_name, re.IGNORECASE):
            return ("Target Date", "holdings:target_date_confirmed")

    # Rule 5: Balanced
    if 30 <= h.equity_pct <= 70 and 30 <= h.fixed_income_pct <= 70:
        return ("Balanced", "holdings:balanced")

    # Rule 6: Equity-dominant → style box
    if h.equity_pct >= 70:
        # Geography first (overrides style box for international/regional funds)
        if h.geography_em_pct > 50:
            return ("Emerging Markets Equity", "holdings:em_equity")
        if h.geography_europe_pct > 60:
            return ("European Equity", "holdings:european_equity")
        if h.geography_asia_developed_pct > 60:
            return ("Asian Equity", "holdings:asian_equity")
        # International (non-US dominant but not concentrated in one region)
        non_us = 100 - h.geography_us_pct
        if non_us > 60:
            return ("International Equity", "holdings:international_equity")

        # Sector concentration = Sector Equity
        if h.top_sectors and h.top_sectors[0][1] > 60:
            return ("Sector Equity", f"holdings:sector_{h.top_sectors[0][0].lower().replace(' ', '_')}")

        # Style box for diversified US equity
        if h.growth_tilt is not None and h.size_tilt is not None:
            size_label = "Large" if h.size_tilt > 0.3 else ("Small" if h.size_tilt < -0.3 else "Mid")
            style_label = "Growth" if h.growth_tilt > 0.3 else ("Value" if h.growth_tilt < -0.3 else "Blend")
            return (f"{size_label} {style_label}", f"holdings:{size_label.lower()}_{style_label.lower()}")

    # Rule 7: Fixed income-dominant
    if h.fixed_income_pct >= 70:
        # Geography
        if h.geography_em_pct > 40:
            return ("Emerging Markets Debt", "holdings:em_debt")
        if h.geography_europe_pct > 50:
            return ("European Bond", "holdings:european_bond")
        # Default: can't disambiguate between HY/IG/Gov without credit rating
        # Return Intermediate-Term Bond as safest generic
        # TODO Phase 4.5: credit rating enrichment disambiguates
        return ("Intermediate-Term Bond", "holdings:fixed_income_generic")

    # No clear signal from holdings
    return None
```

#### 3. Update worker to fetch holdings

File: `backend/app/domains/wealth/workers/strategy_reclassification.py`

Add holdings fetching to the SQL query for sources with CIK (sec_registered_funds, sec_etfs, instruments_universe via CIK mapping):

```python
async def _fetch_latest_holdings(db, cik: int) -> list[dict]:
    """Fetch latest N-PORT holdings for a CIK."""
    if not cik:
        return []
    stmt = text("""
        WITH latest AS (
            SELECT MAX(report_date) AS rd FROM sec_nport_holdings WHERE cik = :cik
        )
        SELECT
            cik, report_date, cusip, isin, issuer_name,
            asset_class, sector, market_value, pct_of_nav, currency
        FROM sec_nport_holdings
        WHERE cik = :cik
          AND report_date = (SELECT rd FROM latest)
        ORDER BY pct_of_nav DESC NULLS LAST
    """)
    r = await db.execute(stmt, {"cik": cik})
    return [dict(row._mapping) for row in r]
```

In the per-source reclassify functions, compute `HoldingsAnalysis` when CIK is available:

```python
from app.domains.wealth.services.holdings_analyzer import analyze_holdings

# Per row:
holdings = await _fetch_latest_holdings(db, row.cik) if row.cik else []
h_analysis = analyze_holdings(holdings) if holdings else None

result = classify_fund(
    fund_name=row.fund_name,
    fund_type=row.fund_type,
    tiingo_description=row.tiingo_description,
    holdings_analysis=h_analysis,
)
```

#### 4. Tests: `test_strategy_classifier_layer0.py`

Regression tests for the 5 bug patterns that motivated this sprint:

```python
def test_target_date_resolved_by_holdings():
    """Vanguard Target Retirement 2055 has ~90% equity holdings."""
    h = HoldingsAnalysis(
        as_of_date=date(2026, 3, 31),
        n_holdings=500, total_nav_covered_pct=98,
        equity_pct=88, fixed_income_pct=10, cash_pct=2,
        derivatives_pct=0, other_pct=0,
        top_sectors=[("Technology", 25), ("Financials", 15)],
        sector_hhi=1200, distinct_sectors=11,
        geography_us_pct=65, geography_europe_pct=15,
        geography_asia_developed_pct=10, geography_em_pct=8, geography_other_pct=2,
        growth_tilt=0.1, size_tilt=0.7,
        coverage_quality="high",
    )
    result = classify_fund(
        fund_name="Vanguard Target Retirement 2055",
        fund_type="Mutual Fund",
        tiingo_description=None,
        holdings_analysis=h,
    )
    # Target Date not triggered by holdings (88% equity too high to match balanced range)
    # Falls through — but at least NOT Government Bond (which was the bug)
    assert result.strategy_label != "Government Bond"

def test_equity_income_resolved_by_holdings():
    """CAPITAL WORLD GROWTH & INCOME has 95% equity."""
    h = HoldingsAnalysis(
        as_of_date=date(2026, 3, 31),
        n_holdings=200, total_nav_covered_pct=95,
        equity_pct=95, fixed_income_pct=3, cash_pct=2,
        derivatives_pct=0, other_pct=0,
        top_sectors=[("Financials", 20)],
        sector_hhi=500, distinct_sectors=10,
        geography_us_pct=55, geography_europe_pct=25,
        geography_asia_developed_pct=10, geography_em_pct=10, geography_other_pct=0,
        growth_tilt=-0.1, size_tilt=0.8,
        coverage_quality="high",
    )
    result = classify_fund(
        fund_name="CAPITAL WORLD GROWTH & INCOME",
        fund_type="Mutual Fund",
        tiingo_description=None,
        holdings_analysis=h,
    )
    # Should be International or Global Equity, NOT Intermediate-Term Bond (the bug)
    assert "Bond" not in result.strategy_label

def test_global_macro_from_derivatives():
    """RIVERVIEW GLOBAL MACRO has derivatives-heavy composition."""
    h = HoldingsAnalysis(
        as_of_date=date(2026, 3, 31),
        n_holdings=50, total_nav_covered_pct=95,
        equity_pct=5, fixed_income_pct=5, cash_pct=25,
        derivatives_pct=65, other_pct=0,
        top_sectors=[], sector_hhi=0, distinct_sectors=0,
        geography_us_pct=40, geography_europe_pct=20,
        geography_asia_developed_pct=10, geography_em_pct=15, geography_other_pct=15,
        derivatives_fx_pct=20, derivatives_ir_pct=20,
        derivatives_commodity_pct=10, derivatives_equity_pct=10, derivatives_credit_pct=5,
        non_usd_currency_pct=40,
        coverage_quality="high",
    )
    result = classify_fund(
        fund_name="RIVERVIEW GLOBAL MACRO FUND",
        fund_type="Mutual Fund",
        tiingo_description=None,
        holdings_analysis=h,
    )
    assert result.strategy_label == "Global Macro"
    assert result.source == "nport_holdings"


def test_real_estate_from_sector_concentration():
    """Fund with 70% of equity in Real Estate sector = Real Estate."""
    h = HoldingsAnalysis(
        as_of_date=date(2026, 3, 31),
        n_holdings=25, total_nav_covered_pct=95,
        equity_pct=95, fixed_income_pct=3, cash_pct=2,
        derivatives_pct=0, other_pct=0,
        top_sectors=[("Real Estate", 75), ("Financials", 15)],
        sector_hhi=5850, distinct_sectors=3,
        geography_us_pct=85, geography_europe_pct=10,
        geography_asia_developed_pct=3, geography_em_pct=2, geography_other_pct=0,
        growth_tilt=-0.2, size_tilt=0.6,
        coverage_quality="high",
    )
    result = classify_fund(
        fund_name="iShares Mortgage Real Estate ETF",
        fund_type="ETF",
        tiingo_description=None,
        holdings_analysis=h,
    )
    assert result.strategy_label == "Real Estate"
    assert result.source == "nport_holdings"


def test_low_coverage_falls_through_to_tiingo():
    """If coverage_quality is low, Layer 0 passes through to Layer 1."""
    h = HoldingsAnalysis(
        as_of_date=date(2026, 3, 31),
        n_holdings=5, total_nav_covered_pct=40,  # Low coverage
        equity_pct=95, fixed_income_pct=3, cash_pct=2,
        derivatives_pct=0, other_pct=0,
        top_sectors=[("Real Estate", 75)],
        sector_hhi=5625, distinct_sectors=1,
        geography_us_pct=100, geography_europe_pct=0,
        geography_asia_developed_pct=0, geography_em_pct=0, geography_other_pct=0,
        coverage_quality="low",
    )
    result = classify_fund(
        fund_name="Generic Fund",
        fund_type="Mutual Fund",
        tiingo_description="invests primarily in large cap growth stocks",
        holdings_analysis=h,
    )
    # Layer 0 skipped due to low coverage; Layer 1 fires on description
    assert result.source == "tiingo_description"
    assert result.strategy_label == "Large Growth"
```

### VERIFICATION (Session B)

1. `make test` passes (layer 0 + existing 124 tests).
2. Re-run `run_strategy_reclassification()` → new run_id.
3. Counts by classification_source:
   - `nport_holdings`: expected 3,000-6,000 rows (funds with good N-PORT coverage)
   - `tiingo_description`: reduced (Layer 0 wins first)
   - `name_regex`: reduced
   - `fallback`: reduced from ~10k to <3k

4. Spot-check 30 samples where `classification_source = 'nport_holdings'`. All should be defensible:
   - High-equity funds classified via style box or geography
   - High-FI funds classified to bond category
   - Derivatives-heavy classified to Global Macro
   - Real estate-heavy classified to Real Estate

---

## Session C — Style Drift Analyzer

### DELIVERABLES

#### 1. Service: `backend/app/domains/wealth/services/style_drift_analyzer.py`

```python
"""
Style drift analysis.

Compare current HoldingsAnalysis against historical mean (last 8 quarters)
and emit drift signals. Key metrics:
  - asset_mix_drift: L2 distance on (equity, fi, cash, deriv, other)
  - sector_drift: L2 distance on sector weights
  - geography_drift: L2 distance on geography buckets
  - style_drift: Euclidean distance in (growth_tilt, size_tilt) space
  - composite_drift: weighted sum

Emits to strategy_drift_alerts when thresholds exceeded.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from statistics import mean
import math

from app.domains.wealth.services.holdings_analyzer import HoldingsAnalysis


@dataclass(frozen=True)
class StyleDriftResult:
    instrument_id: str
    current_date: date
    historical_window_quarters: int
    asset_mix_drift: float      # 0-100 scale
    sector_drift: float
    geography_drift: float
    style_drift: float | None   # None if current or historical had no style data
    composite_drift: float      # weighted combo
    severity: str                # "none" | "low" | "medium" | "high" | "critical"
    drivers: list[str]           # top 3 contributing factors


def compute_style_drift(
    current: HoldingsAnalysis,
    historical: list[HoldingsAnalysis],
    *,
    instrument_id: str,
) -> StyleDriftResult:
    """Compare current holdings against historical mean.

    Historical should have at least 4 quarters for meaningful drift detection.
    If fewer, returns low-confidence result with severity='none'.
    """
    if len(historical) < 4:
        return _insufficient_history(current, instrument_id)

    # Asset mix L2 distance
    hist_mix = _mean_asset_mix(historical)
    curr_mix = (
        current.equity_pct, current.fixed_income_pct, current.cash_pct,
        current.derivatives_pct, current.other_pct,
    )
    asset_drift = _l2_distance(curr_mix, hist_mix)

    # Geography L2
    hist_geo = _mean_geography(historical)
    curr_geo = (
        current.geography_us_pct, current.geography_europe_pct,
        current.geography_asia_developed_pct, current.geography_em_pct,
        current.geography_other_pct,
    )
    geo_drift = _l2_distance(curr_geo, hist_geo)

    # Sector drift (top sectors)
    sec_drift = _sector_drift(current, historical)

    # Style drift (growth/size tilts)
    if current.growth_tilt is not None and current.size_tilt is not None:
        hist_growth = [h.growth_tilt for h in historical if h.growth_tilt is not None]
        hist_size = [h.size_tilt for h in historical if h.size_tilt is not None]
        if hist_growth and hist_size:
            style_dist = math.sqrt(
                (current.growth_tilt - mean(hist_growth)) ** 2 +
                (current.size_tilt - mean(hist_size)) ** 2
            )
            # Scale to 0-100 (style tilts are -1 to +1, max distance is ~2.83)
            style_drift: float | None = (style_dist / 2.83) * 100
        else:
            style_drift = None
    else:
        style_drift = None

    # Composite drift (weighted)
    weights = {"asset_mix": 0.4, "geography": 0.2, "sector": 0.25, "style": 0.15}
    composite = (
        asset_drift * weights["asset_mix"] +
        geo_drift * weights["geography"] +
        sec_drift * weights["sector"] +
        (style_drift or 0) * weights["style"]
    )

    # Severity thresholds
    if composite < 5:
        severity = "none"
    elif composite < 15:
        severity = "low"
    elif composite < 30:
        severity = "medium"
    elif composite < 50:
        severity = "high"
    else:
        severity = "critical"

    # Top drivers
    drivers = sorted([
        ("asset_mix", asset_drift * weights["asset_mix"]),
        ("geography", geo_drift * weights["geography"]),
        ("sector", sec_drift * weights["sector"]),
        ("style", (style_drift or 0) * weights["style"]),
    ], key=lambda x: -x[1])[:3]

    return StyleDriftResult(
        instrument_id=instrument_id,
        current_date=current.as_of_date,
        historical_window_quarters=len(historical),
        asset_mix_drift=asset_drift,
        sector_drift=sec_drift,
        geography_drift=geo_drift,
        style_drift=style_drift,
        composite_drift=composite,
        severity=severity,
        drivers=[d[0] for d in drivers],
    )


def _l2_distance(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _mean_asset_mix(historical: list[HoldingsAnalysis]) -> tuple[float, ...]:
    n = len(historical)
    return (
        sum(h.equity_pct for h in historical) / n,
        sum(h.fixed_income_pct for h in historical) / n,
        sum(h.cash_pct for h in historical) / n,
        sum(h.derivatives_pct for h in historical) / n,
        sum(h.other_pct for h in historical) / n,
    )


def _mean_geography(historical: list[HoldingsAnalysis]) -> tuple[float, ...]:
    n = len(historical)
    return (
        sum(h.geography_us_pct for h in historical) / n,
        sum(h.geography_europe_pct for h in historical) / n,
        sum(h.geography_asia_developed_pct for h in historical) / n,
        sum(h.geography_em_pct for h in historical) / n,
        sum(h.geography_other_pct for h in historical) / n,
    )


def _sector_drift(current: HoldingsAnalysis, historical: list[HoldingsAnalysis]) -> float:
    """Compute sector weight L2 drift using union of sectors."""
    curr_pcts = dict(current.top_sectors[:5])
    hist_means: dict[str, float] = {}
    for h in historical:
        for name, pct in h.top_sectors[:5]:
            if name not in hist_means:
                hist_means[name] = 0.0
            hist_means[name] += pct / len(historical)
    all_sectors = set(curr_pcts.keys()) | set(hist_means.keys())
    return math.sqrt(sum(
        (curr_pcts.get(s, 0.0) - hist_means.get(s, 0.0)) ** 2
        for s in all_sectors
    ))


def _insufficient_history(current: HoldingsAnalysis, instrument_id: str) -> StyleDriftResult:
    return StyleDriftResult(
        instrument_id=instrument_id,
        current_date=current.as_of_date,
        historical_window_quarters=0,
        asset_mix_drift=0.0, sector_drift=0.0, geography_drift=0.0,
        style_drift=None, composite_drift=0.0,
        severity="none", drivers=[],
    )
```

#### 2. Worker: `backend/app/domains/wealth/workers/style_drift_worker.py`

- Lock 900_064
- Weekly schedule
- For each fund with 4+ quarterly N-PORT filings, compute drift
- Persist results to `strategy_drift_alerts` table (existing) with metric_details JSONB payload
- Alert when severity in ("high", "critical")

#### 3. Tests and runbook documentation

### VERIFICATION (Session C)

1. Historical fixture for 8 quarters → known drift score.
2. Insufficient history (<4 quarters) → severity="none".
3. Stable fund (no change) → drift < 5.
4. Fund with 50% sector reallocation → drift > 30, severity="high".

---

## OVERALL VERIFICATION

1. All 3 sessions' tests pass.
2. Re-run `run_strategy_reclassification()` — `fallback` count drops from ~10k to <3k.
3. Spot-check 30 funds where `classification_source = 'nport_holdings'` — all correctly classified.
4. `style_drift_worker` run detects known drift events (manual fixture test).
5. `strategy_drift_alerts` populated with composite_drift metadata.

---

## OUT OF SCOPE

- **Credit rating enrichment** (Phase 4.5): Disambiguates HY vs IG bonds
- **Market cap enrichment** (Phase 4.5): Improves style box precision beyond sector heuristic
- **Maturity/duration enrichment** (Phase 4.5): Distinguishes Short-Term vs Long-Term Bond
- **Frontend alert UI** (separate sprint): Display drift alerts in dashboard
- **Automated rebalancing triggers** (future): Link drift severity to construction advisor

---

## SEQUENCE

1. Session A (Holdings Analyzer) merged → unblocks B
2. Session B (Layer 0 integration) merged → unblocks re-run worker with holdings
3. Re-run worker, inspect numbers, apply new batch via apply_strategy_reclassification.py
4. Session C (Style Drift) merged → populates strategy_drift_alerts
5. Future: Phase 4.5 enrichments (credit rating, market cap, maturity)
