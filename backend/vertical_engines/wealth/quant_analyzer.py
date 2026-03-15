"""Quant Analyzer — bridges quant_engine services for wealth DD reports.

Integrates with quant_engine/ services (CVaR, Sharpe, drawdown, regime)
to provide quantitative analysis for fund manager evaluation.

Config is received as parameter (resolved by caller via ConfigService).
No YAML loading, no @lru_cache — follows the quant_engine refactor pattern.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class QuantAnalyzer:
    """Quantitative analysis for wealth management."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    def analyze_portfolio(
        self,
        db: Session,
        *,
        fund_id: str,
        actor_id: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Run portfolio-level quant analysis.

        Delegates to quant_engine services with config injected as parameter.

        Parameters
        ----------
        db : Session
            Caller-provided database session.
        fund_id : str
            Fund to analyze.
        actor_id : str
            User performing the action.
        as_of : str | None
            Point-in-time date (ISO format).

        Returns
        -------
        dict
            Quant analysis result (CVaR, scores, drift, regime).
        """
        logger.info("Running quant analysis fund=%s as_of=%s", fund_id, as_of)

        # TODO(Sprint 5+): Wire to actual quant_engine services.
        # The pattern will be:
        #   cvar_config = resolve_cvar_config(self._config)
        #   cvar_result = compute_cvar(db, fund_id=fund_id, config=cvar_config)
        #   scoring = compute_scoring(db, fund_id=fund_id, config=self._config)
        #   drift = check_drift(db, fund_id=fund_id, config=self._config)

        return {
            "fund_id": fund_id,
            "as_of": as_of,
            "status": "scaffold",
            "cvar": None,
            "scoring": None,
            "drift": None,
            "regime": None,
        }

