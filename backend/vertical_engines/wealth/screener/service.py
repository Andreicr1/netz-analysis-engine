"""Screener service — entry point for instrument screening.

Deterministic multi-layer instrument screener. No LLM.
Layer 1: Eliminatory (hard criteria per instrument type).
Layer 2: Mandate fit (per allocation block).
Layer 3: Quant scoring (percentile rank within peer group).

Session injection pattern: caller provides db session.
Config resolved once at async entry point via ConfigService, passed down.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from vertical_engines.wealth.screener.layer_evaluator import LayerEvaluator, determine_status
from vertical_engines.wealth.screener.models import (
    CriterionResult,
    InstrumentScreeningResult,
    ScreeningRunResult,
)
from vertical_engines.wealth.screener.quant_metrics import (
    BondQuantMetrics,
    FIQuantMetrics,
    QuantMetrics,
    composite_score,
)

logger = logging.getLogger(__name__)


class ScreenerService:
    """Deterministic multi-layer instrument screener. No LLM."""

    def __init__(
        self,
        config_layer1: dict[str, Any],
        config_layer2: dict[str, Any],
        config_layer3: dict[str, Any],
    ) -> None:
        self._config_layer1 = config_layer1
        self._config_layer2 = config_layer2
        self._config_layer3 = config_layer3
        self._evaluator = LayerEvaluator(config_layer1)

    @property
    def config_hash(self) -> str:
        """SHA-256 of the frozen screening config."""
        combined = json.dumps(
            {
                "layer1": self._config_layer1,
                "layer2": self._config_layer2,
                "layer3": self._config_layer3,
            },
            sort_keys=True,
        )
        return hashlib.sha256(combined.encode()).hexdigest()

    def screen_instrument(
        self,
        instrument_id: uuid.UUID,
        instrument_type: str,
        attributes: dict[str, Any],
        block_id: str | None = None,
        quant_metrics: QuantMetrics | BondQuantMetrics | FIQuantMetrics | None = None,
        peer_values: dict[str, list[float]] | None = None,
        previous_status: str | None = None,
    ) -> InstrumentScreeningResult:
        """Screen a single instrument through all 3 layers.

        Args:
            instrument_id: UUID of the instrument.
            instrument_type: 'fund', 'bond', or 'equity'.
            attributes: JSONB attributes dict from instruments_universe.
            block_id: AllocationBlock ID for Layer 2.
            quant_metrics: Pre-computed quant metrics for Layer 3.
            peer_values: Dict of metric → peer values for percentile ranking.
            previous_status: Previous screening status for hysteresis.

        Returns:
            InstrumentScreeningResult with all layer results.

        """
        all_results: list[CriterionResult] = []

        # ── Layer 1: Eliminatory ──────────────────────────────────
        l1_results = self._evaluator.evaluate_layer1(
            instrument_type, attributes, self._config_layer1,
        )
        all_results.extend(l1_results)

        if any(not r.passed for r in l1_results):
            return InstrumentScreeningResult(
                instrument_id=instrument_id,
                instrument_type=instrument_type,
                overall_status="FAIL",
                score=None,
                failed_at_layer=1,
                layer_results=all_results,
                required_analysis_type=self._analysis_type(instrument_type),
            )

        # ── Layer 2: Mandate fit ──────────────────────────────────
        l2_results = self._evaluator.evaluate_layer2(
            instrument_type, attributes, block_id, self._config_layer2,
        )
        all_results.extend(l2_results)

        if any(not r.passed for r in l2_results):
            # Check watchlist margin
            if self._within_watchlist_margin(l2_results, attributes):
                return InstrumentScreeningResult(
                    instrument_id=instrument_id,
                    instrument_type=instrument_type,
                    overall_status="WATCHLIST",
                    score=None,
                    failed_at_layer=2,
                    layer_results=all_results,
                    required_analysis_type=self._analysis_type(instrument_type),
                )
            return InstrumentScreeningResult(
                instrument_id=instrument_id,
                instrument_type=instrument_type,
                overall_status="FAIL",
                score=None,
                failed_at_layer=2,
                layer_results=all_results,
                required_analysis_type=self._analysis_type(instrument_type),
            )

        # ── Layer 3: Quant scoring ────────────────────────────────
        score = self._compute_layer3_score(
            instrument_type, quant_metrics, peer_values,
        )

        # Add Layer 3 criterion results for audit trail
        if score is not None:
            all_results.append(CriterionResult(
                criterion="composite_score",
                expected="0.0-1.0",
                actual=str(score),
                passed=True,
                layer=3,
            ))

        thresholds = self._config_layer3.get("thresholds", {})
        status = determine_status(score, previous_status, thresholds)

        return InstrumentScreeningResult(
            instrument_id=instrument_id,
            instrument_type=instrument_type,
            overall_status=status,
            score=score,
            failed_at_layer=None,
            layer_results=all_results,
            required_analysis_type=self._analysis_type(instrument_type),
        )

    def screen_universe(
        self,
        instruments: list[dict[str, Any]],
        organization_id: uuid.UUID,
        run_type: str = "batch",
    ) -> ScreeningRunResult:
        """Batch evaluate all instruments. Pure logic, no DB.

        Args:
            instruments: List of dicts with instrument_id, instrument_type,
                        attributes, block_id, quant_metrics, peer_values.
            organization_id: Tenant UUID.
            run_type: 'batch' or 'on_demand'.

        Returns:
            ScreeningRunResult with all individual results.

        """
        run_id = uuid.uuid4()
        started_at = datetime.now(UTC)
        results: list[InstrumentScreeningResult] = []

        for inst in instruments:
            try:
                result = self.screen_instrument(
                    instrument_id=inst["instrument_id"],
                    instrument_type=inst["instrument_type"],
                    attributes=inst.get("attributes", {}),
                    block_id=inst.get("block_id"),
                    quant_metrics=inst.get("quant_metrics"),
                    peer_values=inst.get("peer_values"),
                    previous_status=inst.get("previous_status"),
                )
                results.append(result)
            except Exception:
                logger.warning(
                    "Failed to screen instrument %s",
                    inst.get("instrument_id"),
                    exc_info=True,
                )

        return ScreeningRunResult(
            run_id=run_id,
            organization_id=organization_id,
            run_type=run_type,
            instrument_count=len(instruments),
            config_hash=self.config_hash,
            results=results,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

    def _compute_layer3_score(
        self,
        instrument_type: str,
        quant_metrics: QuantMetrics | BondQuantMetrics | FIQuantMetrics | None,
        peer_values: dict[str, list[float]] | None,
    ) -> float | None:
        """Compute Layer 3 composite score."""
        if quant_metrics is None:
            return None

        # FI funds use "fund_fixed_income" config key for distinct weights
        if isinstance(quant_metrics, FIQuantMetrics):
            config_key = "fund_fixed_income"
        else:
            config_key = instrument_type

        type_config = self._config_layer3.get(config_key, {})
        weights = type_config.get("weights", {})

        if not weights:
            return None

        # Convert dataclass to dict for scoring
        if isinstance(quant_metrics, FIQuantMetrics):
            metrics_dict = {
                "empirical_duration": quant_metrics.empirical_duration,
                "credit_beta": quant_metrics.credit_beta,
                "yield_proxy_12m": quant_metrics.yield_proxy_12m,
                "duration_adj_drawdown": quant_metrics.duration_adj_drawdown,
                "sharpe_ratio": quant_metrics.sharpe_ratio,
            }
        elif isinstance(quant_metrics, QuantMetrics):
            metrics_dict = {
                "sharpe_ratio": quant_metrics.sharpe_ratio,
                "max_drawdown": quant_metrics.max_drawdown_pct,
                "pct_positive_months": quant_metrics.pct_positive_months,
                "annual_volatility_pct": quant_metrics.annual_volatility_pct,
            }
        elif isinstance(quant_metrics, BondQuantMetrics):
            metrics_dict = {
                "spread_vs_benchmark": quant_metrics.spread_vs_benchmark_bps,
                "liquidity_score": quant_metrics.liquidity_score,
                "duration_efficiency": quant_metrics.duration_efficiency,
            }
        else:
            return None

        return composite_score(
            metrics=metrics_dict,
            peer_values=peer_values or {},
            weights=weights,
        )

    @staticmethod
    def _within_watchlist_margin(
        l2_results: list[CriterionResult],
        attributes: dict[str, Any],
    ) -> bool:
        """Check if Layer 2 failures are within watchlist margin (10%)."""
        for result in l2_results:
            if result.passed:
                continue
            # Check if the failure is within 10% of the threshold
            try:
                actual = float(result.actual)
                expected = float(result.expected)
                if expected != 0:
                    margin = abs(actual - expected) / abs(expected)
                    if margin <= 0.10:
                        return True
            except (ValueError, TypeError):
                continue
        return False

    @staticmethod
    def _analysis_type(instrument_type: str) -> str:
        """Determine required analysis type by instrument type."""
        if instrument_type == "bond":
            return "bond_brief"
        if instrument_type in ("fund", "equity"):
            return "dd_report"
        return "none"
