"""Macro snapshot builders (legacy v1 + expanded v2).

Imports fred_client.py, computed_fields.py, regional.py, stress.py.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from typing import Any

import structlog

from quant_engine.fred_service import apply_transform
from vertical_engines.credit.market_data.computed_fields import (
    _compute_cpi_yoy,
    _compute_yield_curve_2s10s,
)
from vertical_engines.credit.market_data.fred_client import (
    _fetch_fred_series,
    _fetch_latest_strict,
)
from vertical_engines.credit.market_data.models import (
    FRED_SERIES_REGISTRY,
    FRED_SLEEP_BETWEEN_CALLS,
)
from vertical_engines.credit.market_data.regional import fetch_regional_case_shiller
from vertical_engines.credit.market_data.stress import compute_macro_stress_severity

logger = structlog.get_logger()


def _snapshot_hash(data: dict[str, Any]) -> str:
    """Deterministic hash of a snapshot for integrity verification."""
    encoded = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _build_macro_snapshot_legacy() -> dict[str, Any]:
    """Legacy v1 snapshot builder — 8 scalar series only.

    Kept for testing and fallback. New code should use
    _build_macro_snapshot_expanded() instead.
    """
    logger.info("market_data_fetch_start_legacy")

    risk_free_10y = _fetch_latest_strict("DGS10")
    risk_free_2y = _fetch_latest_strict("DGS2")
    baa_spread = _fetch_latest_strict("BAA10Y")
    unemployment = _fetch_latest_strict("UNRATE")
    financial_cond = _fetch_latest_strict("NFCI")
    recession_raw = _fetch_latest_strict("USREC")

    # CPI YoY (computed from index levels)
    obs_cpi = _fetch_fred_series("CPIAUCSL", limit=15)
    valid_cpi = [float(o["value"]) for o in obs_cpi if o["value"] not in ("", ".")]
    if len(valid_cpi) < 13:
        raise ValueError(f"CPIAUCSL: need >=13 monthly obs, got {len(valid_cpi)}")
    cpi_yoy = _compute_cpi_yoy(valid_cpi[0], valid_cpi[12])

    gdp_yoy: float | None = None
    try:
        gdp_yoy = _fetch_latest_strict("A191RL1Q225SBEA")
    except Exception as exc:
        logger.warning("fred_gdp_yoy_unavailable", error=str(exc))

    hy_spread_proxy: float | None = None
    try:
        hy_spread_proxy = _fetch_latest_strict("BAMLH0A0HYM2")
    except Exception:
        pass

    sofr_rate: float | None = None
    try:
        sofr_rate = _fetch_latest_strict("SOFR")
    except Exception:
        pass

    yield_curve = _compute_yield_curve_2s10s(risk_free_10y, risk_free_2y)
    recession_flag = recession_raw >= 1.0

    snapshot: dict[str, Any] = {
        "risk_free_10y": risk_free_10y,
        "risk_free_2y": risk_free_2y,
        "yield_curve_2s10s": yield_curve,
        "baa_spread": baa_spread,
        "hy_spread_proxy": hy_spread_proxy,
        "sofr_rate": sofr_rate,
        "base_rate_short": sofr_rate if sofr_rate is not None else risk_free_2y,
        "cpi_yoy": cpi_yoy,
        "gdp_yoy": gdp_yoy,
        "unemployment_rate": unemployment,
        "financial_conditions_index": financial_cond,
        "recession_flag": recession_flag,
        "as_of_date": dt.date.today().isoformat(),
    }

    _CRITICAL = (
        "risk_free_10y", "risk_free_2y", "yield_curve_2s10s",
        "baa_spread", "cpi_yoy", "unemployment_rate",
        "financial_conditions_index", "recession_flag", "base_rate_short",
    )
    missing = [f for f in _CRITICAL if snapshot.get(f) is None]
    if missing:
        raise RuntimeError(
            f"MACRO_SNAPSHOT_INCOMPLETE — critical fields are None: {missing}",
        )
    return snapshot


def _build_macro_snapshot(*, deal_geography: str | None = None) -> dict[str, Any]:
    """Backward-compatible entrypoint used by tests and cache orchestration."""
    return _build_macro_snapshot_expanded(deal_geography=deal_geography)


def _build_macro_snapshot_expanded(
    *,
    deal_geography: str | None = None,
) -> dict[str, Any]:
    """Fetch all FRED series from FRED_SERIES_REGISTRY and build expanded snapshot.

    Each series returns a full 12-month time-series curve + derived signals.
    Critical series raise RuntimeError on failure; non-critical use None fallback.

    deal_geography: optional free-form location string for regional Case-Shiller.
    Note: regional data is NOT persisted in the base cache (deal-specific).
    """
    logger.info("macro_snapshot_expanded_start")

    result: dict[str, Any] = {
        "rates_spreads": {},
        "real_estate_national": {},
        "mortgage": {},
        "credit_quality": {},
        "banking_activity": {},
        "macro_fundamentals": {},
        "regional": {},
        "as_of_date": dt.date.today().isoformat(),
        "schema_version": "v2_expanded",
    }

    # Fetch all registry series
    for series_id, entry in FRED_SERIES_REGISTRY.items():
        category = entry["category"]
        is_critical = entry["critical"]
        n_obs = entry["observations"]
        transform = entry["transform"]

        try:
            obs = _fetch_fred_series(series_id, limit=n_obs)
            transformed = apply_transform(series_id, obs, transform)
            transformed["label"] = entry["label"]
            transformed["fred_series"] = series_id
            result[category][series_id] = transformed

            logger.debug(
                "fred_series_ok",
                series=series_id,
                latest=transformed.get("latest"),
                trend=transformed.get("trend_direction"),
            )
        except Exception as exc:
            if is_critical:
                raise RuntimeError(
                    f"MACRO_SNAPSHOT_CRITICAL_FAILURE — series '{series_id}' "
                    f"({entry['label']}) failed: {exc}",
                ) from exc
            result[category][series_id] = {
                "series": [], "latest": None, "latest_date": None,
                "transform_result": None, "trend_direction": None,
                "delta_12m": None, "delta_12m_pct": None,
                "label": entry["label"],
                "fred_series": series_id,
                "error": str(exc),
            }
            logger.warning("fred_series_failed", series=series_id, error=str(exc))

        # Rate-limit buffer (120 req/min; ~35 calls — well within limit)
        time.sleep(FRED_SLEEP_BETWEEN_CALLS)

    # Regional Case-Shiller (optional, deal-specific)
    if deal_geography:
        regional = fetch_regional_case_shiller(deal_geography, observations=24)
        if regional:
            result["regional"]["case_shiller_metro"] = regional
            result["regional"]["national_vs_metro_delta"] = None
            national = result["real_estate_national"].get("CSUSHPINSA", {})
            nat_yoy = national.get("delta_12m_pct")
            metro_yoy = regional.get("delta_12m_pct")
            if nat_yoy is not None and metro_yoy is not None:
                result["regional"]["national_vs_metro_delta"] = round(
                    metro_yoy - nat_yoy, 2,
                )

    # Compute backward-compatible scalar fields
    rates = result["rates_spreads"]
    macro = result["macro_fundamentals"]

    def _latest(cat: dict[str, Any], sid: str) -> float | None:
        return (cat.get(sid) or {}).get("latest")

    risk_free_10y = _latest(rates, "DGS10")
    risk_free_2y = _latest(rates, "DGS2")
    baa_spread = _latest(rates, "BAA10Y")
    sofr_rate = _latest(rates, "SOFR")
    nfci = _latest(rates, "NFCI")
    recession_raw = _latest(macro, "USREC")
    unemployment = _latest(macro, "UNRATE")
    cpi_yoy = (macro.get("CPIAUCSL") or {}).get("transform_result")
    gdp_yoy = _latest(macro, "A191RL1Q225SBEA")
    hy_spread = _latest(rates, "BAMLH0A0HYM2")

    # Validate critical scalars
    _CRITICAL_SCALARS: dict[str, Any] = {
        "risk_free_10y": risk_free_10y,
        "risk_free_2y": risk_free_2y,
        "baa_spread": baa_spread,
        "unemployment_rate": unemployment,
        "financial_conditions_index": nfci,
        "cpi_yoy": cpi_yoy,
    }
    missing = [k for k, v in _CRITICAL_SCALARS.items() if v is None]
    if missing:
        raise RuntimeError(
            f"MACRO_SNAPSHOT_INCOMPLETE — critical scalars None after fetch: {missing}",
        )

    assert risk_free_10y is not None
    assert risk_free_2y is not None
    base_rate = sofr_rate if sofr_rate is not None else risk_free_2y
    yield_curve = round(risk_free_10y - risk_free_2y, 4)
    recession_flag = (recession_raw or 0) >= 1.0

    # Inject flat scalars at top level for backward compatibility
    result.update({
        "risk_free_10y": risk_free_10y,
        "risk_free_2y": risk_free_2y,
        "yield_curve_2s10s": yield_curve,
        "baa_spread": baa_spread,
        "hy_spread_proxy": hy_spread,
        "sofr_rate": sofr_rate,
        "base_rate_short": base_rate,
        "cpi_yoy": cpi_yoy,
        "gdp_yoy": gdp_yoy,
        "unemployment_rate": unemployment,
        "financial_conditions_index": nfci,
        "recession_flag": recession_flag,
    })

    # Embed stress severity into snapshot
    result["stress_severity"] = compute_macro_stress_severity(result)

    # Summary counters for logging
    _MODULE_KEYS = [
        "rates_spreads", "real_estate_national", "mortgage",
        "credit_quality", "banking_activity", "macro_fundamentals",
    ]
    series_ok = sum(1 for k in _MODULE_KEYS for s in result[k].values() if s.get("latest") is not None)
    series_failed = sum(1 for k in _MODULE_KEYS for s in result[k].values() if s.get("latest") is None)

    logger.info(
        "macro_snapshot_expanded_complete",
        as_of=result["as_of_date"],
        hash=_snapshot_hash(result),
        series_ok=series_ok,
        series_failed=series_failed,
        stress=result["stress_severity"]["level"],
    )

    return result
