"""Fund Analyzer — 8-chapter fund manager due diligence report.

Implements :class:`BaseAnalyzer` for the ``liquid_funds`` profile.
Delegates to DDReportEngine (dd_report/ package) for chapter generation
and QuantAnalyzer for portfolio-level quant analysis.

Config is resolved via :class:`ConfigService` — never reads YAML directly.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from vertical_engines.base.base_analyzer import BaseAnalyzer

logger = structlog.get_logger()


class FundAnalyzer(BaseAnalyzer):
    """Wealth Management fund analyzer — implements BaseAnalyzer."""

    vertical = "liquid_funds"

    def run_deal_analysis(
        self,
        db: Session,
        *,
        instrument_id: str,
        deal_id: str,
        actor_id: str,
        force: bool = False,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run fund manager DD report (8-chapter analysis).

        In wealth context:
          - instrument_id = org fund context (the Netz fund performing evaluation)
          - deal_id = target fund being evaluated
        """
        from vertical_engines.wealth.dd_report import DDReportEngine

        engine = DDReportEngine(config=config)
        result = engine.generate(
            db,
            instrument_id=deal_id,  # Target fund being evaluated
            actor_id=actor_id,
            organization_id=instrument_id,  # Org context
            force=force,
        )
        # Convert frozen dataclass to dict for BaseAnalyzer interface
        return {
            "instrument_id": result.fund_id,
            "status": result.status,
            "confidence_score": result.confidence_score,
            "decision_anchor": result.decision_anchor,
            "chapters": [
                {
                    "tag": ch.tag,
                    "title": ch.title,
                    "status": ch.status,
                    "content_md": ch.content_md,
                    "critic_status": ch.critic_status,
                }
                for ch in result.chapters
            ],
            "error": result.error,
        }

    def run_portfolio_analysis(
        self,
        db: Session,
        *,
        instrument_id: str,
        actor_id: str,
        as_of: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run portfolio-level quant analysis (CVaR, drift, scoring)."""
        from vertical_engines.wealth.quant_analyzer import QuantAnalyzer

        analyzer = QuantAnalyzer(config=config)
        return analyzer.analyze_portfolio(
            db,
            instrument_id=instrument_id,
            actor_id=actor_id,
            as_of=as_of,
        )

    # run_pipeline_analysis: inherits default from BaseAnalyzer
    # (wealth has no pipeline concept)
