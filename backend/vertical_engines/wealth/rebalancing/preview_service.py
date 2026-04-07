"""Rebalance Preview Service — stateless delta engine.

Computes suggested trades by comparing a ModelPortfolio's target weights
(fund_selection_schema) against externally-provided current holdings.
No DB writes — pure calculation.  Cash is a first-class asset with
guaranteed neutrality (sum of all trade_value == 0).

All values in USD.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

logger = structlog.get_logger()

# Universal cash instrument ID — same constant on frontend
CASH_INSTRUMENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
_CASH_ID_STR = str(CASH_INSTRUMENT_ID)

# Threshold below which a trade is considered HOLD (avoids noise)
_HOLD_THRESHOLD = 1e-6  # 0.0001% of AUM

# Tolerance for cash neutrality assertion
_NEUTRALITY_TOLERANCE = 1e-2  # $0.01


def compute_rebalance_preview(
    *,
    portfolio_id: uuid.UUID,
    portfolio_name: str,
    profile: str,
    fund_selection_schema: dict[str, Any],
    current_holdings: list[dict[str, Any]],
    cash_available: float,
    total_aum_override: float | None = None,
) -> dict[str, Any]:
    """Compute rebalance preview: target vs current → trades.

    Cash is normalized into holdings as a first-class asset.  After
    computing fund deltas, ``_apply_cash_sweep`` adjusts the cash
    trade so that ``sum(trade_value) == 0`` (cash-neutral).
    """
    # ── 1. Normalize cash into holdings ──────────────────────────────
    # Inject cash as a holding with price = 1.0 (USD per USD).
    normalized_holdings = list(current_holdings)
    normalized_holdings.append({
        "instrument_id": _CASH_ID_STR,
        "quantity": cash_available,
        "current_price": 1.0,
    })

    # ── 2. Build current positions map ───────────────────────────────
    holdings_map: dict[str, dict[str, Any]] = {}
    holdings_value = 0.0

    for h in normalized_holdings:
        iid = str(h["instrument_id"])
        qty = float(h["quantity"])
        price = float(h["current_price"])
        value = qty * price
        holdings_map[iid] = {
            "quantity": qty,
            "current_price": price,
            "value": value,
        }
        holdings_value += value

    total_aum = total_aum_override if total_aum_override is not None else holdings_value

    if total_aum <= 0:
        return _empty_response(portfolio_id, portfolio_name, profile, total_aum, cash_available)

    # ── 3. Build target weights map from fund_selection_schema ────────
    target_funds = fund_selection_schema.get("funds", [])
    target_map: dict[str, dict[str, Any]] = {}
    target_fund_weight_sum = 0.0
    for f in target_funds:
        iid = str(f["instrument_id"])
        w = float(f.get("weight", 0.0))
        target_map[iid] = {
            "fund_name": f.get("fund_name", ""),
            "block_id": f.get("block_id", "unknown"),
            "weight": w,
        }
        target_fund_weight_sum += w

    # Target cash weight = residual (1.0 - sum of fund weights).
    # Fully-invested models have ~0 target cash; under-invested keep residual.
    target_cash_weight = max(1.0 - target_fund_weight_sum, 0.0)
    target_map[_CASH_ID_STR] = {
        "fund_name": "Cash Balance",
        "block_id": "cash",
        "weight": target_cash_weight,
    }

    # ── 4. Compute trades (all instruments including cash) ───────────
    all_instrument_ids = set(holdings_map.keys()) | set(target_map.keys())
    trades: list[dict[str, Any]] = []
    total_abs_trade_value = 0.0

    for iid in sorted(all_instrument_ids):
        holding = holdings_map.get(iid)
        target = target_map.get(iid)

        current_value = holding["value"] if holding else 0.0
        current_weight = current_value / total_aum

        target_weight = target["weight"] if target else 0.0

        fund_name = target["fund_name"] if target else f"Unknown ({iid[:8]})"
        block_id = target["block_id"] if target else "unknown"

        delta_weight = target_weight - current_weight
        target_value = target_weight * total_aum
        trade_value = target_value - current_value

        if abs(delta_weight) < _HOLD_THRESHOLD:
            action = "HOLD"
            trade_value = 0.0
        elif trade_value > 0:
            action = "BUY"
        else:
            action = "SELL"

        # Cash price is always 1.0; fund price from holding
        price = holding["current_price"] if holding else (1.0 if iid == _CASH_ID_STR else 0.0)
        if price > 0 and action != "HOLD":
            estimated_quantity = abs(trade_value) / price
        else:
            estimated_quantity = 0.0

        trades.append({
            "instrument_id": iid,
            "fund_name": fund_name,
            "block_id": block_id,
            "action": action,
            "current_weight": round(current_weight, 6),
            "target_weight": round(target_weight, 6),
            "delta_weight": round(delta_weight, 6),
            "current_value": round(current_value, 2),
            "target_value": round(target_value, 2),
            "trade_value": round(trade_value, 2),
            "estimated_quantity": round(estimated_quantity, 4),
        })

        # Exclude cash from turnover calculation (cash movement is not turnover)
        if iid != _CASH_ID_STR:
            total_abs_trade_value += abs(trade_value)

    # ── 5. Cash sweep — enforce neutrality ───────────────────────────
    _apply_cash_sweep(trades)

    # Sort: sells first (largest negative delta), then buys, cash last
    trades.sort(key=lambda t: (
        3 if t["instrument_id"] == _CASH_ID_STR else (
            0 if t["action"] == "SELL" else 1 if t["action"] == "BUY" else 2
        ),
        -abs(t["delta_weight"]),
    ))

    # ── 6. Turnover (excludes cash) ──────────────────────────────────
    turnover = total_abs_trade_value / (2 * total_aum) if total_aum > 0 else 0.0

    # ── 7. Block-level weight comparison (exclude cash block) ────────
    block_current: dict[str, float] = {}
    block_target: dict[str, float] = {}

    for t in trades:
        bid = t["block_id"]
        if bid == "cash":
            continue  # Cash not part of allocation block comparison
        block_current[bid] = block_current.get(bid, 0.0) + t["current_weight"]
        block_target[bid] = block_target.get(bid, 0.0) + t["target_weight"]

    all_blocks = sorted(set(block_current.keys()) | set(block_target.keys()))
    weight_comparison = [
        {
            "block_id": bid,
            "current_weight": round(block_current.get(bid, 0.0), 6),
            "target_weight": round(block_target.get(bid, 0.0), 6),
            "delta_pp": round(
                (block_target.get(bid, 0.0) - block_current.get(bid, 0.0)) * 100,
                2,
            ),
        }
        for bid in all_blocks
    ]

    # Count trades excluding HOLD (cash sweep always counts if non-zero)
    total_trades = sum(1 for t in trades if t["action"] != "HOLD")

    logger.info(
        "rebalance_preview_computed",
        portfolio_id=str(portfolio_id),
        total_aum=total_aum,
        total_trades=total_trades,
        turnover=round(turnover, 4),
        cash_neutral=True,
    )

    return {
        "portfolio_id": str(portfolio_id),
        "portfolio_name": portfolio_name,
        "profile": profile,
        "total_aum": round(total_aum, 2),
        "cash_available": round(cash_available, 2),
        "total_trades": total_trades,
        "estimated_turnover_pct": round(turnover, 6),
        "trades": trades,
        "weight_comparison": weight_comparison,
    }


def _apply_cash_sweep(trades: list[dict[str, Any]]) -> None:
    """Adjust cash trade so that sum(trade_value) == 0 (cash-neutral).

    1. Sum trade_value of all non-cash trades.
    2. Set cash trade_value = -sum (exact inverse).
    3. Validate neutrality within tolerance.

    Raises
    ------
    ValueError
        If neutrality cannot be achieved (should never happen with
        correct arithmetic, acts as a safety net).
    """
    cash_trade: dict[str, Any] | None = None
    non_cash_sum = 0.0

    for t in trades:
        if t["instrument_id"] == _CASH_ID_STR:
            cash_trade = t
        else:
            non_cash_sum += t["trade_value"]

    if cash_trade is None:
        # No cash trade exists — nothing to sweep
        return

    # Set cash trade_value to exact inverse of fund trades
    cash_trade_value = -non_cash_sum
    cash_trade["trade_value"] = round(cash_trade_value, 2)
    cash_trade["estimated_quantity"] = round(abs(cash_trade_value), 2)  # price=1.0

    # Determine action
    if abs(cash_trade_value) < 0.01:
        cash_trade["action"] = "HOLD"
        cash_trade["trade_value"] = 0.0
        cash_trade["estimated_quantity"] = 0.0
    elif cash_trade_value > 0:
        cash_trade["action"] = "BUY"  # Net cash inflow (sells > buys)
    else:
        cash_trade["action"] = "SELL"  # Net cash outflow (buys > sells)

    # Recalculate cash weights from the swept value
    # target_value = current_value + trade_value
    cash_trade["target_value"] = round(cash_trade["current_value"] + cash_trade["trade_value"], 2)

    # Validate neutrality
    total_trade_sum = sum(t["trade_value"] for t in trades)
    if abs(total_trade_sum) > _NEUTRALITY_TOLERANCE:
        msg = (
            f"Cash sweep failed: sum(trade_value) = {total_trade_sum:.6f}, "
            f"expected 0.0 (tolerance={_NEUTRALITY_TOLERANCE})"
        )
        raise ValueError(msg)


def _empty_response(
    portfolio_id: uuid.UUID,
    portfolio_name: str,
    profile: str,
    total_aum: float,
    cash_available: float,
) -> dict[str, Any]:
    """Return empty response when AUM is zero or negative."""
    return {
        "portfolio_id": str(portfolio_id),
        "portfolio_name": portfolio_name,
        "profile": profile,
        "total_aum": total_aum,
        "cash_available": cash_available,
        "total_trades": 0,
        "estimated_turnover_pct": 0.0,
        "trades": [],
        "weight_comparison": [],
    }
