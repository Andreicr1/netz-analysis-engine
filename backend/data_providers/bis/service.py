"""BIS Statistics data provider — credit-to-GDP gap, debt service ratio, property prices.

Uses the BIS SDMX-CSV REST API (CSV format, no sdmx1 dependency needed).
No authentication required. Data is quarterly.

Import-linter: data_providers must NOT import vertical_engines, app.domains,
quant_engine, or ai_engine.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import structlog

logger = structlog.get_logger()

BIS_API_BASE = "https://stats.bis.org/api/v1/data"

# BIS dataset → indicator mapping
# Each entry: (dataset_key, frequency, ref_area_key, indicator_name)
DATASETS: list[tuple[str, str, str]] = [
    ("WS_CREDIT_GAP", "Q", "credit_to_gdp_gap"),
    ("WS_DSR", "Q", "debt_service_ratio"),
    ("WS_SPP", "Q", "property_prices"),
]

# Countries of interest mapped to BIS ref_area codes
# BIS uses ISO 2-letter codes
COUNTRIES: list[str] = [
    "US", "GB", "DE", "FR", "JP", "CN", "BR", "IN", "MX", "KR",
    "AU", "CA", "IT", "ES", "NL", "CH", "SE", "NO", "DK", "AT",
    "BE", "FI", "PT", "IE", "GR", "PL", "CZ", "HU", "TR", "ZA",
    "CL", "CO", "PE", "TH", "MY", "ID", "PH", "SG", "HK", "TW",
    "AR", "RU", "SA", "IL",
]


@dataclass(frozen=True)
class BisIndicator:
    """Single BIS observation — frozen for thread safety."""

    country_code: str
    indicator: str
    period: datetime
    value: float
    dataset: str


def _parse_quarter(period_str: str) -> datetime | None:
    """Parse BIS quarter string like '2024-Q1' to datetime."""
    try:
        parts = period_str.split("-Q")
        if len(parts) != 2:
            return None
        year = int(parts[0])
        quarter = int(parts[1])
        month = (quarter - 1) * 3 + 1
        return datetime(year, month, 1, tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None


async def fetch_bis_dataset(
    client: httpx.AsyncClient,
    dataset: str,
    indicator_name: str,
    countries: list[str] | None = None,
) -> list[BisIndicator]:
    """Fetch a single BIS dataset for the specified countries.

    Uses CSV format from the BIS SDMX REST API to avoid sdmx1 dependency.
    """
    target_countries = countries or COUNTRIES
    ref_area = "+".join(target_countries)

    # BIS SDMX REST: /data/{dataset}/Q.{ref_area}?format=csv
    # Key dimension: FREQ.REF_AREA (quarterly data, country codes)
    url = f"{BIS_API_BASE}/{dataset}/Q.{ref_area}"
    headers = {"Accept": "text/csv"}

    try:
        resp = await client.get(
            url,
            headers=headers,
            params={"format": "csv", "startPeriod": "2000-Q1"},
            timeout=60.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.warning(
            "BIS API error",
            dataset=dataset,
            status=e.response.status_code,
        )
        return []
    except httpx.HTTPError as e:
        logger.warning("BIS API connection error", dataset=dataset, error=str(e))
        return []

    results: list[BisIndicator] = []
    reader = csv.DictReader(io.StringIO(resp.text))

    for row in reader:
        # Country column varies by dataset: REF_AREA (SPP) or BORROWERS_CTY (CREDIT_GAP, DSR)
        country = row.get("REF_AREA") or row.get("BORROWERS_CTY") or ""
        period_str = row.get("TIME_PERIOD", "")
        value_str = row.get("OBS_VALUE", "")

        if not country or not period_str or not value_str:
            continue

        period = _parse_quarter(period_str)
        if period is None:
            continue

        try:
            value = float(value_str)
        except (ValueError, TypeError):
            continue

        results.append(BisIndicator(
            country_code=country,
            indicator=indicator_name,
            period=period,
            value=value,
            dataset=dataset,
        ))

    logger.info(
        "BIS dataset fetched",
        dataset=dataset,
        indicator=indicator_name,
        rows=len(results),
    )
    return results


async def fetch_all_bis_data(
    countries: list[str] | None = None,
) -> list[BisIndicator]:
    """Fetch all BIS datasets (credit-to-GDP gap, DSR, property prices).

    Returns flat list of BisIndicator observations.
    """
    all_results: list[BisIndicator] = []

    async with httpx.AsyncClient() as client:
        for dataset_key, _freq, indicator_name in DATASETS:
            indicators = await fetch_bis_dataset(
                client, dataset_key, indicator_name, countries,
            )
            all_results.extend(indicators)

    logger.info("BIS fetch complete", total_observations=len(all_results))
    return all_results
