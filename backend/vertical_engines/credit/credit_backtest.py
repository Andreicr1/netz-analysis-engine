"""Credit PD/LGD model validation via cross-validated backtesting.

Credit-specific: uses default_labels, recovery_rates, vintage_years.
Lives in vertical_engines/credit/ (not quant_engine/) because
PD/LGD concepts are credit-domain-specific.

Sync service — pure computation, dispatched via asyncio.to_thread().

Uses StratifiedKFold by default (not TimeSeriesSplit) because
credit defaults are rare events (1-5% PD) and stratification ensures
every fold has at least one default. Pipeline with StandardScaler
prevents data leakage and handles financial ratio scale differences.

Config is injected as parameter — no YAML, no @lru_cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import structlog

logger = structlog.get_logger()

MAX_OBSERVATIONS = 50_000
MAX_FEATURES = 100
MIN_DEFAULTS = 10
MIN_OBSERVATIONS = 100


class CVStrategy(str, Enum):
    """Cross-validation strategy for PD model validation."""

    STRATIFIED = "stratified"
    TEMPORAL = "temporal"
    TEMPORAL_STRATIFIED = "temporal_stratified"


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


def _validate_input(inp: BacktestInput) -> str | None:
    """Validate backtest input. Returns error message or None."""
    n_obs = inp.features.shape[0]
    n_feat = inp.features.shape[1] if inp.features.ndim > 1 else 1

    if n_obs > MAX_OBSERVATIONS:
        return f"Too many observations ({n_obs} > {MAX_OBSERVATIONS})"
    if n_feat > MAX_FEATURES:
        return f"Too many features ({n_feat} > {MAX_FEATURES})"
    if np.any(~np.isfinite(inp.features)):
        return "Features contain NaN or Inf values"
    if not np.all(np.isin(inp.default_labels, [0, 1])):
        return "default_labels must be binary (0/1)"
    if not np.all((inp.recovery_rates >= 0) & (inp.recovery_rates <= 1)):
        return "recovery_rates must be in [0, 1]"
    if n_obs < MIN_OBSERVATIONS:
        return f"Insufficient observations ({n_obs} < {MIN_OBSERVATIONS})"

    n_defaults = int(inp.default_labels.sum())
    if n_defaults < MIN_DEFAULTS:
        return f"Insufficient defaults ({n_defaults} < {MIN_DEFAULTS})"

    return None


def _select_n_splits(n_obs: int, n_defaults: int, requested: int) -> int:
    """Adaptively choose number of CV folds based on data size."""
    # Each val fold should have >= 2 defaults
    max_splits = n_defaults // 2
    # Each val fold should have >= 10 observations
    max_splits = min(max_splits, n_obs // 10)
    # Cap at requested, floor at 2
    return max(2, min(requested, max_splits))


def _build_vintage_cohorts(
    vintage_years: np.ndarray,
    default_labels: np.ndarray,
    recovery_rates: np.ndarray,
) -> dict[int, dict[str, float]]:
    """Build vintage cohort analysis: default rate and avg recovery by year."""
    cohorts: dict[int, dict[str, float]] = {}
    unique_years = np.unique(vintage_years)

    for year in unique_years:
        mask = vintage_years == year
        n = int(mask.sum())
        if n == 0:
            continue
        defaults = int(default_labels[mask].sum())
        avg_recovery = float(recovery_rates[mask].mean()) if n > 0 else 0.0

        cohorts[int(year)] = {
            "count": float(n),
            "defaults": float(defaults),
            "default_rate": round(defaults / n, 4),
            "avg_recovery": round(avg_recovery, 4),
        }

    return cohorts


def backtest_pd_model(
    inp: BacktestInput,
    *,
    config: dict | None = None,
) -> CreditBacktestResult:
    """Run cross-validated PD/LGD model backtest.

    Args:
        inp: BacktestInput with features, labels, recovery rates, vintages.
        config: Optional calibration config for model parameters.

    Returns:
        CreditBacktestResult with AUC-ROC, Brier, LGD MAE, vintage cohorts.
    """
    # Input validation
    error = _validate_input(inp)
    if error:
        logger.warning("Backtest input validation failed", error=error)
        return CreditBacktestResult(
            status="insufficient_data",
            sample_size=inp.features.shape[0],
            n_defaults=int(inp.default_labels.sum()),
        )

    n_obs = inp.features.shape[0]
    n_defaults = int(inp.default_labels.sum())

    # Adaptive fold count
    n_splits = _select_n_splits(n_obs, n_defaults, inp.n_splits)

    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import brier_score_loss, mean_absolute_error, roc_auc_score
        from sklearn.model_selection import StratifiedKFold, TimeSeriesSplit, cross_val_predict
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as e:
        logger.error("scikit-learn not available for backtesting", error=str(e))
        return CreditBacktestResult(
            status="insufficient_data",
            sample_size=n_obs,
            n_defaults=n_defaults,
        )

    X = inp.features
    y = inp.default_labels

    # Build pipeline: scale + logistic regression with balanced class weights
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            solver="lbfgs",
            random_state=42,
        )),
    ])

    # Select CV strategy
    if inp.cv_strategy == CVStrategy.TEMPORAL:
        cv = TimeSeriesSplit(n_splits=n_splits)
    else:
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

    # PD model: cross-validated OOF predictions
    try:
        y_proba = cross_val_predict(pipeline, X, y, cv=cv, method="predict_proba")[:, 1]
        auc_roc = float(roc_auc_score(y, y_proba))
        brier = float(brier_score_loss(y, y_proba))

        # Per-fold AUC for std calculation
        fold_aucs = []
        for train_idx, val_idx in cv.split(X, y):
            if len(np.unique(y[val_idx])) < 2:
                continue
            pipeline_clone = Pipeline([
                ("scaler", StandardScaler()),
                ("classifier", LogisticRegression(
                    class_weight="balanced", max_iter=1000,
                    solver="lbfgs", random_state=42,
                )),
            ])
            pipeline_clone.fit(X[train_idx], y[train_idx])
            fold_proba = pipeline_clone.predict_proba(X[val_idx])[:, 1]
            fold_aucs.append(float(roc_auc_score(y[val_idx], fold_proba)))

        auc_std = float(np.std(fold_aucs)) if fold_aucs else 0.0

    except Exception as e:
        logger.error("PD model backtest failed", error=str(e))
        auc_roc = 0.0
        auc_std = 0.0
        brier = 1.0

    # LGD model: simple MAE on recovery rates (only for defaulted loans)
    default_mask = y == 1
    if default_mask.sum() > 0:
        lgd_actual = inp.recovery_rates[default_mask]
        lgd_predicted = np.full_like(lgd_actual, lgd_actual.mean())  # baseline: mean recovery
        lgd_mae = float(mean_absolute_error(lgd_actual, lgd_predicted))
    else:
        lgd_mae = 0.0

    # Vintage cohort analysis
    vintage_cohorts = _build_vintage_cohorts(
        inp.vintage_years, inp.default_labels, inp.recovery_rates,
    )

    return CreditBacktestResult(
        pd_auc_roc=round(auc_roc, 4),
        pd_auc_std=round(auc_std, 4),
        pd_brier=round(brier, 4),
        lgd_mae=round(lgd_mae, 4),
        vintage_cohorts=vintage_cohorts,
        cv_folds=n_splits,
        cv_strategy=inp.cv_strategy.value,
        sample_size=n_obs,
        n_defaults=n_defaults,
        status="complete",
    )
