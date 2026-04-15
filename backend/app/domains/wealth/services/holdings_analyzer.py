"""
Holdings composition analyzer.

Pure compute function: given a list of holdings from sec_nport_holdings for a
single fund at a single report_date, produce a HoldingsAnalysis summary with
asset mix, geography, fixed-income subtype breakdown (by N-PORT issuerCat),
and derivative-subtype signatures.

Used by Layer 0 of the classification cascade and by StyleDriftAnalyzer.

IMPORTANT — column semantics
----------------------------
``sec_nport_holdings.sector`` does **not** carry GICS sectors.  It carries
the N-PORT *issuerCat* code: ``CORP`` (corporate), ``MUN`` (municipal),
``UST`` (US Treasury), ``USGSE`` (US Gov Sponsored Enterprise),
``USGA`` (US Gov Agency), ``RF`` (restricted foreign), ``PF`` (preferred
foreign), ``NUSS`` (non-US sovereign), ``OTHER``.  Equity holdings are
almost always tagged ``CORP`` regardless of GICS sector — therefore we
**do not** derive Real Estate / Sector Equity / growth-vs-value tilts from
this column.  Those rules need a true GICS enrichment (Phase 4.5).

What we *do* derive from issuerCat:
  • ``fi_government_pct``  (UST + USGSE + USGA on debt asset classes)
  • ``fi_municipal_pct``   (MUN)
  • ``fi_corporate_pct``   (CORP on debt)
  • ``fi_sovereign_foreign_pct`` (NUSS)

Asset-class derived breakdowns:
  • ``fi_mbs_pct``  (asset_class = ABS-MBS)
  • ``fi_abs_pct``  (asset_class ∈ ABS-O, ABS-CBDO, ABS-APCP)
  • ``fi_loan_pct`` (asset_class = LON)
  • ``equity_real_estate_pct`` (asset_class = RE — REIT/real-estate equity)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

# ── Asset-class bucketing (N-PORT codes → canonical asset-mix buckets) ──
# Reference: SEC N-PORT XML schema, ``invstOrSec/assetCat``.
ASSET_CLASS_BUCKETS: dict[str, str] = {
    # Equity
    "EC": "equity",          # Common stock
    "EP": "equity",          # Preferred stock
    "PF": "equity",          # Preferred foreign (treat as equity)
    "RE": "equity",          # Real estate (REITs / direct RE) — equity sleeve
    # Fixed Income
    "DBT": "fixed_income",   # Corporate / generic debt
    "CORP": "fixed_income",
    "UST": "fixed_income",   # US Treasury
    "USGA": "fixed_income",  # US Gov Agency
    "USGSE": "fixed_income",  # US Gov Sponsored Enterprise
    "MUN": "fixed_income",   # Municipal
    "NUSS": "fixed_income",  # Non-US sovereign
    "ABS-MBS": "fixed_income",   # Mortgage-backed securities
    "ABS-O": "fixed_income",     # Other asset-backed securities
    "ABS-CBDO": "fixed_income",  # Collateralized bond/debt obligations
    "ABS-APCP": "fixed_income",  # Asset-backed commercial paper
    "LON": "fixed_income",       # Loans
    "SN": "fixed_income",        # Structured notes
    # Cash / short-term
    "ST": "cash",            # Short-term securities
    "RA": "cash",            # Repurchase agreements
    "STIV": "cash",          # Short-term investment vehicles
    # Derivatives
    "DE": "derivatives",     # Equity derivatives
    "DCR": "derivatives",    # Credit derivatives
    "DFE": "derivatives",    # FX derivatives
    "DIR": "derivatives",    # Interest rate derivatives
    "DCO": "derivatives",    # Commodity derivatives
    # Other
    "OT": "other",
    "OTHER": "other",
    "RF": "other",           # Restricted foreign — heterogeneous, default to "other"
}

# Asset-class subsets used for FI / equity sub-bucket detection.
_MBS_CODES = frozenset({"ABS-MBS"})
_ABS_CODES = frozenset({"ABS-O", "ABS-CBDO", "ABS-APCP"})
_LOAN_CODES = frozenset({"LON"})
_RE_CODES = frozenset({"RE"})
_DEBT_CODES_FOR_ISSUER_CLASSIFICATION = frozenset({
    "DBT", "CORP", "UST", "USGA", "USGSE", "MUN", "NUSS",
    "ABS-MBS", "ABS-O", "ABS-CBDO", "ABS-APCP", "LON", "SN",
})

# IssuerCat (sector column) groupings for FI subtype attribution.
_GOVT_ISSUER_CATS = frozenset({"UST", "USGA", "USGSE"})
_MUNI_ISSUER_CATS = frozenset({"MUN"})
_CORP_ISSUER_CATS = frozenset({"CORP"})
_FOREIGN_SOVEREIGN_CATS = frozenset({"NUSS"})


@dataclass(frozen=True)
class HoldingsAnalysis:
    """Fund composition summary from N-PORT holdings.

    All ``*_pct`` fields are percentages of total NAV (0–100), normalized so
    the asset-mix buckets sum to ~100 even when raw N-PORT coverage is < 100.
    """

    as_of_date: date
    n_holdings: int
    total_nav_covered_pct: float  # raw sum of pct_of_nav before normalization

    # Asset mix (sums to ~100)
    equity_pct: float
    fixed_income_pct: float
    cash_pct: float
    derivatives_pct: float
    other_pct: float

    # Geography (derived from ISIN[0:2])
    geography_us_pct: float
    geography_europe_pct: float
    geography_asia_developed_pct: float
    geography_em_pct: float
    geography_other_pct: float

    # Fixed-income subtype breakdown — % of total NAV. Used by Layer 0 to
    # disambiguate Government / Municipal / Corporate / MBS / ABS / Loan
    # without GICS sector enrichment. Each bucket can be compared to
    # ``fixed_income_pct`` to derive "share of FI sleeve" if needed.
    fi_government_pct: float = 0.0       # issuerCat ∈ (UST, USGA, USGSE)
    fi_municipal_pct: float = 0.0        # issuerCat = MUN
    fi_corporate_pct: float = 0.0        # issuerCat = CORP on debt asset class
    fi_sovereign_foreign_pct: float = 0.0  # issuerCat = NUSS
    fi_mbs_pct: float = 0.0              # asset_class = ABS-MBS
    fi_abs_pct: float = 0.0              # asset_class ∈ ABS-O/CBDO/APCP
    fi_loan_pct: float = 0.0             # asset_class = LON

    # Equity sub-buckets we *can* derive without GICS:
    equity_real_estate_pct: float = 0.0  # asset_class = RE (REIT sleeve)
    equity_foreign_pct: float = 0.0      # issuerCat ∈ (RF, PF, NUSS) on equity

    # Derivative signatures (for Global Macro detection)
    derivatives_fx_pct: float = 0.0
    derivatives_ir_pct: float = 0.0
    derivatives_commodity_pct: float = 0.0
    derivatives_equity_pct: float = 0.0
    derivatives_credit_pct: float = 0.0

    # Currency exposure (non-USD)
    non_usd_currency_pct: float = 0.0

    # Diagnostic — issuerCat distribution within the equity sleeve. NOT GICS;
    # kept for Style Drift comparison and operator inspection only. Layer 0
    # rules MUST NOT use this field for sector/style classification.
    top_issuer_categories: list[tuple[str, float]] = ()  # type: ignore[assignment]
    issuer_category_hhi: float = 0.0
    distinct_issuer_categories: int = 0

    # Metadata
    coverage_quality: str = "unknown"  # "high" (>=90), "medium" (70-90), "low" (<70)


def analyze_holdings(holdings: list[dict[str, Any]]) -> HoldingsAnalysis:
    """Compute composition summary from N-PORT holdings rows.

    Args:
        holdings: list of dicts with keys matching ``SecNportHolding`` columns.
                  Each dict must have: ``asset_class``, ``sector`` (issuerCat),
                  ``pct_of_nav``, ``isin`` (nullable), ``currency`` (nullable),
                  ``report_date``.

    Returns:
        HoldingsAnalysis frozen dataclass.
    """
    if not holdings:
        return _empty_analysis()

    as_of = max(h["report_date"] for h in holdings)
    n = len(holdings)

    coverage = sum(float(h.get("pct_of_nav") or 0) for h in holdings)
    scale = 100.0 / coverage if coverage > 0 else 1.0

    bucket_pcts: dict[str, float] = {
        "equity": 0.0, "fixed_income": 0.0, "cash": 0.0,
        "derivatives": 0.0, "other": 0.0,
    }
    derivative_subtypes: dict[str, float] = {
        "DE": 0.0, "DCR": 0.0, "DFE": 0.0, "DIR": 0.0, "DCO": 0.0,
    }

    fi_government_raw = 0.0
    fi_municipal_raw = 0.0
    fi_corporate_raw = 0.0
    fi_sovereign_foreign_raw = 0.0
    fi_mbs_raw = 0.0
    fi_abs_raw = 0.0
    fi_loan_raw = 0.0

    equity_real_estate_raw = 0.0
    equity_foreign_raw = 0.0

    issuer_cat_weights: dict[str, float] = {}

    for h in holdings:
        pct = float(h.get("pct_of_nav") or 0)
        ac = (h.get("asset_class") or "").upper().strip()
        bucket = ASSET_CLASS_BUCKETS.get(ac, "other")
        bucket_pcts[bucket] += pct
        if ac in derivative_subtypes:
            derivative_subtypes[ac] += pct

        # Asset-class-driven FI/equity sub-buckets
        if ac in _MBS_CODES:
            fi_mbs_raw += pct
        elif ac in _ABS_CODES:
            fi_abs_raw += pct
        elif ac in _LOAN_CODES:
            fi_loan_raw += pct
        elif ac in _RE_CODES:
            equity_real_estate_raw += pct

        # IssuerCat-driven FI subtype attribution (only for debt asset classes
        # so we don't double-count equity/CORP into "fi_corporate").
        issuer = (h.get("sector") or "").upper().strip()
        if ac in _DEBT_CODES_FOR_ISSUER_CLASSIFICATION:
            if issuer in _GOVT_ISSUER_CATS:
                fi_government_raw += pct
            elif issuer in _MUNI_ISSUER_CATS:
                fi_municipal_raw += pct
            elif issuer in _CORP_ISSUER_CATS:
                fi_corporate_raw += pct
            elif issuer in _FOREIGN_SOVEREIGN_CATS:
                fi_sovereign_foreign_raw += pct

        # Equity-sleeve foreign exposure flag (RF/PF on equity, NUSS rare)
        if bucket == "equity" and issuer in {"RF", "PF", "NUSS"}:
            equity_foreign_raw += pct

        # Diagnostic issuerCat distribution within equity sleeve
        if bucket == "equity" and issuer:
            issuer_cat_weights[issuer] = issuer_cat_weights.get(issuer, 0.0) + pct

    equity_pct = bucket_pcts["equity"] * scale
    fi_pct = bucket_pcts["fixed_income"] * scale
    cash_pct = bucket_pcts["cash"] * scale
    deriv_pct = bucket_pcts["derivatives"] * scale
    other_pct = bucket_pcts["other"] * scale

    # Geography via ISIN[0:2]
    geo_buckets = {"us": 0.0, "europe": 0.0, "asia_dev": 0.0, "em": 0.0, "other": 0.0}
    for h in holdings:
        pct = float(h.get("pct_of_nav") or 0)
        iso = _country_from_isin(h.get("isin"))
        geo_buckets[_geo_bucket(iso)] += pct

    geo_us = geo_buckets["us"] * scale
    geo_eu = geo_buckets["europe"] * scale
    geo_asia = geo_buckets["asia_dev"] * scale
    geo_em = geo_buckets["em"] * scale
    geo_other = geo_buckets["other"] * scale

    # Non-USD currency exposure
    non_usd_raw = sum(
        float(h.get("pct_of_nav") or 0)
        for h in holdings
        if (h.get("currency") or "").upper().strip() not in ("", "USD")
    )
    non_usd_pct = non_usd_raw * scale

    # Diagnostic — issuerCat distribution within equity (for style-drift use,
    # NOT for classification rules).
    total_equity_raw = sum(issuer_cat_weights.values())
    if total_equity_raw > 0:
        issuer_cat_pcts = {
            k: (v / total_equity_raw) * 100 for k, v in issuer_cat_weights.items()
        }
        top_issuer_cats = sorted(issuer_cat_pcts.items(), key=lambda x: -x[1])[:5]
        ic_hhi = sum(p * p for p in issuer_cat_pcts.values())
    else:
        top_issuer_cats = []
        ic_hhi = 0.0

    # Coverage tiers. The upper bound (130%) screens out *trust-CIK
    # aggregation*: N-PORT filings under a parent trust CIK union holdings
    # across all series in the trust, producing pct_of_nav sums of 200-3000%
    # that conflate multiple distinct funds into one analysis. Empirically
    # ~25% of CIKs in production exceed this threshold; their composition
    # numbers are meaningless for single-fund classification.
    if 90 <= coverage <= 130:
        qual = "high"
    elif 70 <= coverage < 90:
        qual = "medium"
    else:
        qual = "low"  # under-covered (<70) OR trust-aggregated (>130)

    return HoldingsAnalysis(
        as_of_date=as_of,
        n_holdings=n,
        total_nav_covered_pct=coverage,
        equity_pct=equity_pct,
        fixed_income_pct=fi_pct,
        cash_pct=cash_pct,
        derivatives_pct=deriv_pct,
        other_pct=other_pct,
        geography_us_pct=geo_us,
        geography_europe_pct=geo_eu,
        geography_asia_developed_pct=geo_asia,
        geography_em_pct=geo_em,
        geography_other_pct=geo_other,
        fi_government_pct=fi_government_raw * scale,
        fi_municipal_pct=fi_municipal_raw * scale,
        fi_corporate_pct=fi_corporate_raw * scale,
        fi_sovereign_foreign_pct=fi_sovereign_foreign_raw * scale,
        fi_mbs_pct=fi_mbs_raw * scale,
        fi_abs_pct=fi_abs_raw * scale,
        fi_loan_pct=fi_loan_raw * scale,
        equity_real_estate_pct=equity_real_estate_raw * scale,
        equity_foreign_pct=equity_foreign_raw * scale,
        derivatives_fx_pct=derivative_subtypes["DFE"] * scale,
        derivatives_ir_pct=derivative_subtypes["DIR"] * scale,
        derivatives_commodity_pct=derivative_subtypes["DCO"] * scale,
        derivatives_equity_pct=derivative_subtypes["DE"] * scale,
        derivatives_credit_pct=derivative_subtypes["DCR"] * scale,
        non_usd_currency_pct=non_usd_pct,
        top_issuer_categories=top_issuer_cats,
        issuer_category_hhi=ic_hhi,
        distinct_issuer_categories=len(issuer_cat_weights),
        coverage_quality=qual,
    )


# ── Geography helpers ──

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


def _empty_analysis() -> HoldingsAnalysis:
    return HoldingsAnalysis(
        as_of_date=date.today(),
        n_holdings=0,
        total_nav_covered_pct=0.0,
        equity_pct=0.0, fixed_income_pct=0.0, cash_pct=0.0,
        derivatives_pct=0.0, other_pct=0.0,
        geography_us_pct=0.0, geography_europe_pct=0.0,
        geography_asia_developed_pct=0.0, geography_em_pct=0.0,
        geography_other_pct=0.0,
        coverage_quality="unknown",
    )
