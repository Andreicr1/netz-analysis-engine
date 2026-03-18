"""Portfolio drift monitoring service.

Compares current portfolio weights against combined target
(strategic + tactical) and flags drift beyond configured bands.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "calibration").

Drift = actual_weight - (strategic_target + tactical_overweight)
Intentional tactical bets are NOT flagged as drift.

Note: imports StrategicAllocation, TacticalPosition, PortfolioSnapshot from app.domains.wealth — wealth-vertical-specific dependency.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


class DtwDriftStatus(str, Enum):
    """Status of a DTW drift computation."""

    ok = "ok"
    degraded = "degraded"
    failed = "failed"


@dataclass(frozen=True, slots=True)
class DtwDriftResult:
    """Typed result for DTW drift computation.

    Distinguishes genuine zero drift (status=ok, score=0.0) from
    computation failures (status=degraded/failed, score=None).
    """

    score: float | None
    status: DtwDriftStatus
    reason: str | None = None

    @property
    def is_usable(self) -> bool:
        """Whether the score can be used for downstream decisions."""
        return self.status == DtwDriftStatus.ok

    def score_or_default(self, default: float = 0.0) -> float:
        """Return score if usable, otherwise the caller-chosen default.

        Consumers that need a float (e.g. DB upsert) call this explicitly,
        making the fallback intentional rather than silent.
        """
        if self.score is not None and self.is_usable:
            return self.score
        return default


def resolve_drift_thresholds(config: dict | None = None) -> tuple[float, float]:
    """Extract drift band thresholds from calibration config dict.

    Returns (maintenance_trigger, urgent_trigger) as decimals.
    Falls back to hardcoded defaults if config is None or malformed.
    """
    if config is None:
        return 0.05, 0.10

    try:
        bands = config.get("drift_bands", {})
        if bands:
            return (
                float(bands["maintenance_trigger"]),
                float(bands["urgent_trigger"]),
            )
        return 0.05, 0.10
    except (KeyError, TypeError, ValueError) as e:
        logger.error("Malformed drift config, using defaults", error=str(e))
        return 0.05, 0.10


def resolve_dtw_thresholds(config: dict | None = None) -> tuple[float, float]:
    """Extract DTW divergence thresholds from calibration config dict.

    Returns (warning_threshold, critical_threshold).
    Falls back to hardcoded defaults if config is None or malformed.
    """
    if config is None:
        return 0.40, 0.90

    try:
        dtw_cfg = config.get("drift", {}).get("dtw", {})
        if dtw_cfg:
            return (
                float(dtw_cfg["dtw_divergence_warning"]),
                float(dtw_cfg["dtw_divergence_critical"]),
            )
        return 0.40, 0.90
    except (KeyError, TypeError, ValueError):
        return 0.40, 0.90


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
    config: dict | None = None,
) -> DriftReport:
    """Compute drift for all blocks in a profile.

    Args:
        config: Raw calibration config dict from ConfigService.
    """
    if as_of_date is None:
        as_of_date = date.today()

    maintenance_trigger, urgent_trigger = resolve_drift_thresholds(config)

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

    # 3. Get current tactical positions
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

    if any(d.status == "urgent" for d in drifts):
        overall = "urgent"
    elif any(d.status == "maintenance" for d in drifts):
        overall = "maintenance"
    else:
        overall = "ok"

    meaningful_trades = [
        abs(d.absolute_drift) for d in drifts
        if abs(d.absolute_drift) >= min_trade_threshold
    ]
    turnover = sum(meaningful_trades) / 2

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


def compute_dtw_drift(
    fund_returns: list[float],
    benchmark_returns: list[float],
    window: int = 63,
) -> DtwDriftResult:
    """Compute derivative DTW distance between fund and benchmark return series.

    Uses ddtw_distance (derivative DTW) — naturally scale-invariant.
    Result is length-normalized (raw / window) for cross-fund comparability.

    Returns a typed DtwDriftResult instead of a bare float, so that
    computation failures are never silently encoded as 0.0.
    """
    try:
        from aeon.distances import ddtw_distance
    except ImportError:
        logger.warning("aeon not installed; DTW drift returns degraded result. "
                       "Install with: pip install netz-wealth-os[timeseries]")
        return DtwDriftResult(
            score=None,
            status=DtwDriftStatus.degraded,
            reason="aeon library not installed",
        )

    f = np.array(fund_returns[-window:], dtype=float)
    b = np.array(benchmark_returns[-window:], dtype=float)

    if len(f) < 10 or len(b) < 10:
        return DtwDriftResult(
            score=None,
            status=DtwDriftStatus.degraded,
            reason=f"insufficient data: fund={len(f)}, benchmark={len(b)} (min 10)",
        )

    try:
        raw = ddtw_distance(f, b, window=0.1)
        return DtwDriftResult(
            score=float(raw / max(len(f), 1)),
            status=DtwDriftStatus.ok,
        )
    except Exception as e:
        logger.warning("dtw_drift_computation_failed", error=str(e))
        return DtwDriftResult(
            score=None,
            status=DtwDriftStatus.failed,
            reason=str(e),
        )


def compute_dtw_drift_batch(
    fund_returns_matrix: "np.ndarray",
    benchmark_returns: "np.ndarray",
    window: int = 63,
) -> list[DtwDriftResult]:
    """Vectorized DTW distance for all funds vs benchmark.

    Returns a list of typed DtwDriftResult instead of bare floats,
    so that computation failures are never silently encoded as 0.0.
    """
    n_funds = fund_returns_matrix.shape[0]

    try:
        from aeon.distances import pairwise_distance
    except ImportError:
        logger.warning("aeon not installed; DTW drift returns degraded results. "
                       "Install with: pip install netz-wealth-os[timeseries]")
        return [
            DtwDriftResult(
                score=None,
                status=DtwDriftStatus.degraded,
                reason="aeon library not installed",
            )
            for _ in range(n_funds)
        ]

    try:
        fund_slice = fund_returns_matrix[:, -window:]
        bench_slice = benchmark_returns[-window:].reshape(1, -1)

        all_series = np.vstack([fund_slice, bench_slice])
        dist_matrix = pairwise_distance(all_series, metric="ddtw")
        benchmark_distances = dist_matrix[-1, :-1]

        actual_window = fund_slice.shape[1]
        return [
            DtwDriftResult(
                score=float(d / max(actual_window, 1)),
                status=DtwDriftStatus.ok,
            )
            for d in benchmark_distances
        ]

    except Exception as e:
        logger.warning("dtw_drift_batch_failed", error=str(e))
        return [
            DtwDriftResult(
                score=None,
                status=DtwDriftStatus.failed,
                reason=str(e),
            )
            for _ in range(n_funds)
        ]
