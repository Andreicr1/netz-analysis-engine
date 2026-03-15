"""Universal FRED API fetching service.

Sync service — called from within to_thread() context.
Intentional class pattern (not module functions) due to stateful
requirements: API key, rate limiter, base URL.

FRED rate limit: 120 requests per 60 seconds (2 req/s).

Lifecycle: Instantiate ONCE in FastAPI lifespan() or at worker startup.
The TokenBucketRateLimiter must be shared across calls within a worker run
to correctly enforce rate limits. Store as app.state.fred_service and inject
via dependency. For credit market_data_engine.py (sync context within
to_thread()): receive the pre-instantiated FredService as a parameter.

Config is injected as parameter — no module-level settings reads.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
#  Rate limiter
# ---------------------------------------------------------------------------


@dataclass
class TokenBucketRateLimiter:
    """Token bucket: allows short bursts while respecting sustained rate.

    FRED actual limit: 120 requests per 60 seconds.
    Default: max_tokens=10 (burst), refill_rate=2.0 tokens/s (sustained).
    """

    max_tokens: float = 10.0
    refill_rate: float = 2.0
    _tokens: float = field(init=False, repr=False)
    _last_refill: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._tokens = self.max_tokens
        self._last_refill = time.monotonic()

    def acquire(self) -> None:
        """Block until a token is available."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

        if self._tokens < 1.0:
            wait = (1.0 - self._tokens) / self.refill_rate
            time.sleep(wait)
            self._tokens = 0.0
            self._last_refill = time.monotonic()
        else:
            self._tokens -= 1.0


# ---------------------------------------------------------------------------
#  Data types
# ---------------------------------------------------------------------------


@dataclass
class FredObservation:
    """Single parsed FRED observation."""

    date: str
    value: float | None


# ---------------------------------------------------------------------------
#  Value parsing
# ---------------------------------------------------------------------------

_MISSING_VALUES = frozenset((".", "#N/A", "", "NaN", "nan"))


def parse_fred_value(raw: str, series_id: str = "", obs_date: str = "") -> float | None:
    """Parse a FRED observation value with full validation.

    FRED returns "." for missing/unreported, "#N/A" for discontinued,
    and occasionally empty strings.
    """
    if raw in _MISSING_VALUES:
        return None
    try:
        val = float(raw)
    except (ValueError, TypeError):
        logger.warning("FRED unparseable value", series=series_id, date=obs_date, raw=raw)
        return None
    if not math.isfinite(val):
        logger.warning("FRED non-finite value", series=series_id, date=obs_date, value=val)
        return None
    return val


# ---------------------------------------------------------------------------
#  Error classification
# ---------------------------------------------------------------------------


def _classify_error(status_code: int) -> str:
    """Classify HTTP error into action: 'retry', 'skip', 'fail'."""
    if status_code == 429:
        return "retry"
    if status_code == 503:
        return "retry"
    if status_code == 400:
        return "skip"
    if status_code in (401, 403):
        return "fail"
    if status_code >= 500:
        return "retry"
    return "skip"


# ---------------------------------------------------------------------------
#  FredService
# ---------------------------------------------------------------------------


class FredService:
    """Universal FRED data fetching with rate limiting and error handling.

    Args:
        api_key: FRED API key (from settings.fred_api_key).
        base_url: FRED API base URL.
        rate_limiter: Shared rate limiter instance. If None, creates default.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.stlouisfed.org/fred",
        rate_limiter: TokenBucketRateLimiter | None = None,
    ):
        if not api_key:
            raise ValueError("FRED API key must be provided")
        self._api_key = api_key
        self._base_url = base_url
        self._rate_limiter = rate_limiter or TokenBucketRateLimiter()

    def fetch_series(
        self,
        series_id: str,
        *,
        observation_start: str | None = None,
        observation_end: str | None = None,
        units: str = "lin",
        frequency: str | None = None,
        aggregation_method: str = "avg",
        limit: int = 10,
        sort_order: str = "desc",
        max_retries: int = 3,
    ) -> list[FredObservation]:
        """Fetch observations for a FRED series.

        Args:
            series_id: FRED series identifier (e.g., "DGS10").
            observation_start: ISO date string for start of window.
            observation_end: ISO date string for end of window.
            units: FRED units transform (lin, pch, pc1, ch1, pca, cch, cca, log).
                   Use "pc1" for YoY percent change (server-side).
            frequency: Frequency aggregation (d, w, m, q, a).
            aggregation_method: Aggregation method (avg, sum, eop).
            limit: Max observations to return.
            sort_order: "desc" (newest first) or "asc".
            max_retries: Max retry attempts for transient errors.

        Returns:
            List of FredObservation with parsed values.
            Missing values (".", "#N/A") are filtered out.
        """
        self._rate_limiter.acquire()

        params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": sort_order,
            "limit": limit,
        }
        if observation_start:
            params["observation_start"] = observation_start
        if observation_end:
            params["observation_end"] = observation_end
        if units != "lin":
            params["units"] = units
        if frequency:
            params["frequency"] = frequency
            params["aggregation_method"] = aggregation_method

        url = f"{self._base_url}/series/observations"

        for attempt in range(max_retries):
            try:
                response = httpx.get(url, params=params, timeout=30.0)
                response.raise_for_status()
                data = response.json()

                # FRED can return 200 with error body
                if "error_code" in data:
                    logger.warning(
                        "FRED API error in response body",
                        series=series_id,
                        error_code=data.get("error_code"),
                        error_message=data.get("error_message"),
                    )
                    return []

                return [
                    FredObservation(date=obs["date"], value=parse_fred_value(obs["value"], series_id, obs["date"]))
                    for obs in data.get("observations", [])
                    if parse_fred_value(obs.get("value", ""), series_id, obs.get("date", "")) is not None
                ]

            except httpx.HTTPStatusError as e:
                action = _classify_error(e.response.status_code)
                if action == "fail":
                    logger.error("FRED auth failure", series=series_id, status=e.response.status_code)
                    raise
                if action == "skip":
                    logger.warning("FRED series error, skipping", series=series_id, status=e.response.status_code)
                    return []
                # retry
                wait = min(2 ** attempt * 2, 30)
                logger.warning("FRED retrying", series=series_id, attempt=attempt + 1, wait=wait)
                time.sleep(wait)

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                wait = min(2 ** attempt * 2, 30)
                logger.warning("FRED connection error, retrying", series=series_id, error=str(e), wait=wait)
                time.sleep(wait)

        logger.error("FRED exhausted retries", series=series_id, max_retries=max_retries)
        return []

    def fetch_latest_strict(self, series_id: str, *, limit: int = 10) -> float:
        """Get the most recent numeric value. Raises ValueError if unavailable."""
        obs = self.fetch_series(series_id, limit=limit)
        for o in obs:
            if o.value is not None:
                return o.value
        raise ValueError(f"No valid numeric value in FRED series '{series_id}'")

    def fetch_latest_value(self, series_id: str, *, limit: int = 10) -> float | None:
        """Lenient latest-value helper. Returns None on any failure."""
        try:
            return self.fetch_latest_strict(series_id, limit=limit)
        except Exception:
            return None

    def fetch_latest_two(
        self,
        series_id: str,
        *,
        limit: int = 10,
    ) -> tuple[float | None, float | None]:
        """Return the two newest numeric observations, or (None, None)."""
        try:
            obs = self.fetch_series(series_id, limit=limit)
        except Exception:
            return (None, None)

        values: list[float] = []
        for entry in obs:
            if entry.value is not None:
                values.append(entry.value)
            if len(values) == 2:
                break

        if len(values) < 2:
            return (None, None)
        return (values[0], values[1])

    def fetch_batch(
        self,
        series_configs: list[dict[str, Any]],
        *,
        observation_start: str | None = None,
    ) -> dict[str, list[FredObservation]]:
        """Fetch multiple series sequentially with rate limiting.

        Each config dict should have at minimum: {"series_id": "...", "limit": N}
        Optional keys: "observation_start", "units", "frequency", etc.

        Returns dict mapping series_id to observations list.
        """
        results: dict[str, list[FredObservation]] = {}

        for config in series_configs:
            sid = config["series_id"]
            obs_start = config.get("observation_start", observation_start)
            try:
                obs = self.fetch_series(
                    sid,
                    observation_start=obs_start,
                    observation_end=config.get("observation_end"),
                    units=config.get("units", "lin"),
                    frequency=config.get("frequency"),
                    aggregation_method=config.get("aggregation_method", "avg"),
                    limit=config.get("limit", 10),
                )
                results[sid] = obs
            except Exception as e:
                logger.warning("FRED batch fetch failed for series", series=sid, error=str(e))
                results[sid] = []

        return results


# ---------------------------------------------------------------------------
#  Transform utilities (pure, deterministic)
# ---------------------------------------------------------------------------

EMPTY_TRANSFORM: dict[str, Any] = {
    "series": [],
    "latest": None,
    "latest_date": None,
    "transform_result": None,
    "trend_direction": None,
    "delta_12m": None,
    "delta_12m_pct": None,
}


def apply_transform(
    series_id: str,
    observations: list[FredObservation] | list[dict],
    transform: str | None,
) -> dict[str, Any]:
    """Apply a transform to observations.

    Accepts both FredObservation objects and raw {date, value} dicts
    for backward compatibility with market_data_engine.

    Returns dict with: series, latest, latest_date, transform_result,
    trend_direction, delta_12m, delta_12m_pct.
    """
    if not observations:
        return dict(EMPTY_TRANSFORM)

    # Normalize to {date, value} dicts
    parsed: list[dict[str, Any]] = []
    for o in observations:
        if isinstance(o, FredObservation):
            if o.value is not None:
                parsed.append({"date": o.date, "value": o.value})
        elif isinstance(o, dict):
            try:
                parsed.append({"date": o["date"], "value": float(o["value"])})
            except (ValueError, TypeError, KeyError):
                continue

    if not parsed:
        return dict(EMPTY_TRANSFORM)

    latest = parsed[0]["value"]
    latest_date = parsed[0]["date"]

    # delta vs oldest available in window
    delta_12m = None
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
        full_avg = sum(p["value"] for p in parsed) / len(parsed)
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
            cpi_now = parsed[0]["value"]
            cpi_12m_ago = parsed[12]["value"]
            if cpi_12m_ago > 0:
                transform_result = round((cpi_now / cpi_12m_ago - 1) * 100, 2)
    elif transform == "mom_delta":
        if len(parsed) >= 2:
            transform_result = round(parsed[0]["value"] - parsed[1]["value"], 1)

    return {
        "series": parsed,
        "latest": latest,
        "latest_date": latest_date,
        "transform_result": transform_result,
        "trend_direction": trend_direction,
        "delta_12m": delta_12m,
        "delta_12m_pct": delta_12m_pct,
    }
