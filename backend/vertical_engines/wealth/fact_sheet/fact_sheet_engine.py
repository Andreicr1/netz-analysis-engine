"""FactSheetEngine — orchestrates data loading and PDF generation.

Renders fact-sheet PDFs via Playwright Chromium (HTML→PDF).
Charts are inline SVG (no matplotlib dependency for rendering).

Usage::

    engine = FactSheetEngine(config=config)
    pdf_buf = engine.generate(
        db,
        portfolio_id=portfolio_id,
        organization_id=org_id,
        format="executive",  # or "institutional"
        language="pt",
    )
"""

from __future__ import annotations

import uuid
from datetime import date
from io import BytesIO
from typing import Any, Literal

import structlog
from sqlalchemy.orm import Session

from vertical_engines.wealth.fact_sheet.i18n import Language
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
        """Generate a fact-sheet PDF via Playwright (sync).

        1. Load portfolio data from DB
        2. Build FactSheetData frozen dataclass
        3. Render HTML template (charts are inline SVG)
        4. Convert HTML→PDF via Playwright sync API
        5. Return BytesIO with PDF content

        Safe to call from ``asyncio.to_thread()`` or pure sync code.

        Returns:
            BytesIO seeked to 0 containing the PDF.

        """
        as_of = as_of or date.today()

        # ── Load data ──────────────────────────────────────────────
        data = self._build_fact_sheet_data(db, portfolio_id, organization_id, as_of, format=format)

        # ── Render HTML ──────────────────────────────────────────
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

        # ── HTML → PDF via Playwright sync ───────────────────────
        from vertical_engines.wealth.pdf.html_renderer import html_to_pdf_sync

        pdf_bytes = html_to_pdf_sync(html_str, print_background=True)
        buf = BytesIO(pdf_bytes)
        buf.seek(0)
        return buf

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

        # Enrich each holding with prospectus stats (1Y return, expense ratio)
        holdings = self._enrich_holdings_with_prospectus(db, funds_data, holdings)

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

    def _enrich_holdings_with_prospectus(
        self,
        db: Session,
        funds_data: list[dict[str, Any]],
        holdings: list[HoldingRow],
    ) -> list[HoldingRow]:
        """Enrich HoldingRow list with prospectus data (1Y return, expense ratio).

        Fetches prospectus stats for each fund that has a sec_cik attribute.
        Never raises — returns original holdings on any failure.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from app.domains.wealth.models.instrument import Instrument
        from vertical_engines.wealth.dd_report.sec_injection import gather_prospectus_stats

        # Build instrument_id → sec_cik map
        instrument_ids = [
            f["instrument_id"] for f in funds_data if f.get("instrument_id")
        ]
        if not instrument_ids:
            return holdings

        try:
            instruments = (
                db.query(Instrument)
                .filter(Instrument.instrument_id.in_(instrument_ids))
                .all()
            )
            cik_map: dict[str, str | None] = {
                str(inst.instrument_id): (inst.attributes or {}).get("sec_cik")
                for inst in instruments
            }
        except Exception:
            logger.warning("fact_sheet_cik_map_failed", exc_info=True)
            return holdings

        # Build fund_name → instrument_id lookup
        name_to_iid: dict[str, str] = {
            f.get("fund_name", ""): f.get("instrument_id", "")
            for f in funds_data
        }

        # Gather prospectus stats for funds with CIKs
        fund_name_to_stats: dict[str, dict[str, Any]] = {}

        def _fetch(fund_name: str, cik: str) -> tuple[str, dict[str, Any]]:
            return fund_name, gather_prospectus_stats(db, fund_cik=cik)

        tasks_to_run: dict[str, str] = {}
        for f in funds_data:
            fname = f.get("fund_name", "")
            iid = f.get("instrument_id", "")
            cik = cik_map.get(iid)
            if cik:
                tasks_to_run[fname] = cik

        if tasks_to_run:
            with ThreadPoolExecutor(max_workers=min(8, len(tasks_to_run))) as pool:
                futures = {
                    pool.submit(_fetch, name, cik): name
                    for name, cik in tasks_to_run.items()
                }
                for future in as_completed(futures):
                    try:
                        name, stats = future.result()
                        if stats.get("prospectus_stats_available"):
                            fund_name_to_stats[name] = stats
                    except Exception:
                        pass

        if not fund_name_to_stats:
            return holdings

        # Rebuild enriched HoldingRow list
        enriched: list[HoldingRow] = []
        for h in holdings:
            stats = fund_name_to_stats.get(h.fund_name, {})
            enriched.append(HoldingRow(
                fund_name=h.fund_name,
                block_id=h.block_id,
                weight=h.weight,
                one_year_return=stats.get("avg_annual_return_1y"),
                expense_ratio=stats.get("expense_ratio_pct"),
                holding_status=h.holding_status,
            ))
        return enriched

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
        template and converts to PDF via Playwright async API.
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
