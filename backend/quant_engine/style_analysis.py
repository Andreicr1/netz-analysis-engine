"""Fund style classification from N-PORT holdings.

Sync-pure module: zero I/O, zero imports from ``app.*`` or ``vertical_engines.*``.
Config is injected as parameter — never reads YAML at runtime, never uses @lru_cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

StyleLabel = Literal[
    "large_growth", "large_blend", "large_value",
    "mid_growth", "mid_blend", "mid_value",
    "small_growth", "small_blend", "small_value",
    "fixed_income", "mixed", "unknown",
]

GROWTH_SECTORS = frozenset({
    "Information Technology", "Health Care", "Consumer Discretionary",
    "Communication Services", "Industrials",
})
VALUE_SECTORS = frozenset({
    "Financials", "Energy", "Utilities", "Materials",
    "Consumer Staples", "Real Estate",
})


@dataclass(frozen=True)
class StyleConfig:
    """Thresholds for style classification."""

    min_holdings_for_confidence: int = 10
    equity_threshold: float = 0.60
    fixed_income_threshold: float = 0.60
    growth_tilt_threshold: float = 0.55


@dataclass(frozen=True)
class StyleVector:
    """Result of fund style classification."""

    style_label: StyleLabel
    growth_tilt: float
    sector_weights: dict[str, float]
    equity_pct: float | None
    fixed_income_pct: float | None
    cash_pct: float | None
    confidence: float


_EQUITY_CLASSES = frozenset({
    "EC", "equity", "common stock", "preferred stock",
    "COM", "CS", "PS", "SHS", "SHARES",
})
_FIXED_INCOME_CLASSES = frozenset({
    "DBT", "debt", "bond", "note", "fixed income",
    "DB", "BOND", "NT", "MBS", "ABS", "CLO",
})
_CASH_CLASSES = frozenset({
    "cash", "money market", "repurchase agreement",
    "STIV", "MM", "RP", "REPO",
})


def _classify_asset(asset_class: str | None) -> str:
    """Classify asset_class string into 'equity', 'fixed_income', 'cash', or 'other'."""
    if not asset_class:
        return "other"
    ac = asset_class.strip().upper()
    ac_lower = asset_class.strip().lower()
    if ac in _EQUITY_CLASSES or ac_lower in _EQUITY_CLASSES:
        return "equity"
    if ac in _FIXED_INCOME_CLASSES or ac_lower in _FIXED_INCOME_CLASSES:
        return "fixed_income"
    if ac in _CASH_CLASSES or ac_lower in _CASH_CLASSES:
        return "cash"
    return "other"


def classify_fund_style(
    holdings: list[dict[str, Any]],
    config: StyleConfig | None = None,
) -> StyleVector:
    """Classify fund style from N-PORT holdings.

    Each holding dict: {sector: str|None, asset_class: str, pct_of_nav: float|None,
                        market_value: int|None}
    Inputs come from sec_nport_holdings.
    Never raises — returns style_label='unknown', confidence=0.0 on insufficient data.
    """
    if config is None:
        config = StyleConfig()

    if not holdings:
        return StyleVector(
            style_label="unknown", growth_tilt=0.0,
            sector_weights={}, equity_pct=None,
            fixed_income_pct=None, cash_pct=None, confidence=0.0,
        )

    # Calculate weights — prefer pct_of_nav, fall back to market_value proportion
    total_value = 0.0
    for h in holdings:
        mv = h.get("market_value") or 0
        total_value += max(mv, 0)

    equity_weight = 0.0
    fi_weight = 0.0
    cash_weight = 0.0
    sector_totals: dict[str, float] = {}
    holdings_with_sector = 0

    for h in holdings:
        pct = h.get("pct_of_nav")
        if pct is not None:
            weight = pct / 100.0 if abs(pct) > 1.5 else pct
        elif total_value > 0:
            mv = h.get("market_value") or 0
            weight = mv / total_value
        else:
            weight = 1.0 / len(holdings)

        asset_type = _classify_asset(h.get("asset_class"))
        if asset_type == "equity":
            equity_weight += weight
        elif asset_type == "fixed_income":
            fi_weight += weight
        elif asset_type == "cash":
            cash_weight += weight

        sector = h.get("sector")
        if sector:
            holdings_with_sector += 1
            sector_totals[sector] = sector_totals.get(sector, 0.0) + weight

    # Normalize sector weights
    sector_sum = sum(sector_totals.values()) or 1.0
    sector_weights = {s: round(w / sector_sum, 4) for s, w in sector_totals.items()}

    # Confidence: proportion of holdings with sector data
    confidence = holdings_with_sector / len(holdings) if holdings else 0.0

    # Determine primary asset class
    total_weight = equity_weight + fi_weight + cash_weight or 1.0
    equity_pct = round(equity_weight / total_weight, 4) if total_weight > 0 else None
    fi_pct = round(fi_weight / total_weight, 4) if total_weight > 0 else None
    cash_pct_val = round(cash_weight / total_weight, 4) if total_weight > 0 else None

    # Classify style
    if equity_pct is not None and equity_pct >= config.equity_threshold:
        # Equity fund — derive growth/value tilt from sector exposure
        growth_sum = sum(sector_weights.get(s, 0.0) for s in GROWTH_SECTORS)
        value_sum = sum(sector_weights.get(s, 0.0) for s in VALUE_SECTORS)
        tilt_denom = growth_sum + value_sum
        growth_tilt = growth_sum / tilt_denom if tilt_denom > 0 else 0.5

        # Size classification: default to large (no per-holding market cap data)
        size = "large"

        if growth_tilt >= config.growth_tilt_threshold:
            style = "growth"
        elif growth_tilt <= (1.0 - config.growth_tilt_threshold):
            style = "value"
        else:
            style = "blend"

        style_label: StyleLabel = f"{size}_{style}"  # type: ignore[assignment]

    elif fi_pct is not None and fi_pct >= config.fixed_income_threshold:
        style_label = "fixed_income"
        growth_tilt = 0.0
    elif len(holdings) < config.min_holdings_for_confidence:
        style_label = "unknown"
        growth_tilt = 0.0
    else:
        style_label = "mixed"
        growth_sum = sum(sector_weights.get(s, 0.0) for s in GROWTH_SECTORS)
        value_sum = sum(sector_weights.get(s, 0.0) for s in VALUE_SECTORS)
        tilt_denom = growth_sum + value_sum
        growth_tilt = growth_sum / tilt_denom if tilt_denom > 0 else 0.5

    return StyleVector(
        style_label=style_label,
        growth_tilt=round(growth_tilt, 4),
        sector_weights=sector_weights,
        equity_pct=equity_pct,
        fixed_income_pct=fi_pct,
        cash_pct=cash_pct_val,
        confidence=round(confidence, 4),
    )
