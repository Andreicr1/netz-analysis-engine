"""Market data constants and registries (LEAF — zero sibling imports).

Contains FRED series registry, Case-Shiller metro map, geography resolution map,
and configuration constants.
"""
from __future__ import annotations

from typing import Any

# ── Configuration ─────────────────────────────────────────────────────
NFCI_STRESS_THRESHOLD = 0.0

# ── Series Registry ───────────────────────────────────────────────────
FRED_SERIES_REGISTRY: dict[str, dict[str, Any]] = {

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

# ── Regional Case-Shiller series ──────────────────────────────────────
CASE_SHILLER_METRO_MAP: dict[str, str] = {
    "new_york": "NYXRSA",
    "los_angeles": "LXXRSA",
    "miami": "MFHXRSA",
    "chicago": "CHXRSA",
    "dallas": "DAXRSA",
    "houston": "HIOXRSA",
    "washington_dc": "WDXRSA",
    "boston": "BOXRSA",
    "atlanta": "ATXRSA",
    "seattle": "SEXRSA",
    "phoenix": "PHXRSA",
    "denver": "DNXRSA",
    "san_francisco": "SFXRSA",
    "tampa": "TPXRSA",
    "charlotte": "CRXRSA",
    "minneapolis": "MNXRSA",
    "portland": "POXRSA",
    "san_diego": "SDXRSA",
    "detroit": "DEXRSA",
    "cleveland": "CLXRSA",
}

# ── Geography resolution map ──────────────────────────────────────────
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
