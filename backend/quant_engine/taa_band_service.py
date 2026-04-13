"""Tactical Asset Allocation Band Service — regime-responsive optimizer constraints.

Transforms regime classifications into effective allocation bands that the
CLARABEL optimizer uses as block-level min/max constraints. Three layers:

1. IPS bounds (StrategicAllocation min/max) — HARD, never violated
2. Regime bands (ConfigService taa_bands) — SOFT, clamped by IPS
3. Optimizer (CLARABEL cascade) — operates within effective bands

Pure-sync functions — no I/O. All data passed as parameters.
Config resolved by callers via ConfigService.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Re-use the optimizer's BlockConstraint to avoid duplicate types.
# Import is deferred to avoid circular deps at module scope — callers
# import both quant_engine modules anyway.
from quant_engine.optimizer_service import BlockConstraint

# ── Default config (matches vertical_config_defaults seed) ─────────────

DEFAULT_TAA_BANDS: dict[str, Any] = {
    "regime_bands": {
        "RISK_ON": {
            "equity":       {"center": 0.52, "half_width": 0.08},
            "fixed_income": {"center": 0.30, "half_width": 0.06},
            "alternatives": {"center": 0.12, "half_width": 0.04},
            "cash":         {"center": 0.06, "half_width": 0.03},
        },
        "RISK_OFF": {
            "equity":       {"center": 0.38, "half_width": 0.08},
            "fixed_income": {"center": 0.36, "half_width": 0.06},
            "alternatives": {"center": 0.13, "half_width": 0.04},
            "cash":         {"center": 0.13, "half_width": 0.05},
        },
        "INFLATION": {
            "equity":       {"center": 0.42, "half_width": 0.08},
            "fixed_income": {"center": 0.25, "half_width": 0.06},
            "alternatives": {"center": 0.22, "half_width": 0.06},
            "cash":         {"center": 0.11, "half_width": 0.04},
        },
        "CRISIS": {
            "equity":       {"center": 0.25, "half_width": 0.06},
            "fixed_income": {"center": 0.35, "half_width": 0.06},
            "alternatives": {"center": 0.15, "half_width": 0.05},
            "cash":         {"center": 0.25, "half_width": 0.08},
        },
    },
    "transition": {
        "ema_halflife_days": 5,
        "min_confidence_to_act": 0.60,
        "max_daily_shift_pct": 0.03,
    },
    "ips_override_priority": True,
}


@dataclass(frozen=True, slots=True)
class EffectiveBand:
    """Result of band clamping for a single block."""

    block_id: str
    ips_min: float
    ips_max: float
    regime_center: float
    effective_min: float
    effective_max: float


# ---------------------------------------------------------------------------
#  Core band clamping
# ---------------------------------------------------------------------------


def compute_effective_band(
    ips_min: float,
    ips_max: float,
    regime_center: float,
    regime_half_width: float,
) -> tuple[float, float]:
    """Compute effective optimizer band = intersection of IPS and regime band.

    The IPS invariant is ALWAYS maintained:
        ips_min <= effective_min <= effective_max <= ips_max

    When the regime band falls entirely outside IPS bounds, clamps to
    the nearest IPS edge while preserving the band width as much as
    possible.
    """
    regime_min = regime_center - regime_half_width
    regime_max = regime_center + regime_half_width

    effective_min = max(ips_min, regime_min)
    effective_max = min(ips_max, regime_max)

    # If regime band falls entirely outside IPS, clamp to nearest IPS edge
    if effective_min > effective_max:
        if regime_center < ips_min:
            effective_min = ips_min
            effective_max = min(ips_min + 2 * regime_half_width, ips_max)
        elif regime_center > ips_max:
            effective_max = ips_max
            effective_min = max(ips_max - 2 * regime_half_width, ips_min)
        else:
            # Shouldn't happen, but defensive: use IPS bounds directly
            effective_min = ips_min
            effective_max = ips_max

    return effective_min, effective_max


# ---------------------------------------------------------------------------
#  EMA smoothing on regime centers
# ---------------------------------------------------------------------------


def smooth_regime_centers(
    current_centers: dict[str, float],
    previous_smoothed: dict[str, float] | None,
    halflife_days: int = 5,
    max_daily_shift: float = 0.03,
) -> dict[str, float]:
    """Apply EMA smoothing to regime-implied asset-class centers.

    Prevents whipsaw: regime flips are absorbed gradually over ~22 business
    days (5-day halflife → 95% convergence in 22 days).

    The max_daily_shift cap provides a hard limit on single-day movement
    (default 3pp/day) regardless of EMA output.

    When previous_smoothed is None (first run), returns current_centers
    as the initial anchor.
    """
    if previous_smoothed is None:
        return dict(current_centers)

    alpha = 1 - math.exp(-math.log(2) / halflife_days)
    smoothed: dict[str, float] = {}

    for asset_class, target in current_centers.items():
        prev = previous_smoothed.get(asset_class, target)
        # EMA step
        raw_smoothed = alpha * target + (1 - alpha) * prev
        # Apply max daily shift cap
        delta = raw_smoothed - prev
        if abs(delta) > max_daily_shift:
            clamped = prev + max_daily_shift * (1 if delta > 0 else -1)
            smoothed[asset_class] = round(clamped, 6)
        else:
            smoothed[asset_class] = round(raw_smoothed, 6)

    return smoothed


# ---------------------------------------------------------------------------
#  Per-block disaggregation
# ---------------------------------------------------------------------------


def _disaggregate_centers_to_blocks(
    asset_class_centers: dict[str, float],
    blocks: list[dict[str, Any]],
    half_widths: dict[str, float],
) -> dict[str, tuple[float, float]]:
    """Disaggregate asset-class centers to per-block centers + half widths.

    Preserves IC committee's geographic/style preferences within each asset
    class by maintaining the ratio of each block's target to its asset class
    total.

    Args:
        asset_class_centers: Smoothed centers per asset class
            {"equity": 0.42, "fixed_income": 0.33, ...}
        blocks: List of dicts with block_id, asset_class, target_weight, min_weight, max_weight
        half_widths: Per-asset-class half widths from config

    Returns:
        Dict of block_id → (center, half_width) for each block.
    """
    # Group blocks by asset class and compute total target per class
    class_totals: dict[str, float] = {}
    for b in blocks:
        ac = b["asset_class"]
        class_totals[ac] = class_totals.get(ac, 0) + b["target_weight"]

    result: dict[str, tuple[float, float]] = {}
    for b in blocks:
        ac = b["asset_class"]
        class_total = class_totals.get(ac, 0)
        class_center = asset_class_centers.get(ac)

        if class_center is None or class_total <= 0:
            # No regime data for this asset class — skip, will use IPS bounds
            continue

        # Proportional disaggregation: preserve block's share of asset class
        block_ratio = b["target_weight"] / class_total
        block_center = class_center * block_ratio

        # Half width scaled proportionally too
        ac_half = half_widths.get(ac, 0.05)
        block_half = ac_half * block_ratio

        result[b["block_id"]] = (block_center, block_half)

    return result


# ---------------------------------------------------------------------------
#  Main orchestrator
# ---------------------------------------------------------------------------


def resolve_effective_bands(
    allocations: list[dict[str, Any]],
    block_asset_classes: dict[str, str],
    taa_regime_state: dict[str, Any] | None,
    taa_config: dict[str, Any] | None = None,
    taa_enabled: bool = True,
) -> tuple[list[BlockConstraint], dict[str, Any]]:
    """Resolve effective optimizer bands from regime state + IPS bounds.

    This is the main entry point called by _run_construction_async.

    Args:
        allocations: List of dicts with block_id, target_weight, min_weight, max_weight
        block_asset_classes: Mapping of block_id → asset_class (from AllocationBlock table)
        taa_regime_state: Latest taa_regime_state row as dict with
            smoothed_centers, effective_bands. None if first run or no regime data.
        taa_config: TAA config from ConfigService. Falls back to DEFAULT_TAA_BANDS.
        taa_enabled: Toggle from PortfolioCalibration.expert_overrides.

    Returns:
        Tuple of (list[BlockConstraint], provenance_dict).
        provenance_dict contains TAA metadata for calibration_snapshot.
    """
    config = taa_config or DEFAULT_TAA_BANDS

    # ── Fallback: static IPS bounds (identical to current behavior) ──
    if not taa_enabled or taa_regime_state is None:
        constraints = [
            BlockConstraint(
                block_id=a["block_id"],
                min_weight=a["min_weight"],
                max_weight=a["max_weight"],
            )
            for a in allocations
        ]
        return constraints, {
            "enabled": False,
            "reason": "disabled" if not taa_enabled else "no_regime_state",
        }

    # ── Read smoothed centers from regime state ──
    smoothed_centers: dict[str, float] = taa_regime_state.get("smoothed_centers", {})
    raw_regime: str = taa_regime_state.get("raw_regime", "RISK_ON")
    stress_score: float | None = taa_regime_state.get("stress_score")

    # Get half-widths from config for the current regime
    regime_bands = config.get("regime_bands", {})
    regime_config = regime_bands.get(raw_regime, regime_bands.get("RISK_ON", {}))
    half_widths: dict[str, float] = {
        ac: band_cfg.get("half_width", 0.05)
        for ac, band_cfg in regime_config.items()
    }

    # ── Enrich allocations with asset_class ──
    enriched_blocks = []
    for a in allocations:
        ac = block_asset_classes.get(a["block_id"], "other")
        enriched_blocks.append({
            "block_id": a["block_id"],
            "asset_class": ac,
            "target_weight": a["target_weight"],
            "min_weight": a["min_weight"],
            "max_weight": a["max_weight"],
        })

    # ── Disaggregate to per-block centers ──
    block_bands = _disaggregate_centers_to_blocks(
        smoothed_centers, enriched_blocks, half_widths,
    )

    # ── Clamp by IPS and build BlockConstraints ──
    constraints: list[BlockConstraint] = []
    effective_bands_log: dict[str, dict[str, float]] = {}
    ips_clamps: list[str] = []

    for a in allocations:
        bid = a["block_id"]
        ips_min = a["min_weight"]
        ips_max = a["max_weight"]

        band_data = block_bands.get(bid)
        if band_data is None:
            # No regime data for this block — use IPS bounds
            constraints.append(BlockConstraint(
                block_id=bid,
                min_weight=ips_min,
                max_weight=ips_max,
            ))
            continue

        block_center, block_half = band_data
        eff_min, eff_max = compute_effective_band(
            ips_min, ips_max, block_center, block_half,
        )

        # Track IPS clamps for audit
        raw_regime_min = block_center - block_half
        raw_regime_max = block_center + block_half
        if eff_min > raw_regime_min + 1e-6:
            ips_clamps.append(f"{bid}_min_raised")
        if eff_max < raw_regime_max - 1e-6:
            ips_clamps.append(f"{bid}_max_lowered")

        constraints.append(BlockConstraint(
            block_id=bid,
            min_weight=round(eff_min, 6),
            max_weight=round(eff_max, 6),
        ))
        effective_bands_log[bid] = {
            "min": round(eff_min, 6),
            "max": round(eff_max, 6),
            "center": round(block_center, 6),
        }

    # ── Compute transition velocity for audit ──
    prev_centers = taa_regime_state.get("_previous_smoothed_centers")
    velocity: dict[str, float] = {}
    if prev_centers and isinstance(prev_centers, dict):
        for ac, current in smoothed_centers.items():
            prev = prev_centers.get(ac)
            if prev is not None:
                velocity[ac] = round(current - prev, 6)

    provenance = {
        "enabled": True,
        "raw_regime": raw_regime,
        "stress_score": stress_score,
        "smoothed_centers": smoothed_centers,
        "effective_bands": effective_bands_log,
        "ips_clamps_applied": ips_clamps,
        "ic_overrides_active": [],
        "transition_velocity": velocity,
    }

    return constraints, provenance


def extract_stress_score(reasons: dict[str, str]) -> float | None:
    """Extract numeric stress score from classify_regime_multi_signal reasons.

    The composite_stress field has format "XX.X/100 (N signals)".
    Returns the float value or None if not parseable.
    """
    composite = reasons.get("composite_stress", "")
    if "/" in composite:
        try:
            return float(composite.split("/")[0])
        except (ValueError, IndexError):
            return None
    return None


def get_regime_centers_for_regime(
    regime: str,
    config: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Get raw (unsmoothed) asset-class centers for a given regime.

    Used by risk_calc worker to determine the target centers before EMA smoothing.
    """
    cfg = config or DEFAULT_TAA_BANDS
    regime_bands = cfg.get("regime_bands", {})
    band_config = regime_bands.get(regime, regime_bands.get("RISK_ON", {}))
    return {
        ac: float(band_cfg["center"])
        for ac, band_cfg in band_config.items()
        if isinstance(band_cfg, dict) and "center" in band_cfg
    }
