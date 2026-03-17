"""Peer Group Service — entry point for peer identification and ranking.

Computes peer groups dynamically (not persisted). Queries
InstrumentScreeningMetrics for metric values, uses peer_matcher for group
identification, and computes percentile rankings.

Session injection pattern: caller provides db session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog
from scipy.stats import percentileofscore
from sqlalchemy import select
from sqlalchemy.orm import Session

from vertical_engines.wealth.peer_group.models import (
    MetricRanking,
    PeerGroup,
    PeerGroupNotFound,
    PeerRanking,
)
from vertical_engines.wealth.peer_group.peer_matcher import match_peers

logger = structlog.get_logger()

# Metrics where lower values are better (invert percentile rank)
LOWER_IS_BETTER: frozenset[str] = frozenset({
    "max_drawdown_pct",
    "annual_volatility_pct",
    "pe_ratio_ttm",
    "debt_to_equity",
})

# Default metric weights by instrument type
_DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "fund": {
        "sharpe_ratio": 0.30,
        "max_drawdown_pct": 0.20,
        "annual_return_pct": 0.25,
        "annual_volatility_pct": 0.15,
        "pct_positive_months": 0.10,
    },
    "bond": {
        "spread_vs_benchmark_bps": 0.40,
        "liquidity_score": 0.30,
        "duration_efficiency": 0.30,
    },
    "equity": {
        "sharpe_ratio": 0.30,
        "max_drawdown_pct": 0.20,
        "annual_return_pct": 0.25,
        "annual_volatility_pct": 0.15,
        "pct_positive_months": 0.10,
    },
}


class PeerGroupService:
    """Peer group identification and percentile ranking engine."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._config = config or {}
        self._weights = self._config.get("weights", _DEFAULT_WEIGHTS)
        self._lower_is_better = LOWER_IS_BETTER

    def find_peers(
        self,
        db: Session,
        instrument_id: uuid.UUID,
        organization_id: str,
    ) -> PeerGroup | PeerGroupNotFound:
        """Find the peer group for an instrument.

        Queries the instruments_universe for same-type instruments in the
        same organization, then uses hierarchical matching to find a group
        with >= 20 members.
        """
        from app.domains.wealth.models.instrument import Instrument

        # Get target instrument
        target = db.execute(
            select(Instrument).where(
                Instrument.instrument_id == instrument_id,
                Instrument.organization_id == organization_id,
                Instrument.is_active.is_(True),
            )
        ).scalar_one_or_none()

        if target is None:
            return PeerGroupNotFound(
                instrument_id=instrument_id,
                reason="instrument_not_found",
            )

        if not target.block_id:
            return PeerGroupNotFound(
                instrument_id=instrument_id,
                reason="no_block_assigned",
            )

        # Get all active instruments of the same type in this org
        rows = db.execute(
            select(Instrument).where(
                Instrument.organization_id == organization_id,
                Instrument.instrument_type == target.instrument_type,
                Instrument.is_active.is_(True),
            )
        ).scalars().all()

        universe = [
            {
                "instrument_id": r.instrument_id,
                "instrument_type": r.instrument_type,
                "block_id": r.block_id,
                "attributes": r.attributes or {},
            }
            for r in rows
        ]

        return match_peers(
            target_instrument_id=instrument_id,
            target_type=target.instrument_type,
            target_block_id=target.block_id,
            target_attributes=target.attributes or {},
            universe=universe,
        )

    def compute_rankings(
        self,
        db: Session,
        instrument_id: uuid.UUID,
        organization_id: str,
    ) -> PeerRanking | PeerGroupNotFound:
        """Compute percentile rankings for an instrument within its peer group."""
        peer_result = self.find_peers(db, instrument_id, organization_id)

        if isinstance(peer_result, PeerGroupNotFound):
            return peer_result

        return self._rank_instrument(
            db=db,
            instrument_id=instrument_id,
            peer_group=peer_result,
            organization_id=organization_id,
        )

    def compute_rankings_batch(
        self,
        db: Session,
        instrument_ids: list[uuid.UUID],
        organization_id: str,
    ) -> list[PeerRanking | PeerGroupNotFound]:
        """Compute rankings for multiple instruments."""
        results: list[PeerRanking | PeerGroupNotFound] = []
        for iid in instrument_ids:
            try:
                result = self.compute_rankings(db, iid, organization_id)
                results.append(result)
            except Exception:
                logger.exception("peer_ranking_failed", instrument_id=str(iid))
                results.append(PeerGroupNotFound(
                    instrument_id=iid,
                    reason="no_metrics",
                ))
        return results

    def _rank_instrument(
        self,
        db: Session,
        instrument_id: uuid.UUID,
        peer_group: PeerGroup,
        organization_id: str,
    ) -> PeerRanking | PeerGroupNotFound:
        """Compute percentile rankings within a peer group."""

        # Get latest metrics for all peer group members
        peer_metrics = self._load_peer_metrics(
            db, peer_group.members, organization_id
        )

        if not peer_metrics:
            return PeerGroupNotFound(
                instrument_id=instrument_id,
                reason="no_metrics",
            )

        # Get target instrument's metrics
        target_metrics = peer_metrics.get(instrument_id)
        if not target_metrics:
            return PeerGroupNotFound(
                instrument_id=instrument_id,
                reason="no_metrics",
            )

        weights = self._weights.get(peer_group.instrument_type, {})
        rankings: list[MetricRanking] = []
        weighted_sum = 0.0
        total_weight = 0.0

        for metric_name, weight in weights.items():
            target_value = target_metrics.get(metric_name)
            if target_value is None:
                rankings.append(MetricRanking(
                    metric=metric_name,
                    value=None,
                    percentile=None,
                    lower_is_better=metric_name in self._lower_is_better,
                ))
                continue

            # Collect peer values for this metric
            peer_vals = [
                m.get(metric_name)
                for m in peer_metrics.values()
                if m.get(metric_name) is not None
            ]

            if len(peer_vals) < 3:
                rankings.append(MetricRanking(
                    metric=metric_name,
                    value=float(target_value),
                    percentile=None,
                    lower_is_better=metric_name in self._lower_is_better,
                ))
                continue

            peer_arr = np.array(peer_vals, dtype=float)

            # Winsorize at 1% tails
            lo = float(np.percentile(peer_arr, 1))
            hi = float(np.percentile(peer_arr, 99))
            if lo == hi:
                rankings.append(MetricRanking(
                    metric=metric_name,
                    value=float(target_value),
                    percentile=50.0,
                    lower_is_better=metric_name in self._lower_is_better,
                ))
                weighted_sum += weight * 50.0
                total_weight += weight
                continue

            clipped_val = float(np.clip(target_value, lo, hi))
            clipped_peers = np.clip(peer_arr, lo, hi).tolist()

            pctile = float(percentileofscore(clipped_peers, clipped_val, kind="rank"))

            if metric_name in self._lower_is_better:
                pctile = 100.0 - pctile

            pctile = round(pctile, 2)

            rankings.append(MetricRanking(
                metric=metric_name,
                value=float(target_value),
                percentile=pctile,
                lower_is_better=metric_name in self._lower_is_better,
            ))
            weighted_sum += weight * pctile
            total_weight += weight

        composite = round(weighted_sum / total_weight, 2) if total_weight > 0 else None

        return PeerRanking(
            instrument_id=instrument_id,
            peer_group_key=peer_group.peer_group_key,
            peer_count=peer_group.member_count,
            fallback_level=peer_group.fallback_level,
            rankings=tuple(rankings),
            composite_percentile=composite,
            ranked_at=datetime.now(timezone.utc),
        )

    def _load_peer_metrics(
        self,
        db: Session,
        member_ids: tuple[uuid.UUID, ...],
        organization_id: str,
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Load latest screening metrics for peer group members."""
        from app.domains.wealth.models.screening_metrics import InstrumentScreeningMetrics

        if not member_ids:
            return {}

        # Get latest metrics per instrument (most recent calc_date)
        rows = db.execute(
            select(InstrumentScreeningMetrics)
            .where(
                InstrumentScreeningMetrics.instrument_id.in_(list(member_ids)),
                InstrumentScreeningMetrics.organization_id == organization_id,
            )
            .order_by(
                InstrumentScreeningMetrics.instrument_id,
                InstrumentScreeningMetrics.calc_date.desc(),
            )
        ).scalars().all()

        # Keep only latest per instrument
        result: dict[uuid.UUID, dict[str, Any]] = {}
        for row in rows:
            if row.instrument_id not in result:
                result[row.instrument_id] = row.metrics or {}

        return result
