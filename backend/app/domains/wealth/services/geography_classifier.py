"""Investment geography classifier — 3-layer cascade.

Layer 1: N-PORT ISIN country codes (highest quality — real allocation data)
Layer 2: strategy_label + fund_name keyword matching
Layer 3: Default by fund_type/domicile

Never raises — returns a canonical geography string.
"""

from __future__ import annotations

import re

# Canonical values — these appear in screener filters and Portfolio Builder
GEOGRAPHY_VALUES = frozenset({
    "US",
    "Europe",
    "Emerging Markets",
    "Asia Pacific",
    "Global",
    "Latin America",
    "Middle East & Africa",
})

# ISO country code → geography region
COUNTRY_TO_REGION: dict[str, str] = {
    # US
    "US": "US",
    # Europe
    "GB": "Europe", "DE": "Europe", "FR": "Europe", "NL": "Europe",
    "CH": "Europe", "SE": "Europe", "DK": "Europe", "NO": "Europe",
    "IT": "Europe", "ES": "Europe", "BE": "Europe", "AT": "Europe",
    "IE": "Europe", "PT": "Europe", "FI": "Europe", "LU": "Europe",
    "KY": "Europe",
    # Asia Pacific
    "JP": "Asia Pacific", "CN": "Asia Pacific", "TW": "Asia Pacific",
    "KR": "Asia Pacific", "HK": "Asia Pacific", "AU": "Asia Pacific",
    "SG": "Asia Pacific", "IN": "Asia Pacific",
    # Emerging Markets (non-Asia)
    "BR": "Emerging Markets", "MX": "Emerging Markets",
    "ZA": "Emerging Markets", "EG": "Emerging Markets",
    "NG": "Emerging Markets", "KE": "Emerging Markets",
    "SA": "Emerging Markets", "AE": "Emerging Markets",
    "TH": "Emerging Markets", "ID": "Emerging Markets",
    "MY": "Emerging Markets", "PH": "Emerging Markets",
    "PL": "Emerging Markets", "CZ": "Emerging Markets",
    "HU": "Emerging Markets", "TR": "Emerging Markets",
    "RU": "Emerging Markets",
    # Latin America (overlap with EM — kept separate for granularity)
    "CL": "Latin America", "CO": "Latin America", "PE": "Latin America",
    "AR": "Latin America",
    # Canada — North American but not US-focused → Global
    "CA": "Global",
}

# Keywords for Layer 2 — order matters (most specific first)
_GEOGRAPHY_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bem\b|emerging.?market", re.IGNORECASE), "Emerging Markets"),
    (re.compile(r"\bchina\b|\bchinese\b|\bgreater china\b", re.IGNORECASE), "Emerging Markets"),
    (re.compile(r"\bindia\b|\bindian\b", re.IGNORECASE), "Emerging Markets"),
    (re.compile(r"latin\s*america|\bbrazil\b|\bmexico\b|\blatam\b", re.IGNORECASE), "Latin America"),
    (re.compile(r"\beurope\b|\beuropean\b|\beurozone\b|\beuro\b", re.IGNORECASE), "Europe"),
    (re.compile(r"\basia[ -]pacific\b|\basiapac\b|\bapac\b|\bjapan\b|\bjapanese\b", re.IGNORECASE), "Asia Pacific"),
    (re.compile(r"\basia\b|\basian\b", re.IGNORECASE), "Asia Pacific"),
    (re.compile(r"\bglobal\b|\bworld\b|\binternational\b|\bforeign\b|\bex[\.\-]?us\b", re.IGNORECASE), "Global"),
    (re.compile(r"\bus\b|\bamerican\b|\bdomestic\b|\bunited states\b|\bu\.s\.", re.IGNORECASE), "US"),
]


def classify_from_nport_countries(
    country_allocations: dict[str, float],
) -> str | None:
    """Layer 1: N-PORT ISIN country codes."""
    if not country_allocations:
        return None

    us_pct = country_allocations.get("US", 0.0)

    if us_pct >= 80.0:
        return "US"

    # Aggregate by region
    region_totals: dict[str, float] = {}
    for country, pct in country_allocations.items():
        region = COUNTRY_TO_REGION.get(country)
        if region:
            region_totals[region] = region_totals.get(region, 0.0) + pct

    if not region_totals:
        return None

    dominant_region = max(region_totals, key=lambda r: region_totals[r])
    dominant_pct = region_totals[dominant_region]

    if dominant_pct >= 50.0:
        return dominant_region

    # US 20-80% with cross-region exposure → Global
    if us_pct >= 20.0:
        return "Global"

    return "Global"


def classify_from_text(text: str | None) -> str | None:
    """Layer 2: keyword matching on strategy_label or fund_name."""
    if not text:
        return None
    for pattern, geography in _GEOGRAPHY_KEYWORDS:
        if pattern.search(text):
            return geography
    return None


def classify_default(
    fund_type: str | None,
    domicile: str | None,
    universe_type: str | None,
) -> str:
    """Layer 3: default by fund type and domicile."""
    if universe_type in ("ucits", "esma"):
        if domicile in ("IE", "LU", "GB", "FR", "DE"):
            return "Europe"
        return "Global"
    if fund_type in ("hedge_fund", "private_equity", "real_estate", "venture_capital",
                      "Hedge Fund", "Private Equity Fund", "Venture Capital Fund",
                      "Real Estate Fund"):
        return "Global"
    # Registered US / ETF / BDC without signal → US (91% confirmed by N-PORT)
    return "US"


def classify_geography(
    *,
    fund_type: str | None = None,
    universe_type: str | None = None,
    domicile: str | None = None,
    strategy_label: str | None = None,
    fund_name: str | None = None,
    nport_country_allocations: dict[str, float] | None = None,
) -> str:
    """Cascade classifier. Never raises.

    Returns one of: US, Europe, Emerging Markets, Asia Pacific,
                    Global, Latin America, Middle East & Africa
    """
    # Layer 1: N-PORT (most reliable)
    if nport_country_allocations:
        result = classify_from_nport_countries(nport_country_allocations)
        if result:
            return result

    # Layer 2: text signals
    for text in [strategy_label, fund_name]:
        result = classify_from_text(text)
        if result:
            return result

    # Layer 3: default
    return classify_default(fund_type, domicile, universe_type)
