"""Correlation regime service — wealth-specific orchestration.

Resolves portfolio instruments, maps quant_engine results to domain models.
Pure sync, designed for asyncio.to_thread().
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from quant_engine.correlation_regime_service import compute_correlation_regime
from vertical_engines.wealth.correlation.models import (
    ConcentrationAnalysis,
    InstrumentCorrelation,
    PortfolioCorrelationResult,
)

logger = structlog.get_logger()


class CorrelationService:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    def analyze_portfolio_correlation(
        self,
        instrument_ids: tuple[str, ...],
        instrument_names: tuple[str, ...],
        returns_matrix: np.ndarray,
        weights: np.ndarray | None = None,
        profile: str = "",
    ) -> PortfolioCorrelationResult:
        """Analyze correlation regime for portfolio instruments.

        Parameters
        ----------
        instrument_ids : tuple[str, ...]
            Instrument UUID strings.
        instrument_names : tuple[str, ...]
            Instrument display names (same order).
        returns_matrix : np.ndarray
            (T, N) daily returns, pre-aligned by date intersection.
        weights : np.ndarray | None
            Portfolio weights. None = equal weight.
        profile : str
            Portfolio profile name.

        """
        result = compute_correlation_regime(
            returns_matrix=returns_matrix,
            weights=weights,
            config=self._config,
        )

        if not result.sufficient_data:
            return PortfolioCorrelationResult(
                profile=profile,
                instrument_count=len(instrument_ids),
                window_days=0,
                correlation_matrix=(),
                instrument_labels=instrument_names,
                instrument_ids=instrument_ids,
                contagion_pairs=(),
                concentration=ConcentrationAnalysis(
                    eigenvalues=(), explained_variance_ratios=(),
                    first_eigenvalue_ratio=0.0, concentration_status="diversified",
                    diversification_ratio=1.0, dr_alert=False,
                    absorption_ratio=0.0, absorption_status="normal",
                    mp_threshold=0.0, n_signal_eigenvalues=0,
                ),
                average_correlation=0.0,
                baseline_average_correlation=0.0,
                regime_shift_detected=False,
                computed_at=datetime.now(UTC).isoformat(),
            )

        # Map pair indices to instrument identifiers
        contagion_pairs = tuple(
            InstrumentCorrelation(
                instrument_a_id=instrument_ids[p.index_a],
                instrument_a_name=instrument_names[p.index_a],
                instrument_b_id=instrument_ids[p.index_b],
                instrument_b_name=instrument_names[p.index_b],
                current_correlation=p.current_correlation,
                baseline_correlation=p.baseline_correlation,
                correlation_change=p.correlation_change,
                is_contagion=p.is_contagion,
            )
            for p in result.pair_correlations
        )

        concentration = ConcentrationAnalysis(
            eigenvalues=result.concentration.eigenvalues,
            explained_variance_ratios=result.concentration.explained_variance_ratios,
            first_eigenvalue_ratio=result.concentration.first_eigenvalue_ratio,
            concentration_status=result.concentration.concentration_status,
            diversification_ratio=result.diversification_ratio,
            dr_alert=result.dr_alert,
            absorption_ratio=result.concentration.absorption_ratio,
            absorption_status=result.concentration.absorption_status,
            mp_threshold=result.concentration.mp_threshold,
            n_signal_eigenvalues=result.concentration.n_signal_eigenvalues,
        )

        return PortfolioCorrelationResult(
            profile=profile,
            instrument_count=result.instrument_count,
            window_days=result.window_days,
            correlation_matrix=result.correlation_matrix,
            instrument_labels=instrument_names,
            instrument_ids=instrument_ids,
            contagion_pairs=contagion_pairs,
            concentration=concentration,
            average_correlation=result.average_correlation,
            baseline_average_correlation=result.baseline_average_correlation,
            regime_shift_detected=result.regime_shift_detected,
            computed_at=datetime.now(UTC).isoformat(),
        )
