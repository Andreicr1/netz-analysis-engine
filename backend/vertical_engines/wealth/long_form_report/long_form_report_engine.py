"""LongFormReportEngine — 8-chapter institutional client report.

Generates a comprehensive report for existing clients combining macro context,
attribution, risk, fees, and fund highlights. Distinct from the FactSheet
(marketing for prospects) and DDReport (fund-level due diligence).

Architecture:
- Chapters 1-8 run in parallel via asyncio.gather (never-raises per chapter)
- Each chapter returns ChapterResult with confidence scoring
- No imports from dd_report/ — separate vertical within wealth engine
- attribution/ and fee_drag/ receive data as arrays/dicts — no I/O

Usage (from async route)::

    engine = LongFormReportEngine(config=config)
    result = await engine.generate(db, portfolio_id=pid, organization_id=org_id)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vertical_engines.wealth.long_form_report.models import (
    CHAPTER_REGISTRY,
    ChapterResult,
    LongFormReportResult,
)

logger = structlog.get_logger()


class LongFormReportEngine:
    """Orchestrate 8-chapter long-form report generation.

    Never raises — returns LongFormReportResult with status='failed' on error.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    async def generate(
        self,
        db: AsyncSession,
        *,
        portfolio_id: str,
        organization_id: str,
        as_of: date | None = None,
    ) -> LongFormReportResult:
        """Generate all 8 chapters in parallel.

        Parameters
        ----------
        db : AsyncSession
            Async database session with RLS context set.
        portfolio_id : str
            Target model portfolio UUID.
        organization_id : str
            Tenant organization ID.
        as_of : date | None
            Report date (defaults to today).

        Returns
        -------
        LongFormReportResult
            Complete report with all chapters (frozen, safe to serialize).

        """
        as_of = as_of or date.today()
        pid = uuid.UUID(portfolio_id)

        try:
            # Pre-load shared data used across chapters
            context = await self._load_context(db, pid, organization_id, as_of)

            if context.get("error"):
                return LongFormReportResult(
                    portfolio_id=portfolio_id,
                    status="failed",
                    error=context["error"],
                )

            # Generate all 8 chapters in parallel
            tasks = [
                self._generate_chapter(ch["tag"], ch["order"], ch["title"], context, db)
                for ch in CHAPTER_REGISTRY
            ]
            chapters = await asyncio.gather(*tasks)

            completed = sum(1 for ch in chapters if ch.status == "completed")
            status = "completed" if completed == len(chapters) else "partial"

            return LongFormReportResult(
                portfolio_id=portfolio_id,
                chapters=list(chapters),
                status=status,
            )

        except Exception as exc:
            logger.exception("long_form_report_failed", portfolio_id=portfolio_id)
            return LongFormReportResult(
                portfolio_id=portfolio_id,
                status="failed",
                error=str(exc),
            )

    async def _load_context(
        self,
        db: AsyncSession,
        portfolio_id: uuid.UUID,
        organization_id: str,
        as_of: date,
    ) -> dict[str, Any]:
        """Pre-load all shared data for chapter generation."""
        from app.domains.wealth.models.allocation import StrategicAllocation
        from app.domains.wealth.models.block import AllocationBlock
        from app.domains.wealth.models.macro_committee import MacroReview
        from app.domains.wealth.models.model_portfolio import ModelPortfolio
        from app.domains.wealth.models.portfolio import PortfolioSnapshot

        # Load portfolio
        result = await db.execute(
            select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
        )
        portfolio = result.scalar_one_or_none()
        if portfolio is None:
            return {"error": f"Model portfolio {portfolio_id} not found"}

        fund_selection = portfolio.fund_selection_schema or {}
        funds_data = fund_selection.get("funds", [])

        # Load latest approved macro review
        macro_stmt = (
            select(MacroReview.report_json, MacroReview.as_of_date)
            .where(MacroReview.status == "approved")
            .order_by(MacroReview.as_of_date.desc())
            .limit(1)
        )
        macro_result = await db.execute(macro_stmt)
        macro_row = macro_result.one_or_none()
        macro_review = {"report": macro_row[0], "as_of": macro_row[1]} if macro_row else None

        # Load strategic allocation
        sa_stmt = (
            select(
                StrategicAllocation.block_id,
                StrategicAllocation.target_weight,
                StrategicAllocation.rationale,
            )
            .where(
                StrategicAllocation.profile == portfolio.profile,
                StrategicAllocation.effective_from <= as_of,
            )
            .where(
                (StrategicAllocation.effective_to.is_(None))
                | (StrategicAllocation.effective_to >= as_of),
            )
        )
        sa_result = await db.execute(sa_stmt)
        strategic_allocations = [
            {"block_id": r[0], "target_weight": float(r[1]), "rationale": r[2]}
            for r in sa_result.all()
        ]

        # Load block labels
        block_result = await db.execute(
            select(AllocationBlock.block_id, AllocationBlock.display_name),
        )
        block_labels = {r[0]: r[1] for r in block_result.all()}

        # Load current and previous portfolio snapshots
        snap_stmt = (
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.profile == portfolio.profile)
            .order_by(PortfolioSnapshot.snapshot_date.desc())
            .limit(2)
        )
        snap_result = await db.execute(snap_stmt)
        snapshots = snap_result.scalars().all()

        current_snapshot = snapshots[0] if snapshots else None
        previous_snapshot = snapshots[1] if len(snapshots) > 1 else None

        # Load benchmark data for attribution
        benchmark_data: dict[str, Any] = {}
        try:
            from app.domains.wealth.services.benchmark_resolver import (
                fetch_benchmark_nav_series,
            )

            block_weights, benchmark_navs = await fetch_benchmark_nav_series(
                db, portfolio_id,
            )
            benchmark_data = {
                "block_weights": block_weights,
                "benchmark_navs": benchmark_navs,
            }
        except Exception:
            logger.warning("long_form_benchmark_load_failed", exc_info=True)

        return {
            "portfolio": portfolio,
            "portfolio_id": portfolio_id,
            "organization_id": organization_id,
            "profile": portfolio.profile,
            "as_of": as_of,
            "funds_data": funds_data,
            "macro_review": macro_review,
            "strategic_allocations": strategic_allocations,
            "block_labels": block_labels,
            "current_snapshot": current_snapshot,
            "previous_snapshot": previous_snapshot,
            "benchmark_data": benchmark_data,
        }

    async def _generate_chapter(
        self,
        tag: str,
        order: int,
        title: str,
        context: dict[str, Any],
        db: AsyncSession,
    ) -> ChapterResult:
        """Generate a single chapter — never raises."""
        try:
            handler = getattr(self, f"_chapter_{tag}", None)
            if handler is None:
                return ChapterResult(
                    tag=tag, order=order, title=title,
                    status="failed", confidence=0.0,
                    error=f"No handler for chapter {tag}",
                )
            content = await handler(context, db)
            return ChapterResult(
                tag=tag, order=order, title=title,
                content=content,
                status="completed",
                confidence=1.0 if content else 0.0,
            )
        except Exception as exc:
            logger.warning(
                "long_form_chapter_failed",
                chapter=tag, error=str(exc), exc_info=True,
            )
            return ChapterResult(
                tag=tag, order=order, title=title,
                status="failed", confidence=0.0,
                error=str(exc),
            )

    # ── Chapter handlers ────────────────────────────────────────────

    async def _chapter_macro_context(
        self, context: dict[str, Any], db: AsyncSession,
    ) -> dict[str, Any]:
        """Ch1: Macro Context — latest approved MacroReview."""
        macro = context.get("macro_review")
        if not macro:
            return {"summary": "No approved macro review available."}
        report = macro["report"]
        return {
            "as_of_date": str(macro["as_of"]),
            "regions": report.get("regions", []),
            "global_summary": report.get("global_summary", ""),
            "risk_assessment": report.get("risk_assessment", ""),
        }

    async def _chapter_strategic_allocation(
        self, context: dict[str, Any], db: AsyncSession,
    ) -> dict[str, Any]:
        """Ch2: Strategic Allocation Rationale."""
        allocations = context.get("strategic_allocations", [])
        labels = context.get("block_labels", {})
        return {
            "profile": context["profile"],
            "blocks": [
                {
                    "block_id": sa["block_id"],
                    "display_name": labels.get(sa["block_id"], sa["block_id"]),
                    "target_weight": sa["target_weight"],
                    "rationale": sa.get("rationale", ""),
                }
                for sa in allocations
            ],
        }

    async def _chapter_portfolio_composition(
        self, context: dict[str, Any], db: AsyncSession,
    ) -> dict[str, Any]:
        """Ch3: Portfolio Composition & Changes — current vs previous snapshot."""
        current = context.get("current_snapshot")
        previous = context.get("previous_snapshot")
        funds_data = context.get("funds_data", [])

        current_weights = current.weights if current else {}
        previous_weights = previous.weights if previous else {}

        # Compute deltas
        all_blocks = set(list(current_weights.keys()) + list(previous_weights.keys()))
        deltas = []
        for block_id in sorted(all_blocks):
            cur_w = float(current_weights.get(block_id, 0))
            prev_w = float(previous_weights.get(block_id, 0))
            deltas.append({
                "block_id": block_id,
                "current_weight": cur_w,
                "previous_weight": prev_w,
                "delta": round(cur_w - prev_w, 4),
            })

        return {
            "current_date": str(current.snapshot_date) if current else None,
            "previous_date": str(previous.snapshot_date) if previous else None,
            "total_funds": len(funds_data),
            "deltas": deltas,
        }

    async def _chapter_performance_attribution(
        self, context: dict[str, Any], db: AsyncSession,
    ) -> dict[str, Any]:
        """Ch4: Performance Attribution — Brinson-Fachler via attribution/service.py."""
        funds_data = context.get("funds_data", [])
        bm_data = context.get("benchmark_data", {})
        sa = context.get("strategic_allocations", [])
        labels = context.get("block_labels", {})

        if not funds_data or not bm_data.get("benchmark_navs"):
            return {"available": False, "reason": "insufficient_data"}

        # Build block weights from funds_data
        block_weights: dict[str, float] = {}
        for f in funds_data:
            bid = f.get("block_id", "other")
            block_weights[bid] = block_weights.get(bid, 0) + f.get("weight", 0)

        # Fund returns by block (expected returns as proxy)
        fund_returns_by_block: dict[str, float] = {}
        for f in funds_data:
            bid = f.get("block_id", "other")
            attrs = f.get("attributes", {})
            er = 0.0
            try:
                er = float(attrs.get("expected_return_pct", 0.0))
            except (TypeError, ValueError):
                pass
            bt = block_weights.get(bid, 0)
            if bt > 0:
                w_in_block = f.get("weight", 0) / bt
                fund_returns_by_block[bid] = fund_returns_by_block.get(bid, 0.0) + w_in_block * er

        # Benchmark returns by block (last month proxy)
        benchmark_returns: dict[str, float] = {}
        for block_id, nav_rows in bm_data["benchmark_navs"].items():
            if nav_rows:
                recent = nav_rows[-min(21, len(nav_rows)):]
                total_r = 1.0
                for row in recent:
                    total_r *= (1.0 + row["return_1d"])
                benchmark_returns[block_id] = total_r - 1.0

        def _run_attribution() -> dict[str, Any]:
            from vertical_engines.wealth.attribution.service import AttributionService

            svc = AttributionService(config=self._config)
            result = svc.compute_portfolio_attribution(
                strategic_allocations=[{"block_id": s["block_id"], "target_weight": s["target_weight"]} for s in sa],
                fund_returns_by_block=fund_returns_by_block,
                benchmark_returns_by_block=benchmark_returns,
                block_labels=labels,
                actual_weights_by_block=block_weights,
            )

            if not result.benchmark_available:
                return {"available": False, "reason": "no_benchmark"}

            return {
                "available": True,
                "total_portfolio_return": result.total_portfolio_return,
                "total_benchmark_return": result.total_benchmark_return,
                "total_excess_return": result.total_excess_return,
                "allocation_total": result.allocation_total,
                "selection_total": result.selection_total,
                "interaction_total": result.interaction_total,
                "sectors": [
                    {
                        "sector": s.sector,
                        "allocation_effect": s.allocation_effect,
                        "selection_effect": s.selection_effect,
                        "interaction_effect": s.interaction_effect,
                        "total_effect": s.total_effect,
                    }
                    for s in result.sectors
                ],
            }

        return await asyncio.to_thread(_run_attribution)

    async def _chapter_risk_decomposition(
        self, context: dict[str, Any], db: AsyncSession,
    ) -> dict[str, Any]:
        """Ch5: Risk Decomposition — CVaR per block via quant_engine."""
        funds_data = context.get("funds_data", [])
        if not funds_data:
            return {"available": False, "reason": "no_funds"}

        from app.domains.wealth.services.nav_reader import fetch_returns_only

        # Compute portfolio-level CVaR
        portfolio_id = context["portfolio_id"]
        try:
            returns = await fetch_returns_only(db, portfolio_id)
            if len(returns) < 30:
                return {"available": False, "reason": "insufficient_data"}
        except Exception:
            return {"available": False, "reason": "nav_read_failed"}

        import numpy as np

        from quant_engine.cvar_service import compute_cvar_from_returns

        returns_arr = np.array(returns)
        cvar_95, var_95 = compute_cvar_from_returns(returns_arr, confidence=0.95)

        # Per-block CVaR
        block_cvar: list[dict[str, Any]] = []
        block_funds: dict[str, list[str]] = {}
        for f in funds_data:
            bid = f.get("block_id", "other")
            iid = f.get("instrument_id")
            if iid:
                block_funds.setdefault(bid, []).append(iid)

        labels = context.get("block_labels", {})
        for bid, fund_ids in block_funds.items():
            block_returns: list[float] = []
            for fid in fund_ids:
                try:
                    fr = await fetch_returns_only(db, uuid.UUID(fid))
                    block_returns.extend(fr)
                except Exception:
                    pass
            if len(block_returns) >= 30:
                br_arr = np.array(block_returns)
                b_cvar, b_var = compute_cvar_from_returns(br_arr, 0.95)
                block_cvar.append({
                    "block_id": bid,
                    "display_name": labels.get(bid, bid),
                    "cvar_95": round(b_cvar, 6),
                    "var_95": round(b_var, 6),
                })

        return {
            "available": True,
            "portfolio_cvar_95": round(cvar_95, 6),
            "portfolio_var_95": round(var_95, 6),
            "n_observations": len(returns),
            "blocks": block_cvar,
        }

    async def _chapter_fee_analysis(
        self, context: dict[str, Any], db: AsyncSession,
    ) -> dict[str, Any]:
        """Ch6: Fee Analysis — fee_drag/service.py."""
        funds_data = context.get("funds_data", [])
        if not funds_data:
            return {"available": False, "reason": "no_funds"}

        def _run_fee_drag() -> dict[str, Any]:
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
                return {"available": False, "reason": "no_instruments"}

            weights = {
                uuid.UUID(f["instrument_id"]): f.get("weight", 0.0)
                for f in funds_data
                if f.get("instrument_id")
            }

            svc = FeeDragService()
            result = svc.compute_portfolio_fee_drag(instruments, weights=weights)

            return {
                "available": True,
                "total_instruments": result.total_instruments,
                "weighted_gross_return": round(result.weighted_gross_return, 4),
                "weighted_net_return": round(result.weighted_net_return, 4),
                "weighted_fee_drag_pct": round(result.weighted_fee_drag_pct, 4),
                "inefficient_count": result.inefficient_count,
                "instruments": [
                    {
                        "name": r.instrument_name,
                        "total_fee_pct": round(r.fee_breakdown.total_fee_pct, 4),
                        "fee_drag_pct": round(r.fee_drag_pct, 4),
                        "fee_efficient": r.fee_efficient,
                    }
                    for r in result.results
                ],
            }

        return await asyncio.to_thread(_run_fee_drag)

    async def _chapter_per_fund_highlights(
        self, context: dict[str, Any], db: AsyncSession,
    ) -> dict[str, Any]:
        """Ch7: Per-Fund Highlights — top movers, newcomers, exits + firm context."""
        funds_data = context.get("funds_data", [])
        current = context.get("current_snapshot")
        previous = context.get("previous_snapshot")

        # Identify current vs previous fund sets
        current_funds = {f.get("instrument_id") for f in funds_data if f.get("instrument_id")}
        prev_fund_selection = (previous.fund_selection or {}) if previous else {}
        prev_funds = {
            f.get("instrument_id")
            for f in prev_fund_selection.get("funds", [])
            if f.get("instrument_id")
        }

        newcomers = current_funds - prev_funds
        exits = prev_funds - current_funds

        # Top movers by weight (descending)
        sorted_funds = sorted(funds_data, key=lambda f: f.get("weight", 0), reverse=True)
        top_movers = [
            {
                "fund_name": f.get("fund_name", "Unknown"),
                "block_id": f.get("block_id", ""),
                "weight": f.get("weight", 0),
            }
            for f in sorted_funds[:5]
        ]

        # ── Vector search: firm context for top movers ────────────────
        fund_highlights: list[dict[str, Any]] = []
        try:
            fund_highlights = await asyncio.to_thread(
                self._search_fund_highlights,
                sorted_funds[:5],
            )
        except Exception:
            logger.warning("long_form_fund_highlights_vector_failed", exc_info=True)

        return {
            "total_funds": len(current_funds),
            "newcomers": len(newcomers),
            "exits": len(exits),
            "top_movers": top_movers,
            "fund_highlights": fund_highlights,
        }

    def _search_fund_highlights(
        self, top_funds: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Sync helper: retrieve firm context chunks for top funds."""
        from ai_engine.extraction.embedding_service import generate_embeddings
        from ai_engine.extraction.pgvector_search_service import (
            search_fund_firm_context_sync,
        )

        query_text = "investment philosophy strategy performance"
        embed_result = generate_embeddings([query_text])
        if not embed_result.vectors:
            return []

        qvec = embed_result.vectors[0]
        highlights: list[dict[str, Any]] = []

        for fund in top_funds:
            attrs = fund.get("attributes", {})
            sec_crd = attrs.get("sec_crd")
            if not sec_crd:
                continue
            chunks = search_fund_firm_context_sync(
                query_vector=qvec,
                sec_crd=sec_crd,
                top=3,
            )
            if chunks:
                highlights.append({
                    "fund_name": fund.get("fund_name", "Unknown"),
                    "chunks": [
                        {"source_type": c.get("source_type", ""), "content": c.get("content", "")[:1000]}
                        for c in chunks[:3]
                    ],
                })

        return highlights

    def _search_macro_review_chunks(
        self, organization_id: str,
    ) -> list[dict[str, Any]]:
        """Sync helper: retrieve macro review chunks from pgvector."""
        from ai_engine.extraction.embedding_service import generate_embeddings
        from ai_engine.extraction.pgvector_search_service import (
            search_fund_analysis_sync,
        )

        query_text = "macro economic outlook forward expectations risks opportunities"
        embed_result = generate_embeddings([query_text])
        if not embed_result.vectors:
            return []
        return search_fund_analysis_sync(
            organization_id=organization_id,
            query_vector=embed_result.vectors[0],
            source_type="macro_review",
            top=10,
        )

    async def _chapter_forward_outlook(
        self, context: dict[str, Any], db: AsyncSession,
    ) -> dict[str, Any]:
        """Ch8: Forward Outlook — from latest InvestmentOutlook + macro review chunks."""
        from app.domains.wealth.models.content import WealthContent

        outlook_content: dict[str, Any] | None = None
        try:
            stmt = (
                select(WealthContent.content_data, WealthContent.approved_at)
                .where(
                    WealthContent.content_type == "investment_outlook",
                    WealthContent.status == "approved",
                )
                .order_by(WealthContent.approved_at.desc())
                .limit(1)
            )
            result = await db.execute(stmt)
            row = result.one_or_none()
            if row and row[0]:
                outlook_content = {
                    "available": True,
                    "published_at": str(row[1]) if row[1] else None,
                    "content": row[0],
                }
        except Exception:
            logger.warning("long_form_outlook_load_failed", exc_info=True)

        # ── Vector search: macro review chunks for forward context ────
        macro_chunks: list[dict[str, Any]] = []
        try:
            organization_id = context.get("organization_id", "")
            if organization_id:
                macro_chunks = await asyncio.to_thread(
                    self._search_macro_review_chunks,
                    organization_id,
                )
        except Exception:
            logger.warning("long_form_outlook_vector_failed", exc_info=True)

        if outlook_content:
            outlook_content["macro_chunks"] = macro_chunks
            return outlook_content

        if macro_chunks:
            return {
                "available": True,
                "source": "vector_search",
                "macro_chunks": macro_chunks,
            }

        return {"available": False, "reason": "no_approved_outlook"}
