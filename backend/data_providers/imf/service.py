"""IMF World Economic Outlook data provider — GDP, inflation, fiscal forecasts.

Uses the IMF DataMapper JSON API (simple REST, no SDMX/sdmx1 needed).
No authentication required. Updated April + October each year.

Import-linter: data_providers must NOT import vertical_engines, app.domains,
quant_engine, or ai_engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import structlog

logger = structlog.get_logger()

IMF_API_BASE = "https://www.imf.org/external/datamapper/api/v1"

# WEO indicators of interest
INDICATORS: list[tuple[str, str]] = [
    ("NGDP_RPCH", "gdp_growth"),       # Real GDP growth (%)
    ("PCPIPCH", "inflation"),           # Inflation, average consumer prices (%)
    ("GGXCNL_NGDP", "fiscal_balance"), # General govt net lending/borrowing (% of GDP)
    ("GGXWDG_NGDP", "govt_debt"),      # General govt gross debt (% of GDP)
]

# Countries of interest — IMF uses ISO 3-letter codes
COUNTRIES: list[str] = [
    "USA", "GBR", "DEU", "FRA", "JPN", "CHN", "BRA", "IND", "MEX", "KOR",
    "AUS", "CAN", "ITA", "ESP", "NLD", "CHE", "SWE", "NOR", "DNK", "AUT",
    "BEL", "FIN", "PRT", "IRL", "GRC", "POL", "CZE", "HUN", "TUR", "ZAF",
    "CHL", "COL", "PER", "THA", "MYS", "IDN", "PHL", "SGP", "HKG", "TWN",
    "ARG", "RUS", "SAU", "ISR",
]

# ISO-3 → ISO-2 mapping for DB consistency with BIS
ISO3_TO_ISO2: dict[str, str] = {
    "USA": "US", "GBR": "GB", "DEU": "DE", "FRA": "FR", "JPN": "JP",
    "CHN": "CN", "BRA": "BR", "IND": "IN", "MEX": "MX", "KOR": "KR",
    "AUS": "AU", "CAN": "CA", "ITA": "IT", "ESP": "ES", "NLD": "NL",
    "CHE": "CH", "SWE": "SE", "NOR": "NO", "DNK": "DK", "AUT": "AT",
    "BEL": "BE", "FIN": "FI", "PRT": "PT", "IRL": "IE", "GRC": "GR",
    "POL": "PL", "CZE": "CZ", "HUN": "HU", "TUR": "TR", "ZAF": "ZA",
    "CHL": "CL", "COL": "CO", "PER": "PE", "THA": "TH", "MYS": "MY",
    "IDN": "ID", "PHL": "PH", "SGP": "SG", "HKG": "HK", "TWN": "TW",
    "ARG": "AR", "RUS": "RU", "SAU": "SA", "ISR": "IL",
}


@dataclass(frozen=True)
class ImfForecast:
    """Single IMF WEO forecast — frozen for thread safety."""

    country_code: str   # ISO-2 for DB consistency
    indicator: str      # e.g. 'NGDP_RPCH'
    year: int           # forecast year
    value: float
    edition: str        # e.g. '202604'


async def fetch_imf_indicator(
    client: httpx.AsyncClient,
    indicator_code: str,
    countries: list[str] | None = None,
) -> list[ImfForecast]:
    """Fetch a single IMF WEO indicator for the specified countries.

    The DataMapper API returns JSON: {indicator: {country: {year: value}}}.
    """
    target_countries = countries or COUNTRIES
    url = f"{IMF_API_BASE}/{indicator_code}"

    try:
        resp = await client.get(url, timeout=30.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.warning(
            "IMF API error",
            indicator=indicator_code,
            status=e.response.status_code,
        )
        return []
    except httpx.HTTPError as e:
        logger.warning("IMF API connection error", indicator=indicator_code, error=str(e))
        return []

    try:
        data = resp.json()
    except Exception:
        logger.warning("IMF API invalid JSON", indicator=indicator_code)
        return []

    # Structure: {"values": {indicator_code: {country_iso3: {year_str: value}}}}
    values = data.get("values", {}).get(indicator_code, {})
    if not values:
        logger.warning("IMF API empty response", indicator=indicator_code)
        return []

    # Derive edition from current date (April/October)
    now = datetime.now(tz=timezone.utc)
    edition = f"{now.year}{now.month:02d}"

    results: list[ImfForecast] = []
    for iso3 in target_countries:
        country_data = values.get(iso3, {})
        iso2 = ISO3_TO_ISO2.get(iso3, iso3[:2])

        for year_str, val in country_data.items():
            try:
                year = int(year_str)
                value = float(val)
            except (ValueError, TypeError):
                continue

            results.append(ImfForecast(
                country_code=iso2,
                indicator=indicator_code,
                year=year,
                value=value,
                edition=edition,
            ))

    logger.info(
        "IMF indicator fetched",
        indicator=indicator_code,
        rows=len(results),
    )
    return results


async def fetch_all_imf_data(
    countries: list[str] | None = None,
) -> list[ImfForecast]:
    """Fetch all IMF WEO indicators (GDP, inflation, fiscal, debt).

    Returns flat list of ImfForecast observations.
    """
    all_results: list[ImfForecast] = []

    async with httpx.AsyncClient() as client:
        for indicator_code, _label in INDICATORS:
            forecasts = await fetch_imf_indicator(client, indicator_code, countries)
            all_results.extend(forecasts)

    logger.info("IMF fetch complete", total_observations=len(all_results))
    return all_results
