"""Generate preview HTML files for visual validation of Fact Sheet redesign.

Usage:
    cd backend
    python -m scripts.preview_fact_sheet_html [--language en|pt]

Outputs:
    .data/preview_fact_sheet_executive.html
    .data/preview_fact_sheet_institutional.html
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
from vertical_engines.wealth.pdf.templates.fact_sheet_executive import (
    render_fact_sheet_executive,
)
from vertical_engines.wealth.pdf.templates.fact_sheet_institutional import (
    render_fact_sheet_institutional,
)


def _build_mock_data() -> FactSheetData:
    """Build realistic mock data with proper fractional return values."""
    today = date(2026, 3, 28)
    inception = date(2023, 7, 1)

    # --- NAV series (weekly, ~2.7 years) ---
    random.seed(42)
    nav_series: list[NavPoint] = []
    nav = 1.0  # rebased to 1.0
    bench = 1.0
    d = inception
    while d <= today:
        # Simulate realistic weekly returns with slight positive drift
        nav_ret = random.gauss(0.0012, 0.012)
        bm_ret = random.gauss(0.0009, 0.010)
        nav *= 1 + nav_ret
        bench *= 1 + bm_ret
        nav_series.append(
            NavPoint(nav_date=d, nav=round(nav, 6), benchmark_nav=round(bench, 6))
        )
        d += timedelta(days=7)

    # --- Holdings (10 funds — triggers page 2 overflow for executive) ---
    holdings = [
        HoldingRow(fund_name="Vanguard Total Stock Market ETF (VTI)", block_id="us_equity", weight=0.18),
        HoldingRow(fund_name="iShares MSCI ACWI ex US (ACWX)", block_id="intl_equity", weight=0.12),
        HoldingRow(fund_name="PIMCO Income Fund (PONAX)", block_id="fixed_income", weight=0.14),
        HoldingRow(fund_name="DoubleLine Total Return (DBLTX)", block_id="fixed_income", weight=0.08),
        HoldingRow(fund_name="Ares Capital Corporation (ARCC)", block_id="private_credit", weight=0.09),
        HoldingRow(fund_name="Owl Rock Capital (ORCC)", block_id="private_credit", weight=0.06),
        HoldingRow(fund_name="Brookfield Infrastructure (BIP)", block_id="infrastructure", weight=0.08),
        HoldingRow(fund_name="Vanguard Real Estate ETF (VNQ)", block_id="real_assets", weight=0.07),
        HoldingRow(fund_name="BlackRock Strategic Income (BASIX)", block_id="fixed_income", weight=0.10),
        HoldingRow(fund_name="JPMorgan Prime Money Market (JPMXX)", block_id="cash", weight=0.08),
    ]

    allocations = [
        AllocationBlock(block_id="us_equity", weight=0.18),
        AllocationBlock(block_id="intl_equity", weight=0.12),
        AllocationBlock(block_id="fixed_income", weight=0.32),
        AllocationBlock(block_id="private_credit", weight=0.15),
        AllocationBlock(block_id="infrastructure", weight=0.08),
        AllocationBlock(block_id="real_assets", weight=0.07),
        AllocationBlock(block_id="cash", weight=0.08),
    ]

    # --- Attribution (Brinson-Fachler) ---
    attribution = [
        AttributionRow(block_name="US Equity", allocation_effect=0.0045, selection_effect=0.0082, interaction_effect=-0.0012, total_effect=0.0115),
        AttributionRow(block_name="Intl Equity", allocation_effect=-0.0015, selection_effect=0.0030, interaction_effect=0.0005, total_effect=0.0020),
        AttributionRow(block_name="Fixed Income", allocation_effect=0.0018, selection_effect=-0.0008, interaction_effect=0.0002, total_effect=0.0012),
        AttributionRow(block_name="Private Credit", allocation_effect=0.0032, selection_effect=0.0025, interaction_effect=-0.0004, total_effect=0.0053),
        AttributionRow(block_name="Infrastructure", allocation_effect=0.0008, selection_effect=0.0012, interaction_effect=0.0001, total_effect=0.0021),
        AttributionRow(block_name="Real Assets", allocation_effect=-0.0005, selection_effect=0.0003, interaction_effect=0.0000, total_effect=-0.0002),
        AttributionRow(block_name="Cash", allocation_effect=-0.0008, selection_effect=0.0000, interaction_effect=0.0000, total_effect=-0.0008),
    ]

    # --- Stress scenarios ---
    stress = [
        StressRow(name="Global Financial Crisis", start_date=date(2007, 10, 1), end_date=date(2009, 3, 31), portfolio_return=-0.2850, max_drawdown=-0.3420),
        StressRow(name="COVID-19 Crash", start_date=date(2020, 2, 19), end_date=date(2020, 3, 23), portfolio_return=-0.1570, max_drawdown=-0.1890),
        StressRow(name="Taper Tantrum", start_date=date(2013, 5, 22), end_date=date(2013, 9, 5), portfolio_return=-0.0380, max_drawdown=-0.0510),
        StressRow(name="Rate Shock 2022", start_date=date(2022, 1, 1), end_date=date(2022, 10, 12), portfolio_return=-0.1230, max_drawdown=-0.1680),
    ]

    # --- Regime series (aligned to NAV dates) ---
    regimes: list[RegimePoint] = []
    for p in nav_series:
        d = p.nav_date
        if d < date(2024, 9, 1):
            r = "expansion"
        elif d < date(2025, 1, 15):
            r = "contraction"
        elif d < date(2025, 5, 1):
            r = "crisis"
        elif d < date(2025, 8, 1):
            r = "risk_off"
        else:
            r = "expansion"
        regimes.append(RegimePoint(regime_date=d, regime=r))

    # --- Fee drag ---
    fee_drag = {
        "total_instruments": 10,
        "weighted_gross_return": 0.0925,
        "weighted_net_return": 0.0847,
        "weighted_fee_drag_pct": 0.0078,
        "inefficient_count": 2,
        "instruments": [
            {"name": "Vanguard Total Stock (VTI)", "fee_breakdown": {"management": 0.0003, "performance": 0.0, "other": 0.0, "total": 0.0003}, "fee_drag_pct": 0.0003, "fee_efficient": True},
            {"name": "iShares ACWI ex US (ACWX)", "fee_breakdown": {"management": 0.0032, "performance": 0.0, "other": 0.0, "total": 0.0032}, "fee_drag_pct": 0.0035, "fee_efficient": True},
            {"name": "PIMCO Income (PONAX)", "fee_breakdown": {"management": 0.0065, "performance": 0.0, "other": 0.0003, "total": 0.0068}, "fee_drag_pct": 0.0072, "fee_efficient": True},
            {"name": "DoubleLine Total (DBLTX)", "fee_breakdown": {"management": 0.0072, "performance": 0.0, "other": 0.0002, "total": 0.0074}, "fee_drag_pct": 0.0081, "fee_efficient": True},
            {"name": "Ares Capital (ARCC)", "fee_breakdown": {"management": 0.0150, "performance": 0.0200, "other": 0.0015, "total": 0.0365}, "fee_drag_pct": 0.0312, "fee_efficient": False},
            {"name": "Owl Rock Capital (ORCC)", "fee_breakdown": {"management": 0.0140, "performance": 0.0175, "other": 0.0012, "total": 0.0327}, "fee_drag_pct": 0.0285, "fee_efficient": False},
            {"name": "Brookfield Infra (BIP)", "fee_breakdown": {"management": 0.0045, "performance": 0.0, "other": 0.0002, "total": 0.0047}, "fee_drag_pct": 0.0050, "fee_efficient": True},
            {"name": "Vanguard Real Estate (VNQ)", "fee_breakdown": {"management": 0.0012, "performance": 0.0, "other": 0.0, "total": 0.0012}, "fee_drag_pct": 0.0013, "fee_efficient": True},
            {"name": "BlackRock Strategic (BASIX)", "fee_breakdown": {"management": 0.0087, "performance": 0.0, "other": 0.0005, "total": 0.0092}, "fee_drag_pct": 0.0098, "fee_efficient": True},
            {"name": "JPMorgan Prime MM (JPMXX)", "fee_breakdown": {"management": 0.0018, "performance": 0.0, "other": 0.0, "total": 0.0018}, "fee_drag_pct": 0.0020, "fee_efficient": True},
        ],
    }

    # --- Compute realistic returns from NAV series ---
    final_nav = nav_series[-1].nav
    inception_ret = final_nav - 1.0  # fractional return from 1.0 base

    # Find specific period returns
    def _find_nav_at(target: date) -> float:
        closest = min(nav_series, key=lambda p: abs((p.nav_date - target).days))
        return closest.nav

    mtd_start = _find_nav_at(date(2026, 3, 1))
    qtd_start = _find_nav_at(date(2026, 1, 1))
    ytd_start = _find_nav_at(date(2026, 1, 1))
    one_year_start = _find_nav_at(date(2025, 3, 28))

    def _find_bm_at(target: date) -> float:
        closest = min(nav_series, key=lambda p: abs((p.nav_date - target).days))
        return closest.benchmark_nav or 1.0

    final_bm = nav_series[-1].benchmark_nav or 1.0

    return FactSheetData(
        portfolio_id=uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
        portfolio_name="Netz Institutional Growth Allocation",
        profile="growth",
        as_of=today,
        inception_date=inception,
        returns=ReturnMetrics(
            mtd=(final_nav / mtd_start) - 1,
            qtd=(final_nav / qtd_start) - 1,
            ytd=(final_nav / ytd_start) - 1,
            one_year=(final_nav / one_year_start) - 1,
            three_year=None,
            since_inception=inception_ret,
            inception_date=inception,
            is_backtest=True,
        ),
        benchmark_returns=ReturnMetrics(
            mtd=(final_bm / _find_bm_at(date(2026, 3, 1))) - 1,
            qtd=(final_bm / _find_bm_at(date(2026, 1, 1))) - 1,
            ytd=(final_bm / _find_bm_at(date(2026, 1, 1))) - 1,
            one_year=(final_bm / _find_bm_at(date(2025, 3, 28))) - 1,
            three_year=None,
            since_inception=final_bm - 1.0,
        ),
        risk=RiskMetrics(
            annualized_vol=0.1235,
            sharpe=1.28,
            max_drawdown=-0.0845,
            cvar_95=-0.0472,
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
            "overweight to equities given the current expansion regime, while monitoring "
            "potential headwinds from geopolitical risk and central bank policy divergence."
        ),
        benchmark_label="60/40 Blended Composite",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview fact sheet HTML")
    parser.add_argument("--language", choices=["pt", "en"], default="en")
    args = parser.parse_args()

    data = _build_mock_data()
    lang = args.language

    out_dir = Path(__file__).resolve().parent.parent / ".data"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Executive
    exec_html = render_fact_sheet_executive(data, language=lang)
    exec_path = out_dir / f"preview_fact_sheet_executive_{lang}.html"
    exec_path.write_text(exec_html, encoding="utf-8")
    print(f"Executive:     {exec_path}")

    # Institutional
    inst_html = render_fact_sheet_institutional(data, language=lang)
    inst_path = out_dir / f"preview_fact_sheet_institutional_{lang}.html"
    inst_path.write_text(inst_html, encoding="utf-8")
    print(f"Institutional: {inst_path}")

    print("\nOpen in browser to validate visual output.")


if __name__ == "__main__":
    main()
