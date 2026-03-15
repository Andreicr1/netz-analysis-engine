"""FRED data ingestion worker — fetches macro indicators from FRED API.

DEPRECATED — 2026-03-15
Replaced by: backend/app/domains/wealth/workers/macro_ingestion.py
Reason: macro_ingestion is a superset (45 series vs 10) with regional scoring,
concurrent domain fetching, and macro_regional_snapshots persistence.

CUTOVER SEQUENCE (do not skip steps):
  1. Deploy macro_ingestion.py and verify first successful run
  2. Confirm macro_data table is being populated by macro_ingestion
  3. Disable fred_ingestion in the scheduler/Azure Function trigger
  4. Delete this file in the follow-up cleanup sprint

DO NOT run both workers simultaneously — both write to macro_data
with the same series IDs.  Last-write-wins, causing non-deterministic
staleness behavior in regime_service.get_latest_macro_values().

---

Original description:

Usage:
    python -m app.workers.fred_ingestion

Fetches VIX, Treasury rates, CPI, Fed Funds rate from FRED API
and stores results in macro_data table. Computes derived series:
- YIELD_CURVE_10Y2Y = DGS10 - DGS2
- CPI_YOY = (CPI_current / CPI_12m_ago - 1) * 100

FRED API docs: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- API base: https://api.stlouisfed.org/fred/series/observations
- Auth: api_key query parameter
- Rate limit: 120 requests per 60 seconds
- Response: JSON with observations array [{date, value}]
- Missing values returned as "." — filtered before DB insert
"""

import asyncio
import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
import structlog

# Suppress httpx DEBUG logs that would expose FRED API key in query parameters
logging.getLogger("httpx").setLevel(logging.WARNING)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config.settings import settings
from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.models.macro import MacroData

logger = structlog.get_logger()

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Rate limiting: max 2 req/sec per CLAUDE.md §9
MIN_REQUEST_INTERVAL = 0.5
MAX_RETRIES = 3
BACKOFF_BASE = 1  # 1s, 4s, 16s

# FRED series configuration with expected value ranges for validation.
# Frequency: "d"=daily, "w"=weekly, "m"=monthly.
# NOTE: M2SL excluded — structural break May 2020 makes it unreliable for regime signals.
FRED_SERIES: dict[str, dict] = {
    # Market stress
    "VIXCLS": {"frequency": "d", "description": "CBOE VIX", "value_range": (0, 150)},
    # Yield curve components (for YIELD_CURVE_10Y2Y derived series)
    "DGS10": {"frequency": "d", "description": "10Y Treasury Yield", "value_range": (-5, 30)},
    "DGS2": {"frequency": "d", "description": "2Y Treasury Yield", "value_range": (-5, 30)},
    # Monetary policy
    "DFF": {"frequency": "d", "description": "Fed Funds Rate", "value_range": (0, 25)},
    # Inflation (for CPI_YOY derived series)
    "CPIAUCSL": {"frequency": "m", "description": "CPI Urban All Items", "value_range": (100, 500)},
    # Labor market — Sahm Rule recession indicator
    "SAHMREALTIME": {
        "frequency": "m",
        "description": "Sahm Rule Real-Time Recession Indicator",
        "value_range": (-2, 10),
    },
    # Labor market breadth
    "UNRATE": {
        "frequency": "m",
        "description": "Civilian Unemployment Rate",
        "value_range": (0, 30),
    },
    # Employment level
    "PAYEMS": {
        "frequency": "m",
        "description": "Total Non-Farm Payroll Employment (Thousands)",
        "value_range": (50_000, 200_000),
    },
    # Production activity
    "INDPRO": {
        "frequency": "m",
        "description": "Industrial Production Index",
        "value_range": (0, 200),
    },
    # Financial conditions (weekly — broader than VIX)
    "NFCI": {
        "frequency": "w",
        "description": "Chicago Fed National Financial Conditions Index",
        "value_range": (-5, 10),
    },
}

# Publication lag awareness — how many days after period end each series is published.
# Used downstream to avoid look-ahead bias in backtests.
SERIES_LAG_DAYS: dict[str, int] = {
    "VIXCLS": 1,          # T+1
    "DGS10": 1,           # T+1
    "DGS2": 1,            # T+1
    "DFF": 1,             # T+1
    "NFCI": 5,            # Released ~5 days after reference week
    "CPIAUCSL": 16,       # Released ~16 days after reference month
    "SAHMREALTIME": 5,    # Released with jobs report (~first Friday of next month)
    "UNRATE": 5,          # Released with jobs report
    "PAYEMS": 5,          # Released with jobs report
    "INDPRO": 16,         # Released ~16 days after reference month
}


async def _fetch_fred_series(
    client: httpx.AsyncClient,
    series_id: str,
    api_key: str,
    observation_start: str,
    observation_end: str,
) -> list[dict]:
    """Fetch observations from FRED API with retry and backoff.

    Returns list of {date: str, value: str} dicts.
    FRED returns "." for missing values — filtered out.
    API key is a query parameter (FRED API requirement) — redacted from logs.
    """
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
        "observation_end": observation_end,
        "sort_order": "asc",
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(FRED_BASE_URL, params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()

            raw_obs = data.get("observations", [])
            # Filter missing values (".")
            valid_obs = [obs for obs in raw_obs if obs.get("value") != "."]
            skipped = len(raw_obs) - len(valid_obs)

            if skipped > 0:
                logger.info(
                    "FRED missing values filtered",
                    series=series_id,
                    total=len(raw_obs),
                    skipped=skipped,
                )

            return valid_obs

        except httpx.HTTPStatusError as e:
            wait = BACKOFF_BASE * (4 ** attempt)
            # Redact API key from logged URL
            logger.warning(
                "FRED API request failed, retrying",
                series=series_id,
                status=e.response.status_code,
                attempt=attempt + 1,
                wait=wait,
            )
            if attempt == MAX_RETRIES - 1:
                logger.error("FRED API exhausted retries", series=series_id)
                return []
            await asyncio.sleep(wait)

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            wait = BACKOFF_BASE * (4 ** attempt)
            logger.warning(
                "FRED API connection error, retrying",
                series=series_id,
                error=type(e).__name__,
                attempt=attempt + 1,
                wait=wait,
            )
            if attempt == MAX_RETRIES - 1:
                logger.error("FRED API exhausted retries", series=series_id)
                return []
            await asyncio.sleep(wait)

    return []


def _validate_value(series_id: str, value_str: str) -> Decimal | None:
    """Validate and convert a FRED value string to Decimal.

    Returns None if value is outside expected range for the series.
    """
    try:
        val = Decimal(value_str)
    except (InvalidOperation, ValueError):
        logger.warning("FRED invalid value", series=series_id, value=value_str)
        return None

    config = FRED_SERIES.get(series_id)
    if config and "value_range" in config:
        lo, hi = config["value_range"]
        if not (lo <= float(val) <= hi):
            logger.warning(
                "FRED value outside expected range",
                series=series_id,
                value=str(val),
                expected_range=f"[{lo}, {hi}]",
            )
            return None

    return val


async def _ingest_series(
    client: httpx.AsyncClient,
    series_id: str,
    api_key: str,
    lookback_days: int,
) -> list[dict]:
    """Fetch and store a single FRED series. Returns list of row dicts."""
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    observations = await _fetch_fred_series(
        client, series_id, api_key,
        str(start_date), str(end_date),
    )

    if not observations:
        return []

    rows = []
    for obs in observations:
        val = _validate_value(series_id, obs["value"])
        if val is None:
            continue
        rows.append({
            "series_id": series_id,
            "obs_date": obs["date"],
            "value": val,
            "source": "fred",
            "is_derived": False,
        })

    return rows


def _compute_yield_curve(rows_by_series: dict[str, list[dict]]) -> list[dict]:
    """Compute yield curve spread: DGS10 - DGS2.

    Matches dates where both series have values.
    """
    dgs10 = {r["obs_date"]: r["value"] for r in rows_by_series.get("DGS10", [])}
    dgs2 = {r["obs_date"]: r["value"] for r in rows_by_series.get("DGS2", [])}

    common_dates = sorted(set(dgs10.keys()) & set(dgs2.keys()))
    rows = []
    for d in common_dates:
        spread = Decimal(str(dgs10[d])) - Decimal(str(dgs2[d]))
        rows.append({
            "series_id": "YIELD_CURVE_10Y2Y",
            "obs_date": d,
            "value": round(spread, 6),
            "source": "derived",
            "is_derived": True,
        })

    return rows


def _compute_cpi_yoy(rows_by_series: dict[str, list[dict]]) -> list[dict]:
    """Compute CPI Year-over-Year percentage change.

    CPI_YOY = (CPI_current / CPI_12m_ago - 1) * 100
    Uses nearest-match within +/- 5 day tolerance for 12-month lookback.
    """
    cpi_rows = rows_by_series.get("CPIAUCSL", [])
    if len(cpi_rows) < 2:
        return []

    # Build date -> value mapping
    cpi_by_date: dict[date, Decimal] = {}
    for r in cpi_rows:
        d = date.fromisoformat(r["obs_date"]) if isinstance(r["obs_date"], str) else r["obs_date"]
        cpi_by_date[d] = Decimal(str(r["value"]))

    sorted_dates = sorted(cpi_by_date.keys())
    rows = []

    for current_date in sorted_dates:
        # Target: 12 months ago (handle leap year Feb 29)
        try:
            target = current_date.replace(year=current_date.year - 1)
        except ValueError:
            target = current_date.replace(year=current_date.year - 1, day=28)

        # Find nearest CPI observation within +/- 5 days tolerance
        best_match = None
        best_diff = timedelta(days=999)
        for d in sorted_dates:
            diff = abs(d - target)
            if diff <= timedelta(days=5) and diff < best_diff:
                best_match = d
                best_diff = diff

        if best_match is None:
            continue

        cpi_current = cpi_by_date[current_date]
        cpi_12m_ago = cpi_by_date[best_match]

        if cpi_12m_ago == 0:
            continue

        yoy = (cpi_current / cpi_12m_ago - 1) * 100
        rows.append({
            "series_id": "CPI_YOY",
            "obs_date": str(current_date),
            "value": round(yoy, 6),
            "source": "derived",
            "is_derived": True,
        })

    return rows


def _compute_real_fed_funds(rows_by_series: dict[str, list[dict]]) -> list[dict]:
    """Compute real Fed Funds Rate: DFF - CPI_YOY.

    CPI_YOY is monthly; DFF is daily. For each DFF observation, uses the
    most recent available CPI_YOY value (carries forward until next release).
    """
    dff_rows = rows_by_series.get("DFF", [])
    cpi_yoy_rows = rows_by_series.get("CPI_YOY", [])

    if not dff_rows or not cpi_yoy_rows:
        return []

    # Build sorted CPI_YOY map for carry-forward lookup
    cpi_by_date: dict[date, Decimal] = {}
    for r in cpi_yoy_rows:
        d = date.fromisoformat(r["obs_date"]) if isinstance(r["obs_date"], str) else r["obs_date"]
        cpi_by_date[d] = Decimal(str(r["value"]))

    cpi_sorted_dates = sorted(cpi_by_date.keys())

    def _latest_cpi_yoy(as_of: date) -> Decimal | None:
        """Return most recent CPI_YOY published on or before as_of."""
        best = None
        for d in cpi_sorted_dates:
            if d <= as_of:
                best = cpi_by_date[d]
            else:
                break
        return best

    rows = []
    for r in dff_rows:
        dff_date = date.fromisoformat(r["obs_date"]) if isinstance(r["obs_date"], str) else r["obs_date"]
        cpi_yoy = _latest_cpi_yoy(dff_date)
        if cpi_yoy is None:
            continue
        real_rate = Decimal(str(r["value"])) - cpi_yoy
        rows.append({
            "series_id": "REAL_FED_FUNDS",
            "obs_date": str(dff_date),
            "value": round(real_rate, 6),
            "source": "derived",
            "is_derived": True,
        })

    return rows


async def run_fred_ingestion(lookback_days: int = 400) -> dict[str, int]:
    """Fetch all FRED series and compute derived values.

    Default lookback is 400 days (~13 months) to ensure CPI YoY
    can be computed for at least 1 month of data.
    """
    api_key = settings.fred_api_key
    if not api_key:
        logger.error(
            "FRED_API_KEY not set — skipping FRED ingestion. "
            "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
        )
        return {}

    logger.info("Starting FRED ingestion", lookback_days=lookback_days)
    results: dict[str, int] = {}
    rows_by_series: dict[str, list[dict]] = {}

    async with httpx.AsyncClient() as client:
        for series_id in FRED_SERIES:
            raw_rows = await _ingest_series(client, series_id, api_key, lookback_days)
            rows_by_series[series_id] = raw_rows
            results[series_id] = len(raw_rows)
            logger.info("FRED series fetched", series=series_id, rows=results[series_id])
            # Rate limiting
            await asyncio.sleep(MIN_REQUEST_INTERVAL)

    # Compute derived series (order matters: CPI_YOY before REAL_FED_FUNDS)
    yield_curve_rows = _compute_yield_curve(rows_by_series)
    cpi_yoy_rows = _compute_cpi_yoy(rows_by_series)
    # CPI_YOY must be available before computing real fed funds rate
    rows_by_series["CPI_YOY"] = cpi_yoy_rows
    real_fed_funds_rows = _compute_real_fed_funds(rows_by_series)

    # Merge all derived series for unified persist loop
    rows_by_series["YIELD_CURVE_10Y2Y"] = yield_curve_rows
    rows_by_series["REAL_FED_FUNDS"] = real_fed_funds_rows
    results["YIELD_CURVE_10Y2Y"] = len(yield_curve_rows)
    results["CPI_YOY"] = len(cpi_yoy_rows)
    results["REAL_FED_FUNDS"] = len(real_fed_funds_rows)

    # Persist all rows to database — per-series commit
    async with async_session() as db:
        for series_id, rows in rows_by_series.items():
            if not rows:
                continue
            stmt = pg_insert(MacroData).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["series_id", "obs_date"],
                set_={
                    "value": stmt.excluded.value,
                    "source": stmt.excluded.source,
                    "is_derived": stmt.excluded.is_derived,
                },
            )
            await db.execute(stmt)
            await db.commit()
            logger.info("Series persisted", series=series_id, rows=len(rows))

    total = sum(results.values())
    logger.info("FRED ingestion complete", total_rows=total, series_processed=len(results))
    return results


if __name__ == "__main__":
    asyncio.run(run_fred_ingestion())
