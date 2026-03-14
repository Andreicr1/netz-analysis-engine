"""TA-Lib momentum signals computed from existing nav_timeseries data.

Replaces the hardcoded flows_momentum=50.0 stub in scoring_service.py.
No external API required — all signals derived from NAV data already in DB.

Optional dependency: ta-lib>=0.4 (timeseries group).
Install: pip install netz-wealth-os[timeseries]

Note: TA-Lib requires the C library. See https://ta-lib.github.io/ta-lib-python/
"""

import numpy as np
import structlog

logger = structlog.get_logger()

# Minimum NAV observations needed for a reliable momentum signal.
# BBANDS(20) needs 20 + warm-up; RSI(14) needs 14 + warm-up.
MIN_NAV_OBSERVATIONS = 30


def compute_momentum_signals_talib(close: np.ndarray) -> dict[str, float]:
    """Compute RSI and Bollinger Band position from a NAV price series.

    Uses existing nav_timeseries data — no external API call required.
    All indicators are computed in-process via TA-Lib.

    Returns dict with:
        rsi_norm: RSI(14) normalised to [0, 1]  (0=oversold, 1=overbought)
        bb_pos:   position within BB(20, 2σ)    (0=lower band, 1=upper band)
        momentum_score: weighted composite      (0–100, 50=neutral)
    """
    try:
        import talib  # type: ignore[import]
    except ImportError:
        logger.debug("ta-lib not installed; returning neutral momentum score")
        return {"rsi_norm": 0.5, "bb_pos": 0.5, "momentum_score": 50.0}

    if len(close) < MIN_NAV_OBSERVATIONS:
        return {"rsi_norm": 0.5, "bb_pos": 0.5, "momentum_score": 50.0}

    close_f = close.astype(float)

    # RSI(14) — last valid value
    rsi = talib.RSI(close_f, timeperiod=14)
    last_rsi = next((v for v in reversed(rsi) if not np.isnan(v)), None)
    rsi_norm = float(last_rsi) / 100.0 if last_rsi is not None else 0.5

    # Bollinger Bands (20, 2σ) — last valid values
    upper, _, lower = talib.BBANDS(close_f, timeperiod=20, nbdevup=2, nbdevdn=2)
    last_upper = next((v for v in reversed(upper) if not np.isnan(v)), None)
    last_lower = next((v for v in reversed(lower) if not np.isnan(v)), None)
    last_close = float(close_f[-1])

    if last_upper is not None and last_lower is not None:
        bb_range = float(last_upper - last_lower)
        bb_pos = float((last_close - last_lower) / (bb_range + 1e-8)) if bb_range > 0 else 0.5
        bb_pos = max(0.0, min(1.0, bb_pos))
    else:
        bb_pos = 0.5

    momentum_score = round((0.5 * rsi_norm + 0.5 * bb_pos) * 100.0, 2)

    return {
        "rsi_norm": round(rsi_norm, 4),
        "bb_pos": round(bb_pos, 4),
        "momentum_score": momentum_score,
    }


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
