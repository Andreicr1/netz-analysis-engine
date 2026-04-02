"""Monthly Client Report engine.

Orchestrates:
1. Data loading (ModelPortfolio + track record monthly returns)
2. LLM narrative generation (4 sections)
3. HTML template rendering
4. Playwright PDF conversion

Never-raises: returns None on error.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vertical_engines.wealth.monthly_report.models import (
    AllocationBar,
    HoldingRow,
    MonthlyReportData,
    MonthlyReturnRow,
)
from vertical_engines.wealth.pdf.svg_charts import DrawdownPoint, NavPoint

logger = structlog.get_logger()

BLOCK_COLORS: dict[str, str] = {
    "us_equity": "#185FA5",
    "intl_equity": "#1D9E75",
    "fixed_income": "#639922",
    "private_credit": "#BA7517",
    "cash": "#888780",
    "alternatives": "#7C3AED",
    "real_estate": "#DC2626",
}


class MonthlyReportEngine:
    """Generate Monthly Client Report PDF for a model portfolio."""

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    async def generate(
        self,
        db: AsyncSession,
        *,
        portfolio_id: str,
        organization_id: str,
        as_of: date | None = None,
        language: str = "en",
    ) -> bytes | None:
        """Generate Monthly Client Report. Returns PDF bytes or None on failure."""
        try:
            data = await self._build_data(
                db,
                portfolio_id=portfolio_id,
                organization_id=organization_id,
                as_of=as_of or date.today(),
            )
            from vertical_engines.wealth.pdf.html_renderer import html_to_pdf
            from vertical_engines.wealth.pdf.templates.monthly_client import (
                render_monthly_client,
            )

            html = render_monthly_client(data, language=language)
            return await html_to_pdf(html, print_background=True)
        except Exception:
            logger.exception("monthly_report_failed", portfolio_id=portfolio_id)
            return None

    async def _build_data(
        self,
        db: AsyncSession,
        *,
        portfolio_id: str,
        organization_id: str,
        as_of: date,
    ) -> MonthlyReportData:
        """Load all data for the report."""
        from app.domains.wealth.models.block import AllocationBlock
        from app.domains.wealth.models.model_portfolio import ModelPortfolio
        from app.domains.wealth.models.portfolio import PortfolioSnapshot

        pid = uuid.UUID(portfolio_id)

        # Load portfolio
        mp_result = await db.execute(
            select(ModelPortfolio).where(ModelPortfolio.id == pid),
        )
        portfolio = mp_result.scalar_one_or_none()
        if portfolio is None:
            raise ValueError(f"Model portfolio {portfolio_id} not found")

        fund_selection = portfolio.fund_selection_schema or {}
        funds_data = fund_selection.get("funds", [])

        # Load snapshot
        snap_result = await db.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.profile == portfolio.profile)
            .order_by(PortfolioSnapshot.snapshot_date.desc())
            .limit(1),
        )
        snapshot = snap_result.scalar_one_or_none()

        regime = "expansion"
        volatility_val = None
        sharpe_val = None
        max_dd_val = None
        cvar_val = None

        if snapshot:
            regime = getattr(snapshot, "regime", "expansion") or "expansion"
            volatility_val = getattr(snapshot, "volatility", None)
            sharpe_val = getattr(snapshot, "sharpe", None)
            max_dd_val = getattr(snapshot, "max_drawdown", None)
            cvar_val = getattr(snapshot, "cvar_95", None)

        # Load allocation blocks
        block_result = await db.execute(
            select(AllocationBlock.block_id, AllocationBlock.display_name),
        )
        block_labels = {r[0]: r[1] for r in block_result.all()}

        # Build block weights from funds_data
        block_weights: dict[str, float] = {}
        for f in funds_data:
            bid = f.get("block_id", "other")
            block_weights[bid] = block_weights.get(bid, 0) + f.get("weight", 0)

        # Allocation bars
        allocations = [
            AllocationBar(
                label=block_labels.get(bid, bid),
                weight=w,
                color=BLOCK_COLORS.get(bid, "#6b7280"),
            )
            for bid, w in sorted(block_weights.items(), key=lambda x: x[1], reverse=True)
        ]

        # Build holdings
        all_holdings = [
            HoldingRow(
                fund_name=f.get("fund_name", "Unknown"),
                ticker=f.get("attributes", {}).get("ticker", "—"),
                strategy=block_labels.get(f.get("block_id", ""), f.get("block_id", "")),
                weight=f.get("weight", 0),
                one_year_return=self._safe_float(f.get("attributes", {}).get("one_year_return")),
                expense_ratio=self._safe_float(f.get("attributes", {}).get("expense_ratio_pct")),
                status="Core",
            )
            for f in sorted(funds_data, key=lambda x: x.get("weight", 0), reverse=True)
        ]
        core_holdings = all_holdings[:5]

        # Run backtest for monthly returns + NAV series
        nav_series, monthly_returns, trailing_periods, perf = await self._load_performance(
            db, pid, funds_data, as_of,
        )

        # Drawdown series from NAV
        drawdown_series = self._compute_drawdown_series(nav_series)

        # Stress scenarios placeholder (from snapshot or empty)
        stress_scenarios: list[dict] = []

        # Snapshot KV
        snapshot_kv = {
            "Instruments": str(len(funds_data)),
            "Profile": portfolio.profile.title(),
            "Regime": regime.title(),
            "Benchmark": portfolio.benchmark_composite or "Composite",
        }

        # LLM narratives — gather in parallel, never-raises per section
        manager_note, macro_commentary, activity_intro, forward_pos = (
            await self._generate_narratives(
                portfolio_name=portfolio.display_name or portfolio.profile.title(),
                profile=portfolio.profile,
                regime=regime,
                perf=perf,
                funds_data=funds_data,
                block_labels=block_labels,
            )
        )

        report_month = as_of.strftime("%B %Y")

        return MonthlyReportData(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio.display_name or f"{portfolio.profile.title()} Portfolio",
            profile=portfolio.profile,
            report_month=report_month,
            as_of=as_of,
            regime=regime,
            month_return=perf.get("month", 0.0),
            ytd_return=perf.get("ytd", 0.0),
            inception_return=perf.get("inception", 0.0),
            month_bm_return=perf.get("month_bm", 0.0),
            ytd_bm_return=perf.get("ytd_bm", 0.0),
            inception_bm_return=perf.get("inception_bm", 0.0),
            manager_note=manager_note,
            macro_commentary=macro_commentary,
            portfolio_activity_intro=activity_intro,
            forward_positioning=forward_pos,
            portfolio_activities=[],
            watch_items=[],
            allocations=allocations,
            core_holdings=core_holdings,
            nav_series=nav_series,
            monthly_returns=monthly_returns,
            trailing_periods=trailing_periods,
            attribution_narrative="",
            attribution_rows=[],
            attribution_total={},
            risk_narrative="",
            volatility=volatility_val,
            sharpe=sharpe_val,
            max_drawdown=max_dd_val,
            cvar_95=cvar_val,
            drawdown_series=drawdown_series,
            stress_scenarios=stress_scenarios,
            all_holdings=all_holdings,
            watchpoints=[],
            snapshot_kv=snapshot_kv,
            is_backtest=True,
            language="en",
        )

    async def _load_performance(
        self,
        db: AsyncSession,
        portfolio_id: uuid.UUID,
        funds_data: list[dict],
        as_of: date,
    ) -> tuple[list[NavPoint], list[MonthlyReturnRow], dict, dict]:
        """Load NAV series and compute monthly returns.

        Uses model_portfolio_nav if available, falls back to backtest.
        """
        nav_series: list[NavPoint] = []
        monthly_returns: list[MonthlyReturnRow] = []
        trailing: dict[str, dict] = {}
        perf: dict[str, float] = {
            "month": 0.0, "ytd": 0.0, "inception": 0.0,
            "month_bm": 0.0, "ytd_bm": 0.0, "inception_bm": 0.0,
        }

        try:
            from app.domains.wealth.services.nav_reader import fetch_nav_series

            raw_rows = await fetch_nav_series(db, portfolio_id)

            # Compute composite benchmark NAV for real benchmark returns (G7.6)
            bm_by_date: dict[date, float] = {}
            try:
                from app.domains.wealth.services.benchmark_resolver import (
                    fetch_benchmark_nav_series,
                )
                from quant_engine.benchmark_composite_service import compute_composite_nav

                bm_block_weights, bm_navs = await fetch_benchmark_nav_series(
                    db, portfolio_id,
                )
                if bm_block_weights and bm_navs:
                    composite = compute_composite_nav(bm_block_weights, bm_navs)
                    bm_by_date = {row.nav_date: row.nav for row in composite}
            except Exception:
                logger.warning("monthly_report_benchmark_composite_failed", exc_info=True)

            nav_rows = [
                {"nav_date": r.nav_date, "nav": r.nav, "benchmark_nav": bm_by_date.get(r.nav_date)}
                for r in raw_rows
            ]
            if nav_rows and len(nav_rows) >= 2:
                # Convert to NavPoint series (rebased to 1.0)
                base_nav = nav_rows[0]["nav"]
                if base_nav and base_nav > 0:
                    nav_series = [
                        NavPoint(
                            nav_date=r["nav_date"],
                            portfolio_nav=r["nav"] / base_nav,
                            benchmark_nav=(r.get("benchmark_nav", base_nav) or base_nav) / base_nav,
                        )
                        for r in nav_rows
                    ]

                    # Compute trailing returns
                    if nav_series:
                        last = nav_series[-1]
                        perf["inception"] = last.portfolio_nav - 1.0
                        perf["inception_bm"] = (last.benchmark_nav or 1.0) - 1.0

                        # Monthly: last ~21 trading days
                        if len(nav_series) > 21:
                            m_start = nav_series[-22]
                            perf["month"] = last.portfolio_nav / m_start.portfolio_nav - 1.0
                            if m_start.benchmark_nav and last.benchmark_nav:
                                perf["month_bm"] = last.benchmark_nav / m_start.benchmark_nav - 1.0

                        # YTD: from Jan 1
                        ytd_start = next(
                            (p for p in nav_series if p.nav_date.year == as_of.year),
                            nav_series[0],
                        )
                        perf["ytd"] = last.portfolio_nav / ytd_start.portfolio_nav - 1.0
                        if ytd_start.benchmark_nav and last.benchmark_nav:
                            perf["ytd_bm"] = last.benchmark_nav / ytd_start.benchmark_nav - 1.0

                    # Trailing periods
                    trailing = self._compute_trailing(nav_series, as_of)

                    # Monthly returns table (trailing 12 months)
                    monthly_returns = self._compute_monthly_returns(nav_series, as_of)

        except Exception:
            logger.warning("monthly_report_nav_load_failed", exc_info=True)

        return nav_series, monthly_returns, trailing, perf

    def _compute_trailing(
        self,
        nav_series: list[NavPoint],
        as_of: date,
    ) -> dict[str, dict]:
        """Compute trailing period returns (1M, 3M, YTD, 1Y, ITD)."""
        if not nav_series:
            return {}

        last = nav_series[-1]
        result: dict[str, dict] = {}

        # Helper: find nav closest to target date
        def nav_at(target_date: date) -> NavPoint | None:
            closest = None
            for p in nav_series:
                if p.nav_date <= target_date:
                    closest = p
            return closest

        from dateutil.relativedelta import relativedelta

        periods = {
            "1m": as_of - relativedelta(months=1),
            "3m": as_of - relativedelta(months=3),
            "ytd": date(as_of.year, 1, 1),
            "1y": as_of - relativedelta(years=1),
            "itd": nav_series[0].nav_date,
        }

        for label, start_date in periods.items():
            start_pt = nav_at(start_date)
            if start_pt and start_pt.portfolio_nav > 0:
                p_ret = last.portfolio_nav / start_pt.portfolio_nav - 1.0
                b_ret = None
                if start_pt.benchmark_nav and last.benchmark_nav and start_pt.benchmark_nav > 0:
                    b_ret = last.benchmark_nav / start_pt.benchmark_nav - 1.0
                result[label] = {
                    "portfolio": round(p_ret, 6),
                    "benchmark": round(b_ret, 6) if b_ret is not None else None,
                }

        return result

    def _compute_monthly_returns(
        self,
        nav_series: list[NavPoint],
        as_of: date,
    ) -> list[MonthlyReturnRow]:
        """Compute trailing 12 monthly returns."""
        if len(nav_series) < 22:
            return []

        from dateutil.relativedelta import relativedelta

        rows: list[MonthlyReturnRow] = []
        for i in range(12):
            month_end = as_of - relativedelta(months=i)
            month_start = month_end - relativedelta(months=1)

            start_pt = None
            end_pt = None
            for p in nav_series:
                if p.nav_date <= month_start:
                    start_pt = p
                if p.nav_date <= month_end:
                    end_pt = p

            if start_pt and end_pt and start_pt.portfolio_nav > 0:
                p_ret = end_pt.portfolio_nav / start_pt.portfolio_nav - 1.0
                b_ret = 0.0
                if (
                    start_pt.benchmark_nav
                    and end_pt.benchmark_nav
                    and start_pt.benchmark_nav > 0
                ):
                    b_ret = end_pt.benchmark_nav / start_pt.benchmark_nav - 1.0
                active = (p_ret - b_ret) * 10000  # bps

                label = month_end.strftime("%b '%y") if i > 0 else month_end.strftime("%b")
                rows.append(
                    MonthlyReturnRow(
                        period_label=label,
                        portfolio_return=round(p_ret, 6),
                        benchmark_return=round(b_ret, 6),
                        active_bps=round(active, 1),
                        is_current=(i == 0),
                    )
                )

        rows.reverse()
        return rows

    def _compute_drawdown_series(self, nav_series: list[NavPoint]) -> list[DrawdownPoint]:
        """Compute underwater equity curve from NAV series."""
        if not nav_series:
            return []

        points: list[DrawdownPoint] = []
        peak = nav_series[0].portfolio_nav
        for p in nav_series:
            if p.portfolio_nav > peak:
                peak = p.portfolio_nav
            dd = (p.portfolio_nav / peak - 1.0) if peak > 0 else 0.0
            points.append(DrawdownPoint(dd_date=p.nav_date, drawdown=dd))

        return points

    async def _generate_narratives(
        self,
        *,
        portfolio_name: str,
        profile: str,
        regime: str,
        perf: dict[str, float],
        funds_data: list[dict],
        block_labels: dict[str, str],
    ) -> tuple[str, str, str, str]:
        """Generate 4 narrative sections via LLM. Never-raises per section."""
        # Placeholder narratives — LLM integration deferred to avoid
        # hard dependency on OpenAI in PDF rendering path.
        # Future: asyncio.gather 4 LLM calls.
        month_pct = perf.get("month", 0) * 100
        ytd_pct = perf.get("ytd", 0) * 100
        n_funds = len(funds_data)

        manager_note = (
            f"The {portfolio_name} delivered a {month_pct:+.2f}% return this month, "
            f"bringing year-to-date performance to {ytd_pct:+.2f}%. "
            f"The current regime is characterized as {regime}, and the portfolio "
            f"of {n_funds} instruments remains positioned for this environment. "
            f"We continue to monitor key macro indicators for signs of regime transition."
        )

        macro_commentary = (
            f"Global macro conditions remain consistent with a {regime} regime. "
            f"Central bank policy, inflation dynamics, and employment data continue "
            f"to inform our positioning. Regional divergences persist across US, "
            f"European, and emerging markets."
        )

        activity_intro = (
            "Portfolio activity this month reflected our ongoing assessment of "
            "risk-adjusted opportunities across the investment universe."
        )

        forward_pos = (
            f"Looking ahead, we maintain our {profile} positioning while monitoring "
            f"for potential regime shifts. Key factors under surveillance include "
            f"monetary policy trajectory, credit spreads, and geopolitical developments. "
            f"The portfolio's current construction balances return potential with "
            f"downside protection appropriate for the prevailing environment."
        )

        return manager_note, macro_commentary, activity_intro, forward_pos

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        """Safely convert to float, return None on failure."""
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
