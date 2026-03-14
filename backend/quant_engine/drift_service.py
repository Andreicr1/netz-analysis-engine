"""Portfolio drift monitoring service.

Compares current portfolio weights against combined target
(strategic + tactical) and flags drift beyond configured bands.
Drift bands from calibration/config/limits.yaml.

Drift = actual_weight - (strategic_target + tactical_overweight)
Intentional tactical bets are NOT flagged as drift.
"""

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np
import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_calibration_path
from app.domains.wealth.models.allocation import StrategicAllocation, TacticalPosition
from app.domains.wealth.models.portfolio import PortfolioSnapshot

logger = structlog.get_logger()


@dataclass
class BlockDrift:
    block_id: str
    current_weight: float
    target_weight: float
    absolute_drift: float
    relative_drift: float
    status: str  # "ok" | "maintenance" | "urgent"


@dataclass
class DriftReport:
    profile: str
    as_of_date: date
    blocks: list[BlockDrift]
    max_drift_pct: float
    overall_status: str
    rebalance_recommended: bool
    estimated_turnover: float
    maintenance_trigger: float
    urgent_trigger: float


@lru_cache(maxsize=1)
def get_drift_thresholds() -> tuple[float, float]:
    """Load drift band thresholds from limits.yaml.

    Returns (maintenance_trigger, urgent_trigger) as decimals.
    """
    try:
        config_path = get_calibration_path() / "limits.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)
        bands = data["drift_bands"]
        return (
            float(bands["maintenance_trigger"]),
            float(bands["urgent_trigger"]),
        )
    except FileNotFoundError:
        logger.warning("limits.yaml not found, using default drift bands")
        return 0.05, 0.10
    except (KeyError, TypeError, ValueError) as e:
        logger.error("limits.yaml malformed for drift_bands", error=str(e))
        return 0.05, 0.10


def compute_block_drifts(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    maintenance_trigger: float = 0.05,
    urgent_trigger: float = 0.10,
) -> list[BlockDrift]:
    """Compute per-block drift between current and target weights.

    Pure function — no DB access.
    """
    drifts = []
    all_blocks = set(current_weights.keys()) | set(target_weights.keys())

    for block_id in sorted(all_blocks):
        current = current_weights.get(block_id, 0.0)
        target = target_weights.get(block_id, 0.0)
        abs_drift = current - target
        rel_drift = abs_drift / target if target > 0 else 0.0

        if abs(abs_drift) >= urgent_trigger:
            drift_status = "urgent"
        elif abs(abs_drift) >= maintenance_trigger:
            drift_status = "maintenance"
        else:
            drift_status = "ok"

        drifts.append(BlockDrift(
            block_id=block_id,
            current_weight=round(current, 6),
            target_weight=round(target, 6),
            absolute_drift=round(abs_drift, 6),
            relative_drift=round(rel_drift, 4),
            status=drift_status,
        ))

    return drifts


async def compute_drift(
    db: AsyncSession,
    profile: str,
    as_of_date: date | None = None,
    min_trade_threshold: float = 0.005,
) -> DriftReport:
    """Compute drift for all blocks in a profile.

    Drift = actual_weight - (strategic_target + tactical_overweight)
    Intentional tactical bets are NOT flagged as drift.

    Only recommends rebalance when estimated turnover >= 1%.
    """
    if as_of_date is None:
        as_of_date = date.today()

    maintenance_trigger, urgent_trigger = get_drift_thresholds()

    # 1. Get latest snapshot weights
    snap_stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.profile == profile)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    snap_result = await db.execute(snap_stmt)
    snapshot = snap_result.scalar_one_or_none()

    if snapshot is None or not snapshot.weights:
        return DriftReport(
            profile=profile,
            as_of_date=as_of_date,
            blocks=[],
            max_drift_pct=0.0,
            overall_status="ok",
            rebalance_recommended=False,
            estimated_turnover=0.0,
            maintenance_trigger=maintenance_trigger,
            urgent_trigger=urgent_trigger,
        )

    current_weights: dict[str, float] = {
        k: float(v) for k, v in snapshot.weights.items()
    }

    # 2. Get current strategic allocation
    alloc_stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= as_of_date,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= as_of_date)
        )
    )
    alloc_result = await db.execute(alloc_stmt)
    strategic = {a.block_id: float(a.target_weight) for a in alloc_result.scalars().all()}

    # 3. Get current tactical positions (intentional overweights)
    tact_stmt = (
        select(TacticalPosition)
        .where(
            TacticalPosition.profile == profile,
            TacticalPosition.valid_from <= as_of_date,
        )
        .where(
            (TacticalPosition.valid_to.is_(None))
            | (TacticalPosition.valid_to >= as_of_date)
        )
    )
    tact_result = await db.execute(tact_stmt)
    tactical = {t.block_id: float(t.overweight) for t in tact_result.scalars().all()}

    # 4. Combined target = strategic + tactical
    target_weights: dict[str, float] = {}
    for block_id in set(strategic.keys()) | set(tactical.keys()):
        target_weights[block_id] = strategic.get(block_id, 0.0) + tactical.get(block_id, 0.0)

    # 5. Compute drift
    drifts = compute_block_drifts(
        current_weights, target_weights,
        maintenance_trigger, urgent_trigger,
    )

    max_abs = max((abs(d.absolute_drift) for d in drifts), default=0.0)

    # Overall status = worst block
    if any(d.status == "urgent" for d in drifts):
        overall = "urgent"
    elif any(d.status == "maintenance" for d in drifts):
        overall = "maintenance"
    else:
        overall = "ok"

    # Estimated turnover (only meaningful trades)
    meaningful_trades = [
        abs(d.absolute_drift) for d in drifts
        if abs(d.absolute_drift) >= min_trade_threshold
    ]
    turnover = sum(meaningful_trades) / 2

    # Only recommend rebalance if turnover justifies trading costs
    rebalance_recommended = overall != "ok" and turnover >= 0.01

    return DriftReport(
        profile=profile,
        as_of_date=as_of_date,
        blocks=[d for d in drifts if d.status != "ok"],
        max_drift_pct=round(max_abs, 6),
        overall_status=overall,
        rebalance_recommended=rebalance_recommended,
        estimated_turnover=round(turnover, 6),
        maintenance_trigger=maintenance_trigger,
        urgent_trigger=urgent_trigger,
    )


# ─────────────────────────────────────────────────────────────────────────────
# DTW Drift Detection
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_dtw_thresholds() -> tuple[float, float]:
    """Load DTW divergence thresholds from limits.yaml.

    Returns (warning_threshold, critical_threshold).
    Thresholds are for derivative DTW (ddtw), length-normalized (raw / window).
    """
    try:
        config_path = get_calibration_path() / "limits.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)
        dtw_cfg = data["drift"]["dtw"]
        return (
            float(dtw_cfg["dtw_divergence_warning"]),
            float(dtw_cfg["dtw_divergence_critical"]),
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        # Calibrated defaults for derivative DTW, length-normalized
        return 0.40, 0.90


def compute_dtw_drift(
    fund_returns: list[float],
    benchmark_returns: list[float],
    window: int = 63,
) -> float:
    """Compute derivative DTW distance between fund and benchmark return series.

    Uses ddtw_distance (derivative DTW) — naturally scale-invariant.
    Result is length-normalized (raw / window) for cross-fund comparability.
    Returns 0.0 if aeon is not installed (neutral fallback).
    """
    try:
        from aeon.distances import ddtw_distance
    except ImportError:
        logger.warning("aeon not installed; DTW drift score will be 0.0 (neutral). "
                       "Install with: pip install netz-wealth-os[timeseries]")
        return 0.0

    f = np.array(fund_returns[-window:], dtype=float)
    b = np.array(benchmark_returns[-window:], dtype=float)

    if len(f) < 10 or len(b) < 10:
        return 0.0

    try:
        raw = ddtw_distance(f, b, window=0.1)  # 10% warping constraint
        return float(raw / max(len(f), 1))  # length-normalize
    except Exception as e:
        logger.warning("dtw_drift_computation_failed", error=str(e))
        return 0.0


def compute_dtw_drift_batch(
    fund_returns_matrix: "np.ndarray",
    benchmark_returns: "np.ndarray",
    window: int = 63,
) -> list[float]:
    """Vectorized DTW distance for all funds vs benchmark.

    Single pairwise_distance call vs sequential loop: ~0.2s vs ~2s for 200 funds.
    IMPORTANT: Share the DB query with compute_inputs_from_nav — do NOT
    issue a separate query for DTW drift.

    Returns list of length-normalized ddtw scores (one per fund).
    Returns list of 0.0 on missing aeon (neutral fallback).
    """
    n_funds = fund_returns_matrix.shape[0]

    try:
        from aeon.distances import pairwise_distance
    except ImportError:
        logger.warning("aeon not installed; DTW drift scores will be 0.0 (neutral). "
                       "Install with: pip install netz-wealth-os[timeseries]")
        return [0.0] * n_funds

    try:
        # Use last `window` days
        fund_slice = fund_returns_matrix[:, -window:]
        bench_slice = benchmark_returns[-window:].reshape(1, -1)

        # Stack benchmark as last row for pairwise computation
        all_series = np.vstack([fund_slice, bench_slice])

        # pairwise_distance returns (n_funds+1) × (n_funds+1) distance matrix
        dist_matrix = pairwise_distance(all_series, metric="ddtw")

        # Last row = distances to benchmark
        benchmark_distances = dist_matrix[-1, :-1]

        # Length-normalize
        actual_window = fund_slice.shape[1]
        return [float(d / max(actual_window, 1)) for d in benchmark_distances]

    except Exception as e:
        logger.warning("dtw_drift_batch_failed", error=str(e))
        return [0.0] * n_funds
