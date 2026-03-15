"""FRED API retrieval functions (deterministic, no LLM).

Imports only models.py (leaf).
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.core.config import settings
from vertical_engines.credit.market_data.models import FRED_BASE_URL

logger = structlog.get_logger()

_FRED_API_KEY = settings.fred_api_key or ""


def _fetch_fred_series(
    series_id: str,
    *,
    observation_start: str | None = None,
    limit: int = 10,
) -> list[dict[str, str]]:
    """Fetch recent observations for a FRED series.

    Returns list of {date, value} dicts sorted descending (newest first).
    Raises on HTTP error. Never fabricates values.
    """
    if not _FRED_API_KEY:
        raise ValueError("FRED_API_KEY not configured — cannot fetch macro data.")

    url = f"{FRED_BASE_URL}/series/observations"
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
