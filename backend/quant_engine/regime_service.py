"""Market regime detection service.

Classifies market regime using multi-signal approach:
- VIX (from FRED VIXCLS) for volatility stress
- Yield curve (DGS10-DGS2 spread) for recession risk
- CPI YoY for inflation
- Falls back to portfolio volatility proxy when FRED data unavailable

Priority hierarchy: CRISIS > INFLATION > RISK_OFF > RISK_ON
"""

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import TypedDict

import numpy as np
import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_calibration_path
from app.domains.wealth.models.macro import MacroData
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from app.schemas.risk import RegimeRead

logger = structlog.get_logger()


class RegimeThresholds(TypedDict):
    """Typed regime detection thresholds from limits.yaml."""

    vix_risk_off: float
    vix_extreme: float
    yield_curve_inversion: float
    cpi_yoy_high: float
    cpi_yoy_normal: float
    sahm_rule_recession: float  # SAHMREALTIME >= this = recession signal
    default: str


class RegimeDefinition(TypedDict):
    """Typed definition for a single market regime."""

    description: str


# Hardcoded fallback if limits.yaml is missing
_DEFAULT_THRESHOLDS: RegimeThresholds = {
    "vix_risk_off": 25,
    "vix_extreme": 35,
    "yield_curve_inversion": -0.10,
    "cpi_yoy_high": 4.0,
    "cpi_yoy_normal": 2.5,
    "sahm_rule_recession": 0.50,  # Sahm (2019): 0.50pp rise from 12m low = recession onset
    "default": "RISK_ON",
}

REGIME_DEFINITIONS: dict[str, RegimeDefinition] = {
    "RISK_ON": {"description": "Normal market conditions, risk appetite high"},
    "RISK_OFF": {"description": "Elevated volatility, defensive positioning"},
    "INFLATION": {"description": "Above-target inflation, favor real assets"},
    "CRISIS": {"description": "Extreme stress, maximize capital preservation"},
}

# Staleness thresholds (business days) before falling back to volatility proxy
STALENESS_DAILY = 3   # VIX, Treasury, DFF
STALENESS_MONTHLY = 45  # CPI


@lru_cache(maxsize=1)
def get_regime_thresholds() -> RegimeThresholds:
    """Load regime thresholds from limits.yaml, fallback to hardcoded defaults."""
    try:
        config_path = get_calibration_path() / "limits.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)
        raw = data["regime_thresholds"]
        return RegimeThresholds(
            vix_risk_off=float(raw["vix_risk_off"]),
            vix_extreme=float(raw["vix_extreme"]),
            yield_curve_inversion=float(raw.get("yield_curve_inversion", -0.10)),
            cpi_yoy_high=float(raw.get("cpi_yoy_high", 4.0)),
            cpi_yoy_normal=float(raw.get("cpi_yoy_normal", 2.5)),
            sahm_rule_recession=float(raw.get("sahm_rule_recession", 0.50)),
            default=raw.get("default", "RISK_ON"),
        )
    except FileNotFoundError:
        logger.warning("limits.yaml not found, using default regime thresholds")
        return _DEFAULT_THRESHOLDS
    except (KeyError, TypeError, ValueError) as e:
        logger.error("limits.yaml malformed for regime_thresholds", error=str(e))
        return _DEFAULT_THRESHOLDS


@dataclass
class RegimeResult:
    regime: str
    description: str | None = None
    reasons: dict[str, str] = field(default_factory=dict)


def classify_regime_multi_signal(
    vix: float | None,
    yield_curve_spread: float | None,
    cpi_yoy: float | None,
    sahm_rule: float | None = None,
    thresholds: RegimeThresholds | None = None,
) -> tuple[str, dict[str, str]]:
    """Classify regime using priority hierarchy:

    1. VIX >= vix_extreme (35) -> CRISIS
    2. CPI YoY >= cpi_yoy_high (4.0) -> INFLATION
    3. VIX >= vix_risk_off (25) -> RISK_OFF
    4. Otherwise -> RISK_ON

    Informational signals (logged for IC awareness, do not override hierarchy):
    - Yield curve inversion: leading indicator of future recession
    - Sahm Rule >= 0.50: real-time recession onset corroboration (Sahm 2019)

    Returns (regime, reasons_dict) for auditability.
    """
    if thresholds is None:
        thresholds = get_regime_thresholds()

    reasons: dict[str, str] = {}

    # Rule 1: CRISIS — extreme volatility
    if vix is not None and vix >= thresholds["vix_extreme"]:
        reasons["vix"] = f"VIX={vix:.1f} >= {thresholds['vix_extreme']} (CRISIS)"
        reasons["decision"] = "CRISIS: extreme VIX overrides all other signals"
        return "CRISIS", reasons

    # Rule 2: INFLATION — high CPI regardless of VIX
    if cpi_yoy is not None and cpi_yoy >= thresholds["cpi_yoy_high"]:
        reasons["cpi"] = f"CPI_YoY={cpi_yoy:.1f}% >= {thresholds['cpi_yoy_high']}% (INFLATION)"
        reasons["decision"] = "INFLATION: CPI above threshold"
        return "INFLATION", reasons

    # Rule 3: RISK_OFF — elevated VIX
    if vix is not None and vix >= thresholds["vix_risk_off"]:
        reasons["vix"] = f"VIX={vix:.1f} >= {thresholds['vix_risk_off']} (RISK_OFF)"
        reasons["decision"] = "RISK_OFF: elevated volatility"
        return "RISK_OFF", reasons

    # Informational signals — logged for IC awareness, do not override hierarchy
    if yield_curve_spread is not None and yield_curve_spread < thresholds["yield_curve_inversion"]:
        reasons["yield_curve"] = (
            f"10Y-2Y={yield_curve_spread:.2f}% inverted "
            f"(threshold: {thresholds['yield_curve_inversion']}%) — IC awareness"
        )

    if sahm_rule is not None and sahm_rule >= thresholds["sahm_rule_recession"]:
        reasons["sahm_rule"] = (
            f"Sahm={sahm_rule:.2f} >= {thresholds['sahm_rule_recession']} "
            f"(recession onset signal — IC awareness)"
        )

    # Rule 4: Default
    if vix is not None:
        reasons["vix"] = f"VIX={vix:.1f} < {thresholds['vix_risk_off']} (RISK_ON)"
    reasons["decision"] = "RISK_ON: no stress signals triggered"
    return "RISK_ON", reasons


def classify_regime_from_volatility(
    annualized_vol: float,
    vix_risk_off: float = 25.0,
    vix_extreme: float = 35.0,
) -> str:
    """Fallback: classify regime from portfolio volatility proxy.

    Maps portfolio volatility to VIX-equivalent thresholds.
    Used when FRED data is unavailable or stale.
    """
    vol_pct = annualized_vol * 100

    if vol_pct >= vix_extreme:
        return "CRISIS"
    if vol_pct >= vix_risk_off:
        return "RISK_OFF"
    return "RISK_ON"


def detect_regime(
    returns: np.ndarray,
    trading_days_per_year: int = 252,
) -> RegimeResult:
    """Detect market regime from a returns series (volatility proxy fallback).

    Used when FRED macro data is unavailable.
    """
    thresholds = get_regime_thresholds()

    if len(returns) < 10:
        default = thresholds["default"]
        return RegimeResult(
            regime=default,
            description=REGIME_DEFINITIONS.get(default, {}).get("description"),
            reasons={"decision": "insufficient data, using default"},
        )

    vol = float(np.std(returns) * np.sqrt(trading_days_per_year))
    regime = classify_regime_from_volatility(
        vol,
        vix_risk_off=thresholds["vix_risk_off"],
        vix_extreme=thresholds["vix_extreme"],
    )

    return RegimeResult(
        regime=regime,
        description=REGIME_DEFINITIONS.get(regime, {}).get("description"),
        reasons={"volatility_proxy": f"annualized_vol={vol:.4f}"},
    )


async def get_latest_macro_values(
    db: AsyncSession,
) -> dict[str, tuple[float | None, date | None]]:
    """Query latest VIX, yield curve spread, CPI YoY, Fed Funds from macro_data.

    Returns {series_id: (value, obs_date)} for regime-relevant series.
    Logs warnings for stale data.
    """
    series_staleness = {
        "VIXCLS": STALENESS_DAILY,
        "YIELD_CURVE_10Y2Y": STALENESS_DAILY,
        "CPI_YOY": STALENESS_MONTHLY,
        "DFF": STALENESS_DAILY,
        "SAHMREALTIME": STALENESS_MONTHLY,  # published with jobs report
    }

    result: dict[str, tuple[float | None, date | None]] = {}
    today = date.today()

    # Single query for all series using DISTINCT ON
    stmt = (
        select(MacroData.series_id, MacroData.value, MacroData.obs_date)
        .where(MacroData.series_id.in_(series_staleness.keys()))
        .distinct(MacroData.series_id)
        .order_by(MacroData.series_id, MacroData.obs_date.desc())
    )
    rows = (await db.execute(stmt)).all()

    found_series = set()
    for series_id, value, obs_date in rows:
        found_series.add(series_id)
        max_stale = series_staleness.get(series_id, STALENESS_DAILY)
        days_stale = (today - obs_date).days

        if days_stale > max_stale:
            logger.warning(
                "FRED data stale",
                series=series_id,
                last_date=str(obs_date),
                days_stale=days_stale,
                threshold=max_stale,
            )
            result[series_id] = (None, obs_date)
        else:
            result[series_id] = (float(value), obs_date)

    # Mark missing series
    for series_id in series_staleness:
        if series_id not in found_series:
            result[series_id] = (None, None)

    return result


async def get_current_regime(db: AsyncSession) -> RegimeRead:
    """Get current market regime from FRED macro data.

    Falls back to latest portfolio snapshot regime if FRED data unavailable.
    Replaces the old consensus-voting approach since regime is market-wide.
    """
    macro = await get_latest_macro_values(db)

    vix_val = macro.get("VIXCLS", (None, None))[0]
    yield_val = macro.get("YIELD_CURVE_10Y2Y", (None, None))[0]
    cpi_val = macro.get("CPI_YOY", (None, None))[0]
    sahm_val = macro.get("SAHMREALTIME", (None, None))[0]

    # If we have at least VIX, use multi-signal classification
    if vix_val is not None:
        regime, reasons = classify_regime_multi_signal(
            vix_val, yield_val, cpi_val, sahm_rule=sahm_val
        )

        # Find most recent date across available series
        as_of = None
        for _, obs_date in macro.values():
            if obs_date is not None and (as_of is None or obs_date > as_of):
                as_of = obs_date

        return RegimeRead(
            regime=regime,
            as_of_date=as_of,
            reasons=reasons,
        )

    # Fallback: query latest snapshot for regime
    logger.info("No FRED macro data available, falling back to snapshot regime")
    stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.regime.is_not(None))
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    snap = result.scalar_one_or_none()

    return RegimeRead(
        regime=snap.regime if snap else "RISK_ON",
        as_of_date=snap.snapshot_date if snap else None,
        reasons={"source": "volatility_proxy_fallback"},
    )
