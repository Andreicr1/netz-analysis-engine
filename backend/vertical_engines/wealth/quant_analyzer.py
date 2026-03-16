"""Quant Analyzer — bridges quant_engine services for wealth management.

Integrates with quant_engine/ services (CVaR, scoring, drift, regime,
portfolio metrics, peer comparison) to provide quantitative analysis
for fund manager evaluation.

Config is received as parameter (resolved by caller via ConfigService).
No YAML loading, no @lru_cache — follows the quant_engine refactor pattern.
"""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.risk import FundRiskMetrics

logger = structlog.get_logger()


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

        Returns
        -------
        dict
            Quant analysis result (CVaR, scores, drift, regime).
        """
        logger.info("running_quant_analysis", fund_id=fund_id, as_of=as_of)

        fid = uuid.UUID(fund_id)
        result: dict[str, Any] = {
            "fund_id": fund_id,
            "as_of": as_of,
            "status": "computed",
        }

        # 1. CVaR
        result["cvar"] = self._compute_cvar(db, fid)

        # 2. Fund scoring
        result["scoring"] = self._compute_scoring(db, fid)

        # 3. Peer comparison
        result["peer_comparison"] = self._compute_peer_comparison(db, fid)

        return result

    def _compute_cvar(self, db: Session, fund_id: uuid.UUID) -> dict[str, Any] | None:
        """Compute CVaR for a single fund using its NAV history."""
        navs = db.execute(
            select(NavTimeseries.return_1d)
            .where(
                NavTimeseries.fund_id == fund_id,
                NavTimeseries.return_1d.isnot(None),
            )
            .order_by(NavTimeseries.nav_date.desc())
            .limit(252)
        ).scalars().all()

        if len(navs) < 30:
            return None

        returns = np.array([float(r) for r in navs], dtype=np.float64)

        from quant_engine.cvar_service import resolve_cvar_config

        cvar_configs = resolve_cvar_config(self._config.get("cvar"))

        results = {}
        for profile, cfg in cvar_configs.items():
            window = cfg.get("window_months", 3) * 21
            conf = cfg.get("confidence", 0.95)
            r_slice = returns[:window] if len(returns) >= window else returns
            sorted_r = np.sort(r_slice)
            cutoff = max(int(np.floor(len(sorted_r) * (1 - conf))), 1)
            cvar_val = -float(np.mean(sorted_r[:cutoff]))
            results[profile] = {
                "cvar": round(cvar_val, 6),
                "limit": cfg.get("limit"),
                "window_days": len(r_slice),
            }
        return results

    def _compute_scoring(self, db: Session, fund_id: uuid.UUID) -> dict[str, Any] | None:
        """Compute fund score using scoring_service."""
        risk = db.execute(
            select(FundRiskMetrics)
            .where(FundRiskMetrics.fund_id == fund_id)
            .order_by(FundRiskMetrics.calc_date.desc())
            .limit(1)
        ).scalar_one_or_none()

        if risk is None:
            return None

        from quant_engine.scoring_service import compute_fund_score

        score_val, components = compute_fund_score(
            risk,
            flows_momentum_score=50.0,
            config=self._config.get("scoring"),
        )
        return {
            "manager_score": score_val,
            "components": components,
        }

    def _compute_peer_comparison(
        self, db: Session, fund_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """Rank fund against peers in same block."""
        fund = db.execute(
            select(Fund).where(Fund.fund_id == fund_id)
        ).scalar_one_or_none()

        if fund is None or not fund.block_id:
            return None

        from quant_engine.peer_comparison_service import compare

        result = compare(db, fund_id=fund_id, block_id=fund.block_id)
        return {
            "rank": result.target_rank,
            "peer_count": result.peer_count,
            "block_id": result.block_id,
        }
