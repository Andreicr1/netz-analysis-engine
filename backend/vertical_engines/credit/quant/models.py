"""Quant engine data types and constants (LEAF — zero sibling imports).

Contains QuantProfile (existing manual to_dict()), BacktestInput,
CreditBacktestResult, CVStrategy, and all constants used across the package.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

# ── Regex for numeric parsing ─────────────────────────────────────────
NUM_RE = re.compile(r"[\d]+(?:\.[\d]+)?")

# ── Risk-adjusted return constants ────────────────────────────────────
SEVERITY_HAIRCUT_PP: dict[str, float] = {
    "HIGH": 2.5,
    "MEDIUM": 1.2,
    "LOW": 0.5,
}
MAX_TOTAL_HAIRCUT_PP = 8.0

# ── Legacy fee map (for migration shim) ──────────────────────────────
FEE_MAP: dict[str, str] = {
    "managementFee": "Mgmt Fee",
    "performanceFee": "Perf Fee",
    "servicingFee": "Servicing Fee",
    "adminFee": "Admin Fee",
    "originationFee": "Origination Fee",
    "exitFee": "Exit Fee",
}

# ── Backtest constants ────────────────────────────────────────────────
MAX_OBSERVATIONS = 50_000
MAX_FEATURES = 100
MIN_DEFAULTS = 10
MIN_OBSERVATIONS = 100


class CVStrategy(str, Enum):
    """Cross-validation strategy for PD model validation."""

    STRATIFIED = "stratified"
    TEMPORAL = "temporal"


@dataclass
class BacktestInput:
    """Historical default/recovery observations for model validation."""

    features: np.ndarray  # (N, F) financial ratios
    default_labels: np.ndarray  # (N,) 0/1 default indicator
    recovery_rates: np.ndarray  # (N,) realized LGD (0-1)
    vintage_years: np.ndarray  # (N,) origination year
    cv_strategy: CVStrategy = CVStrategy.STRATIFIED
    n_splits: int = 5


@dataclass
class CreditBacktestResult:
    """Backtest result with PD and LGD model metrics."""

    pd_auc_roc: float = 0.0
    pd_auc_std: float = 0.0  # std across folds
    pd_brier: float = 0.0
    lgd_mae: float = 0.0
    vintage_cohorts: dict[int, dict[str, float]] = field(default_factory=dict)
    cv_folds: int = 0
    cv_strategy: str = "stratified"
    sample_size: int = 0
    n_defaults: int = 0
    status: str = "complete"  # complete | insufficient_data


@dataclass
class QuantProfile:
    """Deterministic quantitative profile for an investment opportunity."""

    # ── Schema tracking ──────────────────────────────────────────
    schema_version_used: str = "2.0"

    # Core yield metrics
    coupon_rate_pct: float | None = None
    all_in_yield_pct: float | None = None
    spread_bps: int | None = None

    # Fee metrics (deprecated — kept for backward compat)
    origination_fee_pct: float | None = None
    exit_fee_pct: float | None = None

    # ── A: Rate Decomposition ────────────────────────────────────
    gross_coupon_pct: float | None = None
    base_rate_short_pct: float | None = None
    floor_bps: int | None = None
    fee_stack_annualized_pct: float | None = None
    net_return_proxy_pct: float | None = None
    fee_notes: list[str] = field(default_factory=list)

    # Return metrics
    target_irr_pct: float | None = None
    target_multiple: float | None = None
    yield_to_maturity_pct: float | None = None

    # Sizing
    principal_amount: float | None = None
    currency: str | None = None

    # ── D: Duration / maturity ───────────────────────────────────
    maturity_years: float | None = None
    maturity_years_confidence: str | None = None  # EXACT | PARSED | MISSING
    tenor_bucket: str | None = None  # <1y | 1-3y | 3-5y | >5y

    # ── G: Liquidity quant hooks ─────────────────────────────────
    notice_period_days: int | None = None
    gate_pct_per_period: float | None = None
    suspension_rights_flag: bool | None = None
    lockup_months: float | None = None
    liquidity_flags: list[str] = field(default_factory=list)

    # ── H: Credit Coverage Ratios ────────────────────────────────
    dscr: float | None = None
    interest_coverage_ratio: float | None = None
    leverage_ratio: float | None = None
    ltv_pct: float | None = None
    credit_metrics_confidence: str | None = None
    credit_metrics_source: str | None = None
    credit_coverage_flags: list[str] = field(default_factory=list)

    # ── E: Risk-adjusted ─────────────────────────────────────────
    risk_adjusted_return_pct: float | None = None
    risk_adjusted_notes: list[str] = field(default_factory=list)

    # ── Legacy sensitivity (deprecated — kept for backward compat) ─
    sensitivity_matrix: list[dict[str, Any]] = field(default_factory=list)

    # ── C: Sensitivity 2D / 3D ───────────────────────────────────
    sensitivity_2d: list[dict[str, Any]] = field(default_factory=list)
    sensitivity_3d_summary: dict[str, Any] = field(default_factory=dict)

    # ── B: Scenario results ──────────────────────────────────────
    scenario_results: list[dict[str, Any]] = field(default_factory=list)

    # ── F: Status / Proxy flags ──────────────────────────────────
    metrics_status: str = "COMPLETE"
    missing_fields: list[str] = field(default_factory=list)
    proxy_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            # Schema
            "schema_version_used": self.schema_version_used,
            # Core yield
            "coupon_rate_pct": self.coupon_rate_pct,
            "all_in_yield_pct": self.all_in_yield_pct,
            "spread_bps": self.spread_bps,
            # Deprecated fee fields (backward compat)
            "origination_fee_pct": self.origination_fee_pct,
            "exit_fee_pct": self.exit_fee_pct,
            # Rate decomposition
            "gross_coupon_pct": self.gross_coupon_pct,
            "base_rate_short_pct": self.base_rate_short_pct,
            "floor_bps": self.floor_bps,
            "fee_stack_annualized_pct": self.fee_stack_annualized_pct,
            "net_return_proxy_pct": self.net_return_proxy_pct,
            "fee_notes": self.fee_notes,
            # Returns
            "target_irr_pct": self.target_irr_pct,
            "target_multiple": self.target_multiple,
            "yield_to_maturity_pct": self.yield_to_maturity_pct,
            # Sizing
            "principal_amount": self.principal_amount,
            "currency": self.currency,
            # Maturity / tenor
            "maturity_years": self.maturity_years,
            "maturity_years_confidence": self.maturity_years_confidence,
            "tenor_bucket": self.tenor_bucket,
            # Liquidity quant hooks
            "notice_period_days": self.notice_period_days,
            "gate_pct_per_period": self.gate_pct_per_period,
            "suspension_rights_flag": self.suspension_rights_flag,
            "lockup_months": self.lockup_months,
            "liquidity_flags": self.liquidity_flags,
            # Credit coverage
            "dscr": self.dscr,
            "interest_coverage_ratio": self.interest_coverage_ratio,
            "leverage_ratio": self.leverage_ratio,
            "ltv_pct": self.ltv_pct,
            "credit_metrics_confidence": self.credit_metrics_confidence,
            "credit_metrics_source": self.credit_metrics_source,
            "credit_coverage_flags": self.credit_coverage_flags,
            # Risk
            "risk_adjusted_return_pct": self.risk_adjusted_return_pct,
            "risk_adjusted_notes": self.risk_adjusted_notes,
            # Sensitivity
            "sensitivity_matrix": self.sensitivity_matrix,
            "sensitivity_2d": self.sensitivity_2d,
            "sensitivity_3d_summary": self.sensitivity_3d_summary,
            # Scenarios
            "scenario_results": self.scenario_results,
            # Status
            "metrics_status": self.metrics_status,
            "missing_fields": self.missing_fields,
            "proxy_flags": self.proxy_flags,
        }
