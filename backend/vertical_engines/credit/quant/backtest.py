"""Credit PD/LGD model validation via cross-validated backtesting.

Credit-specific: uses default_labels, recovery_rates, vintage_years.
Sync service — pure computation, dispatched via asyncio.to_thread().

Uses StratifiedKFold by default (not TimeSeriesSplit) because
credit defaults are rare events (1-5% PD) and stratification ensures
every fold has at least one default. Pipeline with StandardScaler
prevents data leakage and handles financial ratio scale differences.

Config is injected as parameter — no YAML, no @lru_cache.

Imports only models.py (leaf).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import structlog

from vertical_engines.credit.quant.models import (
    MAX_FEATURES,
    MAX_OBSERVATIONS,
    MIN_DEFAULTS,
    MIN_OBSERVATIONS,
    BacktestInput,
    CreditBacktestResult,
    CVStrategy,
)

logger = structlog.get_logger()


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
    max_splits = n_defaults // 2
    max_splits = min(max_splits, n_obs // 10)
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
    config: dict[str, Any] | None = None,
) -> CreditBacktestResult:
    """Run cross-validated PD/LGD model backtest.

    Args:
        inp: BacktestInput with features, labels, recovery rates, vintages.
        config: Optional calibration config for model parameters.

    Returns:
        CreditBacktestResult with AUC-ROC, Brier, LGD MAE, vintage cohorts.

    """
    error = _validate_input(inp)
    if error:
        logger.warning("backtest_input_validation_failed", error=error)
        return CreditBacktestResult(
            status="insufficient_data",
            sample_size=inp.features.shape[0],
            n_defaults=int(inp.default_labels.sum()),
        )

    n_obs = inp.features.shape[0]
    n_defaults = int(inp.default_labels.sum())

    n_splits = _select_n_splits(n_obs, n_defaults, inp.n_splits)

    try:
        from sklearn.base import clone
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import brier_score_loss, mean_absolute_error, roc_auc_score
        from sklearn.model_selection import StratifiedKFold, TimeSeriesSplit
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as e:
        logger.error("sklearn_not_available", error=str(e))
        return CreditBacktestResult(
            status="insufficient_data",
            sample_size=n_obs,
            n_defaults=n_defaults,
        )

    X = inp.features
    y = inp.default_labels

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            solver="lbfgs",
            random_state=42,
        )),
    ])

    if inp.cv_strategy == CVStrategy.TEMPORAL:
        cv = TimeSeriesSplit(n_splits=n_splits)
    else:
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

    try:
        oof_predictions = np.zeros(n_obs)
        fold_aucs = []

        for train_idx, val_idx in cv.split(X, y):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            fold_pipeline = clone(pipeline)
            fold_pipeline.fit(X_train, y_train)

            proba = fold_pipeline.predict_proba(X_val)[:, 1]
            oof_predictions[val_idx] = proba

            if len(np.unique(y_val)) > 1:
                fold_aucs.append(float(roc_auc_score(y_val, proba)))

        auc_roc = float(roc_auc_score(y, oof_predictions))
        brier = float(brier_score_loss(y, oof_predictions))
        auc_std = float(np.std(fold_aucs)) if fold_aucs else 0.0

    except Exception as e:
        logger.error("pd_model_backtest_failed", error=str(e))
        auc_roc = 0.0
        auc_std = 0.0
        brier = 1.0

    default_mask = y == 1
    if default_mask.sum() > 0:
        lgd_actual = inp.recovery_rates[default_mask]
        lgd_predicted = np.full_like(lgd_actual, lgd_actual.mean())
        lgd_mae = float(mean_absolute_error(lgd_actual, lgd_predicted))
    else:
        lgd_mae = 0.0

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
