"""Correlation regime domain models — wealth-specific.

Frozen dataclasses for cross-boundary safety.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InstrumentCorrelation:
    """Correlation pair with instrument identifiers."""

    instrument_a_id: str
    instrument_a_name: str
    instrument_b_id: str
    instrument_b_name: str
    current_correlation: float
    baseline_correlation: float
    correlation_change: float
    is_contagion: bool


@dataclass(frozen=True, slots=True)
class ConcentrationAnalysis:
    """Eigenvalue concentration with portfolio context."""

    eigenvalues: tuple[float, ...]
    explained_variance_ratios: tuple[float, ...]
    first_eigenvalue_ratio: float
    concentration_status: str
    diversification_ratio: float
    dr_alert: bool
    absorption_ratio: float
    absorption_status: str
    mp_threshold: float  # Marchenko-Pastur upper bound lambda_plus
    n_signal_eigenvalues: int  # eigenvalues above mp_threshold


@dataclass(frozen=True, slots=True)
class PortfolioCorrelationResult:
    """Full correlation regime result for a portfolio."""

    profile: str
    instrument_count: int
    window_days: int
    correlation_matrix: tuple[tuple[float, ...], ...]
    instrument_labels: tuple[str, ...]
    instrument_ids: tuple[str, ...]
    contagion_pairs: tuple[InstrumentCorrelation, ...]
    concentration: ConcentrationAnalysis
    average_correlation: float
    baseline_average_correlation: float
    regime_shift_detected: bool
    computed_at: str
