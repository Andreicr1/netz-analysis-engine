"""PDF rendering orchestrator for Long-Form DD Report.

Responsibilities:
1. Accept LongFormReportResult from LongFormReportEngine
2. Query DB for supplementary data (allocation, attribution, holdings, risk)
3. Build LongFormReportData
4. Render HTML via template
5. Convert HTML→PDF via Playwright
6. Return PDF bytes (caller handles storage upload)

Never-raises: wraps all errors, returns None on failure.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vertical_engines.wealth.long_form_report.models import (
    AllocationItem,
    AttributionItem,
    LongFormReportData,
    LongFormReportResult,
)
from vertical_engines.wealth.pdf.html_renderer import html_to_pdf
from vertical_engines.wealth.pdf.templates.long_form_dd import render_long_form_dd

logger = structlog.get_logger()


class LongFormPDFRenderer:
    """Orchestrate Long-Form DD Report PDF generation."""

    async def render(
        self,
        result: LongFormReportResult,
        *,
        db: AsyncSession,
        organization_id: str,
        language: str = "en",
    ) -> bytes | None:
        """Build PDF bytes from LongFormReportResult.

        Returns raw PDF bytes, or None on failure (never raises).
        """
        try:
            data = await self._build_data(result, db=db, organization_id=organization_id)
            html = render_long_form_dd(data, language=language)
            return await html_to_pdf(html, print_background=True)
        except Exception:
            logger.exception(
                "long_form_pdf_render_failed",
                portfolio_id=result.portfolio_id,
            )
            return None

    async def _build_data(
        self,
        result: LongFormReportResult,
        *,
        db: AsyncSession,
        organization_id: str,
    ) -> LongFormReportData:
        """Build LongFormReportData from DB + LongFormReportResult."""
        from app.domains.wealth.models.allocation import StrategicAllocation
        from app.domains.wealth.models.block import AllocationBlock
        from app.domains.wealth.models.model_portfolio import ModelPortfolio
        from app.domains.wealth.models.portfolio import PortfolioSnapshot

        pid = uuid.UUID(result.portfolio_id)

        # 1. Load ModelPortfolio
        mp_result = await db.execute(
            select(ModelPortfolio).where(ModelPortfolio.id == pid),
        )
        portfolio = mp_result.scalar_one_or_none()
        if portfolio is None:
            raise ValueError(f"Model portfolio {result.portfolio_id} not found")

        fund_selection = portfolio.fund_selection_schema or {}
        funds_data = fund_selection.get("funds", [])

        # 2. Load latest PortfolioSnapshot for CVaR, regime
        snap_result = await db.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.profile == portfolio.profile)
            .order_by(PortfolioSnapshot.snapshot_date.desc())
            .limit(1),
        )
        snapshot = snap_result.scalar_one_or_none()

        regime = "expansion"
        cvar_95 = None
        volatility = None
        sharpe = None
        max_drawdown = None

        if snapshot:
            regime = getattr(snapshot, "regime", "expansion") or "expansion"
            cvar_95 = getattr(snapshot, "cvar_95", None)
            volatility = getattr(snapshot, "volatility", None)
            sharpe = getattr(snapshot, "sharpe", None)
            max_drawdown = getattr(snapshot, "max_drawdown", None)

        # 3. Load StrategicAllocation + AllocationBlocks
        from datetime import date

        as_of = date.today()

        block_result = await db.execute(
            select(AllocationBlock.block_id, AllocationBlock.display_name),
        )
        block_labels = {r[0]: r[1] for r in block_result.all()}

        sa_result = await db.execute(
            select(
                StrategicAllocation.block_id,
                StrategicAllocation.target_weight,
            )
            .where(
                StrategicAllocation.profile == portfolio.profile,
                StrategicAllocation.effective_from <= as_of,
            )
            .where(
                (StrategicAllocation.effective_to.is_(None))
                | (StrategicAllocation.effective_to >= as_of),
            ),
        )
        sa_rows = sa_result.all()
        sa_weights = {r[0]: float(r[1]) for r in sa_rows}

        # Build block weights from funds_data
        block_weights: dict[str, float] = {}
        for f in funds_data:
            bid = f.get("block_id", "other")
            block_weights[bid] = block_weights.get(bid, 0) + f.get("weight", 0)

        allocations = []
        all_blocks = set(list(block_weights.keys()) + list(sa_weights.keys()))
        for bid in sorted(all_blocks):
            pw = block_weights.get(bid, 0.0)
            bw = sa_weights.get(bid, 0.0)
            allocations.append(
                AllocationItem(
                    block_id=bid,
                    block_name=block_labels.get(bid, bid),
                    portfolio_weight=pw,
                    benchmark_weight=bw,
                    active_weight=round(pw - bw, 4),
                )
            )

        # 4. Build attribution from chapter 4 data if available
        attribution: list[AttributionItem] = []
        for ch in result.chapters:
            if ch.tag == "performance_attribution" and ch.content.get("available"):
                for s in ch.content.get("sectors", []):
                    attribution.append(
                        AttributionItem(
                            block_name=s.get("sector", ""),
                            allocation_effect=s.get("allocation_effect", 0),
                            selection_effect=s.get("selection_effect", 0),
                            total_effect=s.get("total_effect", 0),
                        )
                    )
                break

        # 5. Build holdings list
        holdings = [
            {
                "fund_name": f.get("fund_name", "Unknown"),
                "block_id": f.get("block_id", ""),
                "weight": f.get("weight", 0),
                "ticker": f.get("attributes", {}).get("ticker", ""),
            }
            for f in sorted(funds_data, key=lambda x: x.get("weight", 0), reverse=True)
        ]

        # 6. Compute avg expense ratio
        ers = []
        for f in funds_data:
            er = f.get("attributes", {}).get("expense_ratio_pct")
            if er is not None:
                try:
                    ers.append(float(er))
                except (TypeError, ValueError):
                    pass
        avg_er = sum(ers) / len(ers) if ers else None

        # 7. Extract active return from attribution chapter
        active_return_bps = None
        for ch in result.chapters:
            if ch.tag == "performance_attribution" and ch.content.get("available"):
                excess = ch.content.get("total_excess_return")
                if excess is not None:
                    active_return_bps = round(excess * 10000, 1)
                break

        # 8. Build stress from chapter 5 (risk_decomposition) blocks
        stress: list[dict] = []
        for ch in result.chapters:
            if ch.tag == "risk_decomposition" and ch.content.get("available"):
                # Use portfolio-level cvar if available from chapter
                ch_cvar = ch.content.get("portfolio_cvar_95")
                if ch_cvar is not None:
                    cvar_95 = ch_cvar
                break

        return LongFormReportData(
            portfolio_id=result.portfolio_id,
            portfolio_name=portfolio.display_name or f"{portfolio.profile.title()} Portfolio",
            profile=portfolio.profile,
            as_of=as_of,
            regime=regime,
            active_return_bps=active_return_bps,
            cvar_95=cvar_95,
            avg_expense_ratio=avg_er,
            instrument_count=len(funds_data),
            allocations=allocations,
            attribution=attribution,
            chapters=list(result.chapters),
            volatility=volatility,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            stress=stress,
            holdings=holdings,
        )
