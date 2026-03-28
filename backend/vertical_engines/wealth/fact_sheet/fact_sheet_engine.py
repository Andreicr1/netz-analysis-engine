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
    AttributionRow,
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
        data = self._build_fact_sheet_data(db, portfolio_id, organization_id, as_of, format=format)

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
        format: FactSheetFormat = "executive",
    ) -> FactSheetData:
        """Load portfolio + track-record data and build FactSheetData."""
        from sqlalchemy import select

        from app.domains.wealth.models.model_portfolio import ModelPortfolio

        pid = uuid.UUID(portfolio_id)

        result = db.execute(
            select(ModelPortfolio).where(ModelPortfolio.id == pid),
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

        # Institutional-only: attribution and fee_drag
        attribution: list[AttributionRow] = []
        fee_drag_data: dict[str, Any] | None = None
        if format == "institutional":
            attribution = self._compute_attribution(db, pid, funds_data, block_weights)
            fee_drag_data = self._compute_fee_drag(funds_data, block_weights)

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
            attribution=attribution,
            stress=stress,
            fee_drag=fee_drag_data,
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

    def _compute_attribution(
        self,
        db: Session,
        portfolio_id: uuid.UUID,
        funds_data: list[dict[str, Any]],
        block_weights: dict[str, float],
    ) -> list[AttributionRow]:
        """Compute Brinson-Fachler attribution by connecting existing engine."""
        if not funds_data or not block_weights:
            return []

        try:
            from app.domains.wealth.services.benchmark_resolver import (
                fetch_benchmark_nav_series_sync,
            )
            from vertical_engines.wealth.attribution.service import AttributionService

            # Get benchmark data
            sa_block_weights, benchmark_navs = fetch_benchmark_nav_series_sync(
                db, portfolio_id,
            )
            if not benchmark_navs:
                return []

            # Build fund returns by block (weighted average within each block)
            fund_returns_by_block: dict[str, float] = {}
            for f in funds_data:
                bid = f.get("block_id", "other")
                # Use expected_return or fallback to 0
                attrs = f.get("attributes", {})
                expected_return = attrs.get("expected_return_pct", 0.0)
                try:
                    expected_return = float(expected_return)
                except (TypeError, ValueError):
                    expected_return = 0.0
                block_total = block_weights.get(bid, 0)
                if block_total > 0:
                    weight_in_block = f.get("weight", 0) / block_total
                    fund_returns_by_block[bid] = (
                        fund_returns_by_block.get(bid, 0.0)
                        + weight_in_block * expected_return
                    )

            # Build benchmark returns by block (use last available monthly return)
            benchmark_returns_by_block: dict[str, float] = {}
            for block_id, nav_rows in benchmark_navs.items():
                if nav_rows:
                    # Compute total return over last ~21 trading days (monthly proxy)
                    recent = nav_rows[-min(21, len(nav_rows)):]
                    total_r = 1.0
                    for row in recent:
                        total_r *= (1.0 + row["return_1d"])
                    benchmark_returns_by_block[block_id] = total_r - 1.0

            # Build strategic allocations list
            strategic_allocations = [
                {"block_id": bid, "target_weight": w}
                for bid, w in sa_block_weights.items()
            ]

            # Block labels
            from sqlalchemy import select

            from app.domains.wealth.models.block import AllocationBlock as BlockModel
            label_result = db.execute(
                select(BlockModel.block_id, BlockModel.display_name),
            )
            block_labels = {r[0]: r[1] for r in label_result.all()}

            svc = AttributionService(config=self._config)
            result = svc.compute_portfolio_attribution(
                strategic_allocations=strategic_allocations,
                fund_returns_by_block=fund_returns_by_block,
                benchmark_returns_by_block=benchmark_returns_by_block,
                block_labels=block_labels,
                actual_weights_by_block=block_weights,
            )

            if not result.benchmark_available:
                return []

            return [
                AttributionRow(
                    block_name=s.sector,
                    allocation_effect=s.allocation_effect,
                    selection_effect=s.selection_effect,
                    interaction_effect=s.interaction_effect,
                    total_effect=s.total_effect,
                )
                for s in result.sectors
            ]
        except Exception:
            logger.warning("fact_sheet_attribution_failed", exc_info=True)
            return []

    def _compute_fee_drag(
        self,
        funds_data: list[dict[str, Any]],
        block_weights: dict[str, float],
    ) -> dict[str, Any] | None:
        """Compute portfolio fee drag by connecting existing engine."""
        if not funds_data:
            return None

        try:
            from vertical_engines.wealth.fee_drag.service import FeeDragService

            instruments = []
            for f in funds_data:
                iid = f.get("instrument_id")
                if not iid:
                    continue
                instruments.append({
                    "instrument_id": uuid.UUID(iid),
                    "name": f.get("fund_name", "Unknown"),
                    "instrument_type": f.get("instrument_type", "fund"),
                    "attributes": f.get("attributes", {}),
                })

            if not instruments:
                return None

            weights = {
                uuid.UUID(f["instrument_id"]): f.get("weight", 0.0)
                for f in funds_data
                if f.get("instrument_id")
            }

            svc = FeeDragService()
            result = svc.compute_portfolio_fee_drag(instruments, weights=weights)

            return {
                "total_instruments": result.total_instruments,
                "weighted_gross_return": round(result.weighted_gross_return, 4),
                "weighted_net_return": round(result.weighted_net_return, 4),
                "weighted_fee_drag_pct": round(result.weighted_fee_drag_pct, 4),
                "inefficient_count": result.inefficient_count,
                "instruments": [
                    {
                        "name": r.instrument_name,
                        "fee_breakdown": {
                            "management": round(r.fee_breakdown.management_fee_pct, 4),
                            "performance": round(r.fee_breakdown.performance_fee_pct, 4),
                            "other": round(r.fee_breakdown.other_fees_pct, 4),
                            "total": round(r.fee_breakdown.total_fee_pct, 4),
                        },
                        "fee_drag_pct": round(r.fee_drag_pct, 4),
                        "fee_efficient": r.fee_efficient,
                    }
                    for r in result.results
                ],
            }
        except Exception:
            logger.warning("fact_sheet_fee_drag_failed", exc_info=True)
            return None

    async def generate_async(
        self,
        db: Any,
        *,
        portfolio_id: str,
        organization_id: str,
        format: FactSheetFormat = "executive",
        language: Language = "pt",
        as_of: date | None = None,
    ) -> bytes:
        """Generate fact-sheet PDF via Playwright (async). Returns raw PDF bytes.

        Builds FactSheetData in a sync thread (DB queries), then renders HTML
        template and converts to PDF via Playwright Chromium.
        """
        import asyncio

        as_of = as_of or date.today()

        # Build data in sync thread
        def _build() -> FactSheetData:
            from app.core.db.session import sync_session_factory

            with sync_session_factory() as sync_db, sync_db.begin():
                sync_db.expire_on_commit = False
                from sqlalchemy import text
                safe_oid = str(organization_id).replace("'", "")
                sync_db.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
                return self._build_fact_sheet_data(
                    sync_db, portfolio_id, organization_id, as_of, format=format,
                )

        data = await asyncio.to_thread(_build)

        # Render HTML template
        if format == "executive":
            from vertical_engines.wealth.pdf.templates.fact_sheet_executive import (
                render_fact_sheet_executive,
            )
            html_str = render_fact_sheet_executive(data, language=language)
        else:
            from vertical_engines.wealth.pdf.templates.fact_sheet_institutional import (
                render_fact_sheet_institutional,
            )
            html_str = render_fact_sheet_institutional(data, language=language)

        # Convert to PDF
        from vertical_engines.wealth.pdf.html_renderer import html_to_pdf
        return await html_to_pdf(html_str, print_background=True)

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
