"""Macro snapshot builders — reads from macro_data DB table.

v3: Reads pre-ingested FRED data from the global macro_data hypertable
instead of calling the FRED API directly.  The macro_ingestion worker
(wealth vertical) populates macro_data daily for all series including
credit-specific ones (CREDIT_SERIES in regional_macro_service.py).

Imports computed_fields.py, regional.py, stress.py.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.models import MacroData
from quant_engine.fred_service import apply_transform
from vertical_engines.credit.market_data.computed_fields import (
    _compute_cpi_yoy,
    _compute_yield_curve_2s10s,
)
from vertical_engines.credit.market_data.models import FRED_SERIES_REGISTRY
from vertical_engines.credit.market_data.regional import fetch_regional_case_shiller
from vertical_engines.credit.market_data.stress import compute_macro_stress_severity

logger = structlog.get_logger()


def _snapshot_hash(data: dict[str, Any]) -> str:
    """Deterministic hash of a snapshot for integrity verification."""
    encoded = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _fetch_series_from_db(
    db: Session,
    series_ids: list[str],
    *,
    max_observations: int = 252,
) -> dict[str, list[dict[str, str]]]:
    """Batch-fetch recent observations for multiple FRED series from macro_data.

    Returns dict mapping series_id → list of {date, value} dicts sorted
    descending (newest first), matching the format that apply_transform() expects.
    """
    # Single query: all series, last N observations each, ordered desc
    # Use a lateral subquery approach via window function for per-series limit
    stmt = (
        select(MacroData.series_id, MacroData.obs_date, MacroData.value)
        .where(MacroData.series_id.in_(series_ids))
        .order_by(MacroData.series_id, MacroData.obs_date.desc())
    )
    rows = db.execute(stmt).all()

    # Group by series_id and limit to max_observations per series
    result: dict[str, list[dict[str, str]]] = {sid: [] for sid in series_ids}
    for series_id, obs_date, value in rows:
        if series_id not in result:
            continue
        if len(result[series_id]) >= max_observations:
            continue
        result[series_id].append({
            "date": obs_date.isoformat() if isinstance(obs_date, dt.date) else str(obs_date),
            "value": str(value),
        })

    return result


def _build_macro_snapshot(
    db: Session,
    *,
    deal_geography: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible entrypoint used by tests and cache orchestration."""
    return _build_macro_snapshot_expanded(db, deal_geography=deal_geography)


def _build_macro_snapshot_legacy(db: Session) -> dict[str, Any]:
    """Legacy v1 snapshot builder — 8 scalar series only.

    Kept for testing and fallback. New code should use
    _build_macro_snapshot_expanded() instead.
    """
    logger.info("market_data_fetch_start_legacy")

    legacy_series = [
        "DGS10", "DGS2", "BAA10Y", "UNRATE", "NFCI", "USREC",
        "CPIAUCSL", "A191RL1Q225SBEA", "BAMLH0A0HYM2", "SOFR",
    ]
    all_obs = _fetch_series_from_db(db, legacy_series, max_observations=15)

    def _latest_float(sid: str) -> float:
        obs = all_obs.get(sid, [])
        if not obs:
            raise ValueError(f"No observations in macro_data for series '{sid}'")
        return float(obs[0]["value"])

    def _latest_float_opt(sid: str) -> float | None:
        obs = all_obs.get(sid, [])
        if not obs:
            return None
        try:
            return float(obs[0]["value"])
        except (ValueError, TypeError):
            return None

    risk_free_10y = _latest_float("DGS10")
    risk_free_2y = _latest_float("DGS2")
    baa_spread = _latest_float("BAA10Y")
    unemployment = _latest_float("UNRATE")
    financial_cond = _latest_float("NFCI")
    recession_raw = _latest_float("USREC")

    # CPI YoY (computed from index levels)
    obs_cpi = all_obs.get("CPIAUCSL", [])
    valid_cpi = [float(o["value"]) for o in obs_cpi if o["value"] not in ("", ".")]
    if len(valid_cpi) < 13:
        raise ValueError(f"CPIAUCSL: need >=13 monthly obs, got {len(valid_cpi)}")
    cpi_yoy = _compute_cpi_yoy(valid_cpi[0], valid_cpi[12])

    gdp_yoy = _latest_float_opt("A191RL1Q225SBEA")
    hy_spread_proxy = _latest_float_opt("BAMLH0A0HYM2")
    sofr_rate = _latest_float_opt("SOFR")

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


def _build_macro_snapshot_expanded(
    db: Session,
    *,
    deal_geography: str | None = None,
) -> dict[str, Any]:
    """Read all FRED series from macro_data table and build expanded snapshot.

    Each series returns a full time-series curve + derived signals.
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

    # Batch-fetch all series from macro_data in one query
    series_ids = list(FRED_SERIES_REGISTRY.keys())
    max_obs = max(entry["observations"] for entry in FRED_SERIES_REGISTRY.values())
    all_obs = _fetch_series_from_db(db, series_ids, max_observations=max_obs)

    # Process each registry series
    for series_id, entry in FRED_SERIES_REGISTRY.items():
        category = entry["category"]
        is_critical = entry["critical"]
        transform = entry["transform"]

        obs = all_obs.get(series_id, [])

        try:
            if not obs:
                raise ValueError(f"No observations in macro_data for series '{series_id}'")

            transformed = apply_transform(series_id, obs, transform)
            transformed["label"] = entry["label"]
            transformed["fred_series"] = series_id
            result[category][series_id] = transformed

            logger.debug(
                "macro_data_series_ok",
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
            logger.warning("macro_data_series_missing", series=series_id, error=str(exc))

    # Regional Case-Shiller (optional, deal-specific — from macro_data)
    if deal_geography:
        regional = fetch_regional_case_shiller(db, deal_geography, observations=24)
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
