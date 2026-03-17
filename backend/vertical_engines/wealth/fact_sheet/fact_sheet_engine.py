"""FactSheetEngine — orchestrates data loading, chart rendering, and PDF generation.

Usage::

    engine = FactSheetEngine(config=config)
    pdf_bytes = engine.generate(
        db,
        portfolio_id=portfolio_id,
        organization_id=org_id,
        format="executive",  # or "institutional"
        language="pt",
    )
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO
from typing import Any, Literal

import structlog
from sqlalchemy.orm import Session

from vertical_engines.wealth.fact_sheet.i18n import LABELS, Language
from vertical_engines.wealth.fact_sheet.models import (
    AllocationBlock,
    FactSheetData,
    HoldingRow,
    ReturnMetrics,
    RiskMetrics,
    StressRow,
)

logger = structlog.get_logger()

FactSheetFormat = Literal["executive", "institutional"]


class FactSheetEngine:
    """Orchestrate fact-sheet PDF generation for model portfolios."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    def generate(
        self,
        db: Session,
        *,
        portfolio_id: str,
        organization_id: str,
        format: FactSheetFormat = "executive",
        language: Language = "pt",
        as_of: date | None = None,
    ) -> BytesIO:
        """Generate a fact-sheet PDF.

        1. Load portfolio data from DB
        2. Build FactSheetData frozen dataclass
        3. Render charts in parallel (ThreadPoolExecutor)
        4. Call appropriate renderer
        5. Return BytesIO with PDF content

        Returns:
            BytesIO seeked to 0 containing the PDF.
        """
        as_of = as_of or date.today()
        labels = LABELS[language]

        # ── Load data ──────────────────────────────────────────────
        data = self._build_fact_sheet_data(db, portfolio_id, organization_id, as_of)

        # ── Render charts in parallel ──────────────────────────────
        charts = self._render_charts(data, language=language, format=format)

        # ── Render PDF ─────────────────────────────────────────────
        if format == "executive":
            from vertical_engines.wealth.fact_sheet.executive_renderer import (
                render_executive,
            )

            return render_executive(
                data,
                language=language,
                nav_chart=charts.get("nav"),
                allocation_chart=charts.get("allocation"),
            )
        else:
            from vertical_engines.wealth.fact_sheet.institutional_renderer import (
                render_institutional,
            )

            return render_institutional(
                data,
                language=language,
                nav_chart=charts.get("nav"),
                allocation_chart=charts.get("allocation"),
                regime_chart=charts.get("regime"),
            )

    def _build_fact_sheet_data(
        self,
        db: Session,
        portfolio_id: str,
        organization_id: str,
        as_of: date,
    ) -> FactSheetData:
        """Load portfolio + track-record data and build FactSheetData."""
        from sqlalchemy import select

        from app.domains.wealth.models.model_portfolio import ModelPortfolio

        pid = uuid.UUID(portfolio_id)

        result = db.execute(
            select(ModelPortfolio).where(ModelPortfolio.id == pid)
        )
        portfolio = result.scalar_one_or_none()
        if portfolio is None:
            raise ValueError(f"Model portfolio {portfolio_id} not found")

        fund_selection = portfolio.fund_selection_schema or {}
        funds_data = fund_selection.get("funds", [])

        # Build holdings
        holdings = [
            HoldingRow(
                fund_name=f.get("fund_name", "Unknown"),
                block_id=f.get("block_id", ""),
                weight=f.get("weight", 0),
            )
            for f in funds_data
        ]
        # Sort by weight desc
        holdings = sorted(holdings, key=lambda h: h.weight, reverse=True)

        # Build allocations (aggregate by block)
        block_weights: dict[str, float] = {}
        for f in funds_data:
            bid = f.get("block_id", "other")
            block_weights[bid] = block_weights.get(bid, 0) + f.get("weight", 0)
        allocations = [
            AllocationBlock(block_id=k, weight=v)
            for k, v in sorted(block_weights.items(), key=lambda x: x[1], reverse=True)
        ]

        # Run backtest once, share result with returns + risk
        backtest_result = self._run_backtest(db, pid, funds_data)

        # Build return metrics from backtest results if available
        returns = self._compute_returns(as_of, backtest_result)
        risk = self._compute_risk(backtest_result)

        # Build stress results
        stress = self._compute_stress(db, pid, funds_data)

        return FactSheetData(
            portfolio_id=pid,
            portfolio_name=portfolio.display_name or f"{portfolio.profile.title()} Portfolio",
            profile=portfolio.profile,
            as_of=as_of,
            inception_date=portfolio.inception_date,
            returns=returns,
            risk=risk,
            holdings=holdings,
            allocations=allocations,
            stress=stress,
            benchmark_label=portfolio.benchmark_composite or "",
        )

    def _run_backtest(
        self,
        db: Session,
        portfolio_id: uuid.UUID,
        funds_data: list[dict[str, Any]],
    ) -> Any | None:
        """Run backtest once and return the result (or None on failure)."""
        if not funds_data:
            return None

        try:
            from vertical_engines.wealth.model_portfolio.track_record import (
                compute_backtest,
            )

            fund_ids = [uuid.UUID(f["instrument_id"]) for f in funds_data]
            weights = [f["weight"] for f in funds_data]
            return compute_backtest(
                db, fund_ids=fund_ids, weights=weights, portfolio_id=portfolio_id,
            )
        except Exception:
            logger.warning("fact_sheet_backtest_failed", exc_info=True)
            return None

    def _compute_returns(
        self,
        as_of: date,
        backtest_result: Any | None,
    ) -> ReturnMetrics:
        """Compute period returns from pre-computed backtest result."""
        if backtest_result is None:
            return ReturnMetrics()

        try:
            return ReturnMetrics(
                since_inception=backtest_result.total_return if hasattr(backtest_result, "total_return") else None,
                is_backtest=True,
                inception_date=backtest_result.inception_date,
            )
        except Exception:
            logger.warning("fact_sheet_returns_failed", exc_info=True)
            return ReturnMetrics(is_backtest=True)

    def _compute_risk(
        self,
        backtest_result: Any | None,
    ) -> RiskMetrics:
        """Extract risk metrics from pre-computed backtest result."""
        if backtest_result is None:
            return RiskMetrics()

        try:
            if backtest_result.folds:
                cvar_vals = [f.cvar_95 for f in backtest_result.folds if f.cvar_95 is not None]
                dd_vals = [f.max_drawdown for f in backtest_result.folds if f.max_drawdown is not None]
                return RiskMetrics(
                    sharpe=backtest_result.mean_sharpe,
                    cvar_95=sum(cvar_vals) / len(cvar_vals) if cvar_vals else None,
                    max_drawdown=min(dd_vals) if dd_vals else None,
                )
        except Exception:
            logger.warning("fact_sheet_risk_failed", exc_info=True)

        return RiskMetrics()

    def _compute_stress(
        self,
        db: Session,
        portfolio_id: uuid.UUID,
        funds_data: list[dict[str, Any]],
    ) -> list[StressRow]:
        """Compute stress scenario results."""
        if not funds_data:
            return []

        try:
            from vertical_engines.wealth.model_portfolio.track_record import (
                compute_stress,
            )

            fund_ids = [uuid.UUID(f["instrument_id"]) for f in funds_data]
            weights = [f["weight"] for f in funds_data]
            result = compute_stress(
                db, fund_ids=fund_ids, weights=weights, portfolio_id=portfolio_id,
            )
            return [
                StressRow(
                    name=s.name,
                    start_date=s.start_date,
                    end_date=s.end_date,
                    portfolio_return=s.portfolio_return,
                    max_drawdown=s.max_drawdown,
                )
                for s in result.scenarios
            ]
        except Exception:
            logger.warning("fact_sheet_stress_failed", exc_info=True)
            return []

    def _render_charts(
        self,
        data: FactSheetData,
        *,
        language: Language,
        format: FactSheetFormat,
    ) -> dict[str, BytesIO]:
        """Render charts in parallel using ThreadPoolExecutor."""
        from vertical_engines.wealth.fact_sheet.chart_builder import (
            render_allocation_pie,
            render_nav_chart,
            render_regime_overlay,
        )

        labels = LABELS[language]
        charts: dict[str, BytesIO] = {}

        # Define chart tasks
        tasks: dict[str, Any] = {}

        if data.nav_series:
            tasks["nav"] = lambda: render_nav_chart(
                data.nav_series,
                title=labels["nav_chart_title"],
                benchmark_label=data.benchmark_label or "Benchmark",
                language=language,
            )

        if data.allocations:
            tasks["allocation"] = lambda: render_allocation_pie(
                data.allocations,
                title=labels["allocation_chart_title"],
            )

        if format == "institutional" and data.nav_series and data.regimes:
            tasks["regime"] = lambda: render_regime_overlay(
                data.nav_series,
                data.regimes,
                title=labels["regime_chart_title"],
            )

        if not tasks:
            return charts

        # Render in parallel
        with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
            futures = {name: pool.submit(fn) for name, fn in tasks.items()}
            for name, future in futures.items():
                try:
                    charts[name] = future.result()
                except Exception:
                    logger.warning("chart_render_failed", chart=name, exc_info=True)

        return charts
