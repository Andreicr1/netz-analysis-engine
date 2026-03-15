"""Fund Analyzer — 7-chapter fund manager due diligence report.

Implements :class:`BaseAnalyzer` for the ``liquid_funds`` profile.
Each chapter covers a key dimension of fund manager assessment:

  1. Executive Summary
  2. Investment Strategy & Process
  3. Performance Analysis (quant)
  4. Risk Management Framework
  5. Operational Due Diligence
  6. Terms & Fees
  7. Recommendation

Config is resolved via :class:`ConfigService` — never reads YAML directly.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from vertical_engines.base.base_analyzer import BaseAnalyzer

logger = logging.getLogger(__name__)


class FundAnalyzer(BaseAnalyzer):
    """Wealth Management fund analyzer — implements BaseAnalyzer."""

    vertical = "liquid_funds"

    def run_deal_analysis(
        self,
        db: Session,
        *,
        fund_id: str,
        deal_id: str,
        actor_id: str,
        force: bool = False,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run fund manager DD report (7-chapter analysis).

        In wealth context, "deal" is a fund manager evaluation.
        """
        from vertical_engines.wealth.dd_report_engine import DDReportEngine

        engine = DDReportEngine(config=config)
        return engine.generate(
            db,
            fund_id=fund_id,
            target_id=deal_id,
            actor_id=actor_id,
            force=force,
        )

    def run_portfolio_analysis(
        self,
        db: Session,
        *,
        fund_id: str,
        actor_id: str,
        as_of: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run portfolio-level quant analysis (CVaR, drift, scoring)."""
        from vertical_engines.wealth.quant_analyzer import QuantAnalyzer

        analyzer = QuantAnalyzer(config=config)
        return analyzer.analyze_portfolio(
            db,
            fund_id=fund_id,
            actor_id=actor_id,
            as_of=as_of,
        )

    # run_pipeline_analysis: inherits default from BaseAnalyzer
    # (wealth has no pipeline concept)
