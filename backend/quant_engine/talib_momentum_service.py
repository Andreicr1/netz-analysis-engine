"""TA-Lib momentum signals computed from existing nav_timeseries data.

Replaces the hardcoded flows_momentum=50.0 stub in scoring_service.py.
No external API required — all signals derived from NAV data already in DB.

Priority: ta-lib (C wrapper, fastest) → pandas-ta (pure Python fallback).
If neither is available, returns None values (honest degradation).
"""

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()

# Minimum NAV observations needed for a reliable momentum signal.
# BBANDS(20) needs 20 + warm-up; RSI(14) needs 14 + warm-up.
MIN_NAV_OBSERVATIONS = 30

# ── Backend detection ──────────────────────────────────────────────────────

try:
    import talib as _talib  # type: ignore[import-not-found]

    _BACKEND = "talib"
except ImportError:
    _talib = None
    try:
        import pandas_ta as _pta  # type: ignore[import-not-found]

        _BACKEND = "pandas_ta"
    except ImportError:
        _pta = None
        _BACKEND = "none"

_NEUTRAL: dict[str, float | None] = {"rsi_norm": None, "bb_pos": None, "momentum_score": None}


def _compute_talib(close_f: np.ndarray) -> dict[str, float | None]:
    """Compute momentum signals using TA-Lib C wrapper."""
    assert _talib is not None

    rsi = _talib.RSI(close_f, timeperiod=14)
    last_rsi = next((v for v in reversed(rsi) if not np.isnan(v)), None)
    rsi_norm = float(last_rsi) / 100.0 if last_rsi is not None else None

    upper, _, lower = _talib.BBANDS(close_f, timeperiod=20, nbdevup=2, nbdevdn=2)
    last_upper = next((v for v in reversed(upper) if not np.isnan(v)), None)
    last_lower = next((v for v in reversed(lower) if not np.isnan(v)), None)

    return _assemble(rsi_norm, last_upper, last_lower, float(close_f[-1]))


def _compute_pandas_ta(close_f: np.ndarray) -> dict[str, float | None]:
    """Compute momentum signals using pandas-ta (pure Python)."""
    assert _pta is not None

    s = pd.Series(close_f)

    rsi_series = _pta.rsi(s, length=14)
    last_rsi = None
    if rsi_series is not None and len(rsi_series) > 0:
        last_rsi = rsi_series.dropna().iloc[-1] if not rsi_series.dropna().empty else None
    rsi_norm = float(last_rsi) / 100.0 if last_rsi is not None else None

    bb = _pta.bbands(s, length=20, std=2)
    last_upper = None
    last_lower = None
    if bb is not None and not bb.empty:
        upper_col = [c for c in bb.columns if c.startswith("BBU_")]
        lower_col = [c for c in bb.columns if c.startswith("BBL_")]
        if upper_col:
            vals = bb[upper_col[0]].dropna()
            last_upper = float(vals.iloc[-1]) if not vals.empty else None
        if lower_col:
            vals = bb[lower_col[0]].dropna()
            last_lower = float(vals.iloc[-1]) if not vals.empty else None

    return _assemble(rsi_norm, last_upper, last_lower, float(close_f[-1]))


def _assemble(
    rsi_norm: float | None,
    last_upper: float | None,
    last_lower: float | None,
    last_close: float,
) -> dict[str, float | None]:
    """Assemble final signal dict from indicator values."""
    bb_pos: float | None = None
    if last_upper is not None and last_lower is not None:
        bb_range = last_upper - last_lower
        if bb_range > 0:
            bb_pos = max(0.0, min(1.0, (last_close - last_lower) / (bb_range + 1e-8)))

    if rsi_norm is not None and bb_pos is not None:
        momentum_score = round((0.5 * rsi_norm + 0.5 * bb_pos) * 100.0, 2)
    elif rsi_norm is not None:
        momentum_score = round(rsi_norm * 100.0, 2)
    elif bb_pos is not None:
        momentum_score = round(bb_pos * 100.0, 2)
    else:
        momentum_score = None

    return {
        "rsi_norm": round(rsi_norm, 4) if rsi_norm is not None else None,
        "bb_pos": round(bb_pos, 4) if bb_pos is not None else None,
        "momentum_score": momentum_score,
    }


def compute_momentum_signals_talib(close: np.ndarray) -> dict[str, float | None]:
    """Compute RSI and Bollinger Band position from a NAV price series.

    Uses existing nav_timeseries data — no external API call required.
    Priority: ta-lib (C) → pandas-ta (pure Python) → None (honest degradation).

    Returns dict with:
        rsi_norm: RSI(14) normalised to [0, 1]  (0=oversold, 1=overbought)
        bb_pos:   position within BB(20, 2σ)    (0=lower band, 1=upper band)
        momentum_score: weighted composite      (0–100, 50=neutral)

    All values are None when no backend is available (not fake neutrals).
    """
    if _BACKEND == "none":
        logger.warning("no momentum backend available (ta-lib or pandas-ta); returning None")
        return _NEUTRAL.copy()

    if len(close) < MIN_NAV_OBSERVATIONS:
        return _NEUTRAL.copy()

    close_f = close.astype(float)

    if _BACKEND == "talib":
        return _compute_talib(close_f)
    return _compute_pandas_ta(close_f)


def compute_flow_momentum(
    nav_values: np.ndarray,
    net_flows: np.ndarray,
    period: int = 21,
) -> float:
    """AUM flow momentum — OBV analog for fund net flows (captures − redemptions).

    Uses CVM daily flow data (CAPTC_DIA − RESG_DIA) as volume proxy.
    Positive slope → accumulation (inflows > outflows).
    Negative slope → distribution (outflows > inflows).

    Returns a momentum slope value (positive = accumulation, negative = distribution).
    Returns 0.0 when data is insufficient.
    """
    if len(nav_values) < 2 or len(net_flows) < 2:
        return 0.0

    n = min(len(nav_values), len(net_flows))
    nav_arr = np.array(nav_values[-n:], dtype=float)
    flow_arr = np.array(net_flows[-n:], dtype=float)

    # OBV accumulation: add net flows when NAV rises, subtract when NAV falls
    flow_obv = np.zeros(n)
    for i in range(1, n):
        if nav_arr[i] >= nav_arr[i - 1]:
            flow_obv[i] = flow_obv[i - 1] + flow_arr[i]
        else:
            flow_obv[i] = flow_obv[i - 1] - flow_arr[i]

    # Linear slope of OBV over the last `period` days
    tail = flow_obv[-period:]
    if len(tail) < 2:
        return 0.0

    if not np.all(np.isfinite(tail)):
        return 0.0  # safe fallback: NaN/inf in OBV tail (from null aum_usd)

    slope = float(np.polyfit(np.arange(len(tail)), tail, 1)[0])
    return slope


def normalize_flow_momentum(slope: float, scale: float = 1e6) -> float:
    """Normalise OBV slope to 0-100 score.

    scale: expected order of magnitude for the slope (e.g. 1M BRL/day).
    Returns 50.0 for zero slope (neutral), <50 for distribution, >50 for accumulation.
    """
    # Sigmoid-like squash: tanh maps ℝ → (-1, 1), then scale to (0, 100)
    normalised = float(np.tanh(slope / (scale + 1e-10)))
    return round(50.0 + normalised * 50.0, 2)
