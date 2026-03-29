"""Generate a preview institutional fact sheet PDF with mock data.

Usage:
    python -m scripts.preview_fact_sheet [--language en]

Outputs: .data/preview_fact_sheet_institutional.pdf
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vertical_engines.wealth.fact_sheet.chart_builder import (
    render_allocation_pie,
    render_nav_chart,
    render_regime_overlay,
)
from vertical_engines.wealth.fact_sheet.institutional_renderer import (
    render_institutional,
)
from vertical_engines.wealth.fact_sheet.models import (
    AllocationBlock,
    AttributionRow,
    FactSheetData,
    HoldingRow,
    NavPoint,
    RegimePoint,
    ReturnMetrics,
    RiskMetrics,
    StressRow,
)


def _build_mock_data() -> FactSheetData:
    """Build realistic mock data for PDF preview."""
    today = date(2026, 3, 28)
    inception = date(2024, 6, 15)

    # NAV series (weekly, ~2 years)
    nav_series = []
    nav = 1000.0
    bench = 1000.0
    d = inception
    while d <= today:
        nav *= 1.001 + (hash(str(d)) % 100 - 50) / 10000
        bench *= 1.0008 + (hash(str(d) + "b") % 100 - 48) / 10000
        nav_series.append(NavPoint(nav_date=d, nav=round(nav, 2), benchmark_nav=round(bench, 2)))
        d += timedelta(days=7)

    holdings = [
        HoldingRow(fund_name="Vanguard S&P 500 ETF (VOO)", block_id="us_equity", weight=0.25),
        HoldingRow(fund_name="iShares Core MSCI EAFE (IEFA)", block_id="intl_equity", weight=0.15),
        HoldingRow(fund_name="PIMCO Total Return Fund (PTTRX)", block_id="fixed_income", weight=0.20),
        HoldingRow(fund_name="Ares Capital Corp (ARCC)", block_id="private_credit", weight=0.10),
        HoldingRow(fund_name="JPMorgan Prime Money Market (JPMXX)", block_id="cash", weight=0.05),
        HoldingRow(fund_name="BlackRock Strategic Income (BASIX)", block_id="fixed_income", weight=0.10),
        HoldingRow(fund_name="T. Rowe Price Growth Stock (PRGFX)", block_id="us_equity", weight=0.08),
        HoldingRow(fund_name="Fidelity Contrafund (FCNTX)", block_id="us_equity", weight=0.07),
    ]

    allocations = [
        AllocationBlock(block_id="us_equity", weight=0.40),
        AllocationBlock(block_id="intl_equity", weight=0.15),
        AllocationBlock(block_id="fixed_income", weight=0.30),
        AllocationBlock(block_id="private_credit", weight=0.10),
        AllocationBlock(block_id="cash", weight=0.05),
    ]

    attribution = [
        AttributionRow(block_name="US Equity", allocation_effect=0.45, selection_effect=0.82, interaction_effect=-0.12, total_effect=1.15),
        AttributionRow(block_name="Intl Equity", allocation_effect=-0.15, selection_effect=0.30, interaction_effect=0.05, total_effect=0.20),
        AttributionRow(block_name="Fixed Income", allocation_effect=0.10, selection_effect=-0.08, interaction_effect=0.02, total_effect=0.04),
        AttributionRow(block_name="Private Credit", allocation_effect=0.22, selection_effect=0.15, interaction_effect=-0.03, total_effect=0.34),
        AttributionRow(block_name="Cash", allocation_effect=-0.08, selection_effect=0.00, interaction_effect=0.00, total_effect=-0.08),
    ]

    stress = [
        StressRow(name="global_financial_crisis", start_date=date(2007, 10, 1), end_date=date(2009, 3, 31), portfolio_return=-32.5, max_drawdown=-38.2),
        StressRow(name="covid_crash", start_date=date(2020, 2, 19), end_date=date(2020, 3, 23), portfolio_return=-18.7, max_drawdown=-22.4),
        StressRow(name="taper_tantrum", start_date=date(2013, 5, 22), end_date=date(2013, 9, 5), portfolio_return=-4.8, max_drawdown=-6.1),
        StressRow(name="rate_shock_2022", start_date=date(2022, 1, 1), end_date=date(2022, 10, 12), portfolio_return=-15.3, max_drawdown=-19.8),
    ]

    regimes = []
    d = inception
    while d <= today:
        if d < date(2024, 12, 1):
            r = "expansion"
        elif d < date(2025, 4, 1):
            r = "contraction"
        elif d < date(2025, 9, 1):
            r = "crisis"
        else:
            r = "expansion"
        regimes.append(RegimePoint(regime_date=d, regime=r))
        d += timedelta(days=7)

    fee_drag = {
        "total_instruments": 8,
        "weighted_gross_return": 0.0925,
        "weighted_net_return": 0.0847,
        "weighted_fee_drag_pct": 0.0843,
        "inefficient_count": 2,
        "instruments": [
            {"name": "Vanguard S&P 500 ETF (VOO)", "fee_breakdown": {"management": 0.0003, "performance": 0.0, "other": 0.0, "total": 0.0003}, "fee_drag_pct": 0.003, "fee_efficient": True},
            {"name": "iShares Core MSCI EAFE (IEFA)", "fee_breakdown": {"management": 0.0007, "performance": 0.0, "other": 0.0, "total": 0.0007}, "fee_drag_pct": 0.008, "fee_efficient": True},
            {"name": "PIMCO Total Return (PTTRX)", "fee_breakdown": {"management": 0.0071, "performance": 0.0, "other": 0.0002, "total": 0.0073}, "fee_drag_pct": 0.145, "fee_efficient": True},
            {"name": "Ares Capital Corp (ARCC)", "fee_breakdown": {"management": 0.0150, "performance": 0.0200, "other": 0.0015, "total": 0.0365}, "fee_drag_pct": 0.312, "fee_efficient": True},
            {"name": "JPMorgan Prime MM (JPMXX)", "fee_breakdown": {"management": 0.0018, "performance": 0.0, "other": 0.0, "total": 0.0018}, "fee_drag_pct": 0.035, "fee_efficient": True},
            {"name": "BlackRock Strategic (BASIX)", "fee_breakdown": {"management": 0.0087, "performance": 0.0, "other": 0.0005, "total": 0.0092}, "fee_drag_pct": 0.178, "fee_efficient": True},
            {"name": "T. Rowe Price Growth (PRGFX)", "fee_breakdown": {"management": 0.0065, "performance": 0.0, "other": 0.0003, "total": 0.0068}, "fee_drag_pct": 0.520, "fee_efficient": False},
            {"name": "Fidelity Contrafund (FCNTX)", "fee_breakdown": {"management": 0.0082, "performance": 0.0, "other": 0.0004, "total": 0.0086}, "fee_drag_pct": 0.610, "fee_efficient": False},
        ],
    }

    return FactSheetData(
        portfolio_id=uuid.uuid4(),
        portfolio_name="Netz Growth Allocation",
        profile="growth",
        as_of=today,
        inception_date=inception,
        returns=ReturnMetrics(
            mtd=1.23, qtd=3.45, ytd=5.67,
            one_year=9.25, three_year=None,
            since_inception=18.42,
            inception_date=inception, is_backtest=True,
        ),
        benchmark_returns=ReturnMetrics(
            mtd=0.98, qtd=2.87, ytd=4.52,
            one_year=7.80, three_year=None,
            since_inception=14.15,
        ),
        risk=RiskMetrics(
            annualized_vol=12.35, sharpe=1.28,
            max_drawdown=-8.45, cvar_95=-4.72,
        ),
        holdings=holdings,
        allocations=allocations,
        nav_series=nav_series,
        attribution=attribution,
        stress=stress,
        regimes=regimes,
        fee_drag=fee_drag,
        manager_commentary=(
            "The portfolio delivered strong risk-adjusted returns during Q1 2026, "
            "benefiting from US equity momentum and private credit income. Fixed income "
            "allocations provided stability amid rate uncertainty. We maintain a slight "
            "overweight to equities given the current expansion regime."
        ),
        benchmark_label="60/40 Blended",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview fact sheet PDF")
    parser.add_argument("--language", choices=["pt", "en"], default="pt")
    args = parser.parse_args()

    data = _build_mock_data()

    # Render charts
    nav_chart = render_nav_chart(data.nav_series, benchmark_label=data.benchmark_label)
    allocation_chart = render_allocation_pie(data.allocations)
    regime_chart = render_regime_overlay(data.nav_series, data.regimes)

    # Render PDF
    pdf_buf = render_institutional(
        data,
        language=args.language,
        nav_chart=nav_chart,
        allocation_chart=allocation_chart,
        regime_chart=regime_chart,
    )

    out_dir = Path(__file__).resolve().parent.parent / ".data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"preview_fact_sheet_institutional_{args.language}.pdf"
    out_path.write_bytes(pdf_buf.read())
    print(f"PDF saved to: {out_path}")


if __name__ == "__main__":
    main()
