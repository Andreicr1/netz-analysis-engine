"""Quant Injection — bridge to quant_engine services for DD Report evidence.

Gathers quantitative metrics (CVaR, Sharpe, scoring, risk) from the
quant_engine and formats them for evidence pack injection.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

logger = structlog.get_logger()


def gather_quant_metrics(
    db: Session,
    *,
    instrument_id: str,
    organization_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gather quantitative metrics for a fund from the database.

    Queries fund_risk_metrics for the latest calc_date and extracts
    key metrics for DD Report chapter generation.

    Parameters
    ----------
    db : Session
        Sync database session.
    instrument_id : str
        UUID of the fund to gather metrics for.
    config : dict
        Optional calibration config (token budgets, windows).

    Returns
    -------
    dict
        Quant profile with CVaR, Sharpe, returns, scoring data.

    """
    logger.info("gathering_quant_metrics", instrument_id=instrument_id)

    try:
        from app.domains.wealth.models.risk import FundRiskMetrics

        row = (
            db.query(FundRiskMetrics)
            .filter(
                FundRiskMetrics.instrument_id == instrument_id,
                FundRiskMetrics.organization_id == organization_id,
            )
            .order_by(FundRiskMetrics.calc_date.desc())
            .first()
        )

        if not row:
            logger.warning("no_risk_metrics_found", instrument_id=instrument_id)
            return {}

        return {
            "calc_date": str(row.calc_date),
            "cvar_95_1m": _to_float(row.cvar_95_1m),
            "cvar_95_3m": _to_float(row.cvar_95_3m),
            "cvar_95_6m": _to_float(row.cvar_95_6m),
            "cvar_95_12m": _to_float(row.cvar_95_12m),
            "var_95_1m": _to_float(row.var_95_1m),
            "var_95_3m": _to_float(row.var_95_3m),
            "return_1m": _to_float(row.return_1m),
            "return_3m": _to_float(row.return_3m),
            "return_6m": _to_float(row.return_6m),
            "return_1y": _to_float(row.return_1y),
            "return_3y_ann": _to_float(row.return_3y_ann),
            "volatility_1y": _to_float(row.volatility_1y),
            "max_drawdown_1y": _to_float(row.max_drawdown_1y),
            "sharpe_1y": _to_float(row.sharpe_1y),
            "sharpe_3y": _to_float(row.sharpe_3y),
            "sortino_1y": _to_float(row.sortino_1y),
            "alpha_1y": _to_float(row.alpha_1y),
            "beta_1y": _to_float(row.beta_1y),
            "information_ratio_1y": _to_float(row.information_ratio_1y),
            "tracking_error_1y": _to_float(row.tracking_error_1y),
            "manager_score": _to_float(row.manager_score),
            "score_components": row.score_components or {},
            "dtw_drift_score": _to_float(row.dtw_drift_score),
        }

    except Exception:
        logger.exception("quant_metrics_gather_failed", instrument_id=instrument_id)
        return {}


def gather_risk_metrics(
    db: Session,
    *,
    instrument_id: str,
    organization_id: str,
) -> dict[str, Any]:
    """Gather risk-specific metrics formatted for the risk chapter."""
    profile = gather_quant_metrics(db, instrument_id=instrument_id, organization_id=organization_id)
    if not profile:
        return {}

    return {
        "cvar_windows": {
            "1m": profile.get("cvar_95_1m"),
            "3m": profile.get("cvar_95_3m"),
            "6m": profile.get("cvar_95_6m"),
            "12m": profile.get("cvar_95_12m"),
        },
        "var_windows": {
            "1m": profile.get("var_95_1m"),
            "3m": profile.get("var_95_3m"),
        },
        "volatility_1y": profile.get("volatility_1y"),
        "max_drawdown_1y": profile.get("max_drawdown_1y"),
        "sharpe_1y": profile.get("sharpe_1y"),
        "sortino_1y": profile.get("sortino_1y"),
        "beta_1y": profile.get("beta_1y"),
        "dtw_drift_score": profile.get("dtw_drift_score"),
    }


def _to_float(val: Any) -> float | None:
    """Safely convert Decimal/numeric to float for JSON serialization."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
