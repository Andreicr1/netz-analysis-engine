"""Generate demo PDFs for visual validation of Playwright templates.

Usage:
    python scripts/preview_playwright_pdfs.py

Outputs:
    .data/preview_long_form_dd.pdf
    .data/preview_monthly_client.pdf
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

# Ensure backend/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _build_long_form_data():
    from vertical_engines.wealth.long_form_report.models import (
        AllocationItem,
        AttributionItem,
        ChapterResult,
        LongFormReportData,
    )

    chapters = [
        ChapterResult(
            tag="macro_context",
            order=1,
            title="Macro Context",
            content={
                "global_summary": (
                    "Global economic conditions in Q1 2026 reflect a nuanced landscape. "
                    "The U.S. economy continues to expand at a moderate pace, with GDP growth "
                    "tracking near 2.3% annualized. Labor markets remain tight but are gradually "
                    "rebalancing, with the unemployment rate holding steady at 3.9%. Inflation "
                    "has decelerated meaningfully, with core PCE falling to 2.4% year-over-year, "
                    "providing the Federal Reserve with flexibility to maintain its current pause.\n\n"
                    "European growth has stabilized following a challenging 2025, with the ECB's "
                    "measured easing cycle supporting a recovery in credit conditions. Emerging "
                    "markets present a mixed picture: China's property sector overhang continues "
                    "to weigh on sentiment, while India and Southeast Asia benefit from "
                    "manufacturing diversification trends.\n\n"
                    "Key risks remain centered on geopolitical tensions, particularly in the "
                    "Middle East and their potential impact on energy prices, as well as the "
                    "sustainability of U.S. fiscal deficits given elevated Treasury issuance."
                ),
                "risk_assessment": "Moderate — watching credit spreads and yield curve dynamics.",
            },
        ),
        ChapterResult(
            tag="strategic_allocation",
            order=2,
            title="Strategic Allocation Rationale",
            content={
                "summary": (
                    "The Growth Portfolio's strategic allocation reflects our conviction in "
                    "a late-cycle expansion environment where equity risk premiums remain "
                    "attractive relative to fixed income yields. We maintain a deliberate "
                    "overweight to U.S. equities (+5% vs. benchmark) given superior earnings "
                    "growth expectations, while funding this through an underweight to "
                    "international developed equities.\n\n"
                    "Our fixed income allocation emphasizes shorter duration and higher quality, "
                    "reflecting our view that the yield curve will gradually steepen as the "
                    "Fed navigates its easing cycle. The 10% allocation to private credit "
                    "provides an attractive carry premium and diversification benefit, "
                    "particularly in an environment where traditional credit spreads have "
                    "compressed to historically tight levels.\n\n"
                    "Cash reserves at 5% provide tactical flexibility to capitalize on "
                    "dislocations that may arise from geopolitical or policy surprises."
                ),
                "blocks": [
                    {"block_id": "us_equity", "display_name": "US Equity", "target_weight": 0.35, "rationale": "Overweight — strong earnings cycle"},
                    {"block_id": "intl_equity", "display_name": "International Equity", "target_weight": 0.20, "rationale": "Underweight — valuation gap narrowing"},
                    {"block_id": "fixed_income", "display_name": "Fixed Income", "target_weight": 0.25, "rationale": "Neutral — shorter duration tilt"},
                    {"block_id": "private_credit", "display_name": "Private Credit", "target_weight": 0.10, "rationale": "Carry advantage over public credit"},
                    {"block_id": "cash", "display_name": "Cash & Equivalents", "target_weight": 0.05, "rationale": "Tactical reserve"},
                ],
            },
        ),
        ChapterResult(
            tag="portfolio_composition",
            order=3,
            title="Portfolio Composition & Changes",
            content={
                "summary": (
                    "The portfolio currently holds 8 instruments across 5 allocation blocks. "
                    "During Q1, we executed two notable changes: (1) initiated a position in "
                    "the Vanguard Total International Stock ETF (VXUS) to replace the more "
                    "concentrated iShares MSCI EAFE, improving diversification across emerging "
                    "markets; and (2) trimmed our exposure to the PIMCO Income Fund by 200bps, "
                    "reallocating to shorter-duration Treasury holdings given our view on "
                    "curve steepening.\n\n"
                    "Portfolio turnover for the quarter was 8.2%, consistent with our "
                    "philosophy of low-frequency, high-conviction rebalancing. The weighted "
                    "average expense ratio improved by 3bps to 0.42% following the ETF swap."
                ),
                "total_funds": 8,
                "deltas": [
                    {"block_id": "us_equity", "current_weight": 0.40, "previous_weight": 0.38, "delta": 0.02},
                    {"block_id": "intl_equity", "current_weight": 0.18, "previous_weight": 0.20, "delta": -0.02},
                    {"block_id": "fixed_income", "current_weight": 0.22, "previous_weight": 0.24, "delta": -0.02},
                    {"block_id": "private_credit", "current_weight": 0.12, "previous_weight": 0.10, "delta": 0.02},
                    {"block_id": "cash", "current_weight": 0.08, "previous_weight": 0.08, "delta": 0.0},
                ],
            },
        ),
        ChapterResult(
            tag="performance_attribution",
            order=4,
            title="Performance Attribution",
            content={
                "available": True,
                "summary": (
                    "The portfolio generated a total return of +3.82% in Q1 2026, outperforming "
                    "the blended benchmark by +47bps. Attribution analysis reveals that the "
                    "majority of excess return was driven by selection effects within U.S. equity "
                    "(+32bps), where our overweight to technology and healthcare delivered strong "
                    "alpha. The allocation effect contributed +18bps, primarily from our overweight "
                    "to private credit during a quarter of tightening spreads.\n\n"
                    "Detractors included the international equity sleeve (-8bps selection), "
                    "where our Japan overweight underperformed as the yen strengthened "
                    "unexpectedly. The fixed income allocation was roughly neutral, with "
                    "duration positioning offsetting credit spread compression."
                ),
                "total_excess_return": 0.0047,
                "sectors": [
                    {"sector": "US Equity", "allocation_effect": 0.0012, "selection_effect": 0.0032, "total_effect": 0.0044},
                    {"sector": "Intl Equity", "allocation_effect": -0.0003, "selection_effect": -0.0008, "total_effect": -0.0011},
                    {"sector": "Fixed Income", "allocation_effect": 0.0002, "selection_effect": -0.0001, "total_effect": 0.0001},
                    {"sector": "Private Credit", "allocation_effect": 0.0018, "selection_effect": -0.0005, "total_effect": 0.0013},
                    {"sector": "Cash", "allocation_effect": -0.0002, "selection_effect": 0.0000, "total_effect": -0.0002},
                ],
            },
        ),
        ChapterResult(
            tag="risk_decomposition",
            order=5,
            title="Risk Decomposition",
            content={
                "available": True,
                "summary": (
                    "Portfolio risk metrics remain well within the parameters established "
                    "for the Growth profile. The portfolio's annualized volatility of 11.8% "
                    "sits comfortably below the 14% ceiling, while the Sharpe ratio of 0.92 "
                    "reflects efficient risk utilization. The 95% CVaR of -3.2% indicates "
                    "that in the worst 5% of scenarios, expected daily losses remain moderate "
                    "and manageable.\n\n"
                    "Factor decomposition shows that systematic equity risk accounts for "
                    "approximately 72% of total portfolio variance, with credit spread risk "
                    "contributing 15% and interest rate risk 8%. Idiosyncratic risk is well "
                    "controlled at 5%, reflecting adequate diversification within each block.\n\n"
                    "Maximum drawdown over the trailing 12 months was -6.4%, occurring during "
                    "the August 2025 volatility episode. Recovery time was 34 trading days, "
                    "consistent with the portfolio's design for moderate drawdown resilience."
                ),
                "portfolio_cvar_95": -0.032,
                "portfolio_var_95": -0.021,
                "n_observations": 504,
            },
        ),
        ChapterResult(
            tag="fee_analysis",
            order=6,
            title="Fee Analysis",
            content={
                "available": True,
                "summary": (
                    "The portfolio's weighted average expense ratio stands at 0.42%, "
                    "representing a 3bps improvement from the prior quarter following our "
                    "swap from active international equity to a lower-cost ETF vehicle. "
                    "Total fee drag on the portfolio is estimated at 0.38% annualized, "
                    "which we consider efficient given the inclusion of actively managed "
                    "private credit exposure.\n\n"
                    "At the instrument level, 6 of 8 holdings are classified as fee-efficient "
                    "(fee drag ratio below median for their respective categories). The two "
                    "exceptions are the PIMCO Income Fund (0.72% ER) and the Cliffwater "
                    "Direct Lending Fund (1.85% ER), both of which justify their fee "
                    "premium through meaningful alpha generation and access to illiquidity "
                    "premiums respectively.\n\n"
                    "We continue to monitor fee competitiveness quarterly and will recommend "
                    "substitutions where lower-cost alternatives with comparable risk-return "
                    "profiles become available."
                ),
                "weighted_fee_drag_pct": 0.0038,
                "inefficient_count": 2,
            },
        ),
        ChapterResult(
            tag="per_fund_highlights",
            order=7,
            title="Per-Fund Highlights",
            content={
                "summary": (
                    "Top contributors this quarter include the Vanguard S&P 500 ETF (VOO), "
                    "which benefited from the broad equity rally (+4.8% quarterly return), "
                    "and the Cliffwater Direct Lending Fund, which delivered +2.1% with "
                    "near-zero correlation to equity markets. The T. Rowe Price Blue Chip "
                    "Growth Fund added meaningful alpha through its semiconductor and "
                    "biotech overweights.\n\n"
                    "The primary detractor was the iShares MSCI Japan ETF (EWJ), which "
                    "returned -1.2% as the yen's 3% appreciation eroded dollar-denominated "
                    "returns. We are monitoring the Bank of Japan's policy normalization "
                    "trajectory to assess whether this represents a tactical opportunity "
                    "or a structural headwind requiring position adjustment.\n\n"
                    "New this quarter: VXUS was initiated at a 5% weight to broaden our "
                    "international equity exposure beyond developed markets."
                ),
                "total_funds": 8,
                "newcomers": 1,
                "exits": 1,
                "top_movers": [
                    {"fund_name": "Vanguard S&P 500 ETF", "block_id": "us_equity", "weight": 0.25},
                    {"fund_name": "T. Rowe Price Blue Chip Growth", "block_id": "us_equity", "weight": 0.15},
                    {"fund_name": "Vanguard Total Intl Stock ETF", "block_id": "intl_equity", "weight": 0.18},
                ],
            },
        ),
        ChapterResult(
            tag="forward_outlook",
            order=8,
            title="Forward Outlook",
            content={
                "summary": (
                    "Looking ahead to Q2 2026, we maintain a constructive but watchful stance. "
                    "The earnings cycle remains supportive for equities, with S&P 500 forward "
                    "earnings growth tracking at +9% year-over-year. However, valuations have "
                    "expanded to the upper end of historical ranges, suggesting that the margin "
                    "of safety has narrowed.\n\n"
                    "Key catalysts we are monitoring: (1) the June FOMC meeting, where a rate "
                    "cut is priced at 65% probability — a dovish pivot could provide a tailwind "
                    "to duration exposure; (2) European parliamentary elections and their "
                    "implications for fiscal policy coordination; (3) Chinese property policy "
                    "announcements that could shift emerging market sentiment.\n\n"
                    "Positioning-wise, we are considering: (a) adding a small tactical "
                    "overweight to investment-grade credit if spreads widen by 15-20bps from "
                    "current levels; (b) initiating a hedge via put spreads on the S&P 500 "
                    "as a low-cost portfolio insurance strategy given elevated valuations; "
                    "(c) increasing EM equity exposure by 2-3% if the USD weakens as "
                    "expected under our base case scenario."
                ),
            },
        ),
    ]

    return LongFormReportData(
        portfolio_id="demo-growth-001",
        portfolio_name="Netz Growth Portfolio",
        profile="growth",
        as_of=date(2026, 3, 28),
        regime="expansion",
        active_return_bps=47.0,
        cvar_95=-0.032,
        avg_expense_ratio=0.42,
        instrument_count=8,
        allocations=[
            AllocationItem("us_equity", "US Equity", 0.40, 0.35, 0.05),
            AllocationItem("intl_equity", "International Equity", 0.18, 0.20, -0.02),
            AllocationItem("fixed_income", "Fixed Income", 0.22, 0.25, -0.03),
            AllocationItem("private_credit", "Private Credit", 0.12, 0.10, 0.02),
            AllocationItem("cash", "Cash & Equivalents", 0.08, 0.10, -0.02),
        ],
        attribution=[
            AttributionItem("US Equity", 0.0012, 0.0032, 0.0044),
            AttributionItem("Intl Equity", -0.0003, -0.0008, -0.0011),
            AttributionItem("Fixed Income", 0.0002, -0.0001, 0.0001),
            AttributionItem("Private Credit", 0.0018, -0.0005, 0.0013),
            AttributionItem("Cash", -0.0002, 0.0000, -0.0002),
        ],
        chapters=chapters,
        volatility=0.118,
        sharpe=0.92,
        max_drawdown=-0.064,
        stress=[
            {"name": "GFC Replay", "portfolio_return": -0.284, "max_drawdown": -0.312},
            {"name": "COVID Shock", "portfolio_return": -0.198, "max_drawdown": -0.223},
            {"name": "Taper Tantrum", "portfolio_return": -0.072, "max_drawdown": -0.089},
            {"name": "Rate Shock +200bp", "portfolio_return": -0.115, "max_drawdown": -0.142},
        ],
        holdings=[
            {"fund_name": "Vanguard S&P 500 ETF", "ticker": "VOO", "block_id": "us_equity", "weight": 0.25},
            {"fund_name": "T. Rowe Price Blue Chip Growth", "ticker": "TRBCX", "block_id": "us_equity", "weight": 0.15},
            {"fund_name": "Vanguard Total Intl Stock ETF", "ticker": "VXUS", "block_id": "intl_equity", "weight": 0.18},
            {"fund_name": "PIMCO Income Fund", "ticker": "PONAX", "block_id": "fixed_income", "weight": 0.12},
            {"fund_name": "iShares Core US Aggregate Bond", "ticker": "AGG", "block_id": "fixed_income", "weight": 0.10},
            {"fund_name": "Cliffwater Direct Lending Fund", "ticker": "CDLF", "block_id": "private_credit", "weight": 0.12},
            {"fund_name": "Vanguard Federal Money Market", "ticker": "VMFXX", "block_id": "cash", "weight": 0.05},
            {"fund_name": "Fidelity Govt Money Market", "ticker": "SPAXX", "block_id": "cash", "weight": 0.03},
        ],
    )


def _build_monthly_data():
    from vertical_engines.wealth.monthly_report.models import (
        AllocationBar,
        HoldingRow,
        MonthlyReportData,
        MonthlyReturnRow,
        PortfolioActivity,
        WatchItem,
    )
    from vertical_engines.wealth.pdf.svg_charts import DrawdownPoint, NavPoint

    # Generate 24-month NAV series
    import math

    nav_series = []
    dd_series = []
    base = date(2024, 4, 1)
    peak = 1.0
    for i in range(24):
        m = base.month + i
        y = base.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        d = date(y, m, 1)
        # Simulated portfolio growth with a mid-period dip
        t = i / 23
        p_nav = 1.0 + 0.16 * t - 0.04 * math.sin(math.pi * t * 2)
        b_nav = 1.0 + 0.12 * t - 0.02 * math.sin(math.pi * t * 1.5)
        nav_series.append(NavPoint(nav_date=d, portfolio_nav=round(p_nav, 4), benchmark_nav=round(b_nav, 4)))
        if p_nav > peak:
            peak = p_nav
        dd = p_nav / peak - 1.0
        dd_series.append(DrawdownPoint(dd_date=d, drawdown=round(dd, 4)))

    # Monthly returns (trailing 12)
    monthly_returns = []
    labels = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
    port_rets = [0.012, 0.018, -0.005, 0.022, -0.031, 0.015, 0.028, 0.009, 0.017, 0.024, -0.008, 0.015]
    bench_rets = [0.010, 0.014, -0.003, 0.018, -0.025, 0.012, 0.022, 0.007, 0.014, 0.019, -0.006, 0.012]
    for i, lbl in enumerate(labels):
        suffix = " '25" if i < 9 else ""
        monthly_returns.append(MonthlyReturnRow(
            period_label=f"{lbl}{suffix}",
            portfolio_return=port_rets[i],
            benchmark_return=bench_rets[i],
            active_bps=round((port_rets[i] - bench_rets[i]) * 10000, 1),
            is_current=(i == 11),
        ))

    return MonthlyReportData(
        portfolio_id="demo-moderate-001",
        portfolio_name="Netz Moderate Portfolio",
        profile="moderate",
        report_month="March 2026",
        as_of=date(2026, 3, 28),
        regime="expansion",
        month_return=0.015,
        ytd_return=0.031,
        inception_return=0.128,
        month_bm_return=0.012,
        ytd_bm_return=0.025,
        inception_bm_return=0.098,
        manager_note=(
            "The Moderate Portfolio delivered a solid +1.50% return in March, outpacing "
            "the blended benchmark by 30 basis points. This marks the third consecutive "
            "month of positive active returns, bringing our year-to-date alpha to +60bps.\n\n"
            "The primary driver of outperformance was our overweight to U.S. large-cap "
            "equities, which benefited from a late-quarter rally in technology and healthcare "
            "sectors. Our private credit allocation continued to deliver steady carry with "
            "minimal volatility, contributing meaningfully to risk-adjusted returns.\n\n"
            "Looking ahead, we remain constructive on the portfolio's positioning while "
            "maintaining a watchful eye on credit spreads, which have tightened to levels "
            "that warrant careful monitoring. The current regime remains supportive for "
            "risk assets, but we are preparing contingency playbooks for potential shifts."
        ),
        macro_commentary=(
            "The global macroeconomic backdrop in March was characterized by cautious "
            "optimism. U.S. GDP tracking estimates suggest continued moderate expansion, "
            "while inflation data provided further evidence of gradual disinflation. The "
            "Fed maintained its pause, as expected, with markets pricing approximately "
            "65% probability of a June rate cut.\n\n"
            "In Europe, the ECB's latest meeting signaled continued patience, though "
            "improving PMI data suggests the worst may be behind for the euro area. "
            "Chinese economic data remained mixed, with industrial production surprising "
            "to the upside while property market headwinds persist."
        ),
        portfolio_activity_intro=(
            "Portfolio activity in March was modest, reflecting our conviction in "
            "current positioning rather than a need for significant tactical shifts."
        ),
        forward_positioning=(
            "Our forward positioning balances continued exposure to the equity risk premium "
            "with enhanced downside protection through our fixed income and private credit "
            "allocations. We are actively evaluating opportunities in investment-grade credit "
            "should spreads widen from current levels.\n\n"
            "The portfolio's duration positioning remains short relative to benchmark, "
            "reflecting our expectation for gradual yield curve steepening as the Fed "
            "navigates its easing cycle. We view the current cash allocation as tactical "
            "dry powder rather than a structural position.\n\n"
            "Key watchpoints for Q2 include the June FOMC decision, European elections, "
            "and the trajectory of U.S. corporate earnings. We stand ready to adjust "
            "positioning swiftly if any of these catalysts trigger a regime shift."
        ),
        portfolio_activities=[
            PortfolioActivity(
                ticker="VXUS",
                action="Added",
                narrative="Initiated 5% position for broader EM diversification",
            ),
            PortfolioActivity(
                ticker="PONAX",
                action="Trimmed",
                narrative="Reduced by 200bps; reallocated to shorter-duration Treasuries",
            ),
        ],
        watch_items=[
            WatchItem(text="Credit spreads near historic tights — monitor for reversal", urgency="monitor"),
            WatchItem(text="Japan yen strength impacting intl equity returns", urgency="monitor"),
            WatchItem(text="Q2 earnings season consensus tracking +9% YoY", urgency="track"),
        ],
        allocations=[
            AllocationBar(label="US Equity", weight=0.35, color="#185FA5"),
            AllocationBar(label="Intl Equity", weight=0.18, color="#1D9E75"),
            AllocationBar(label="Fixed Income", weight=0.25, color="#639922"),
            AllocationBar(label="Private Credit", weight=0.12, color="#BA7517"),
            AllocationBar(label="Cash", weight=0.10, color="#888780"),
        ],
        core_holdings=[
            HoldingRow("Vanguard S&P 500 ETF", "VOO", "US Equity", 0.22, 0.148, 0.03, "Core"),
            HoldingRow("T. Rowe Price Blue Chip Growth", "TRBCX", "US Equity", 0.13, 0.162, 0.69, "Core"),
            HoldingRow("Vanguard Total Intl Stock ETF", "VXUS", "Intl Equity", 0.18, 0.085, 0.07, "New"),
            HoldingRow("iShares Core US Agg Bond", "AGG", "Fixed Income", 0.15, 0.032, 0.03, "Core"),
            HoldingRow("PIMCO Income Fund", "PONAX", "Fixed Income", 0.10, 0.058, 0.72, "Reduced"),
        ],
        nav_series=nav_series,
        monthly_returns=monthly_returns,
        trailing_periods={
            "1m": {"portfolio": 0.015, "benchmark": 0.012},
            "3m": {"portfolio": 0.031, "benchmark": 0.025},
            "ytd": {"portfolio": 0.031, "benchmark": 0.025},
            "1y": {"portfolio": 0.118, "benchmark": 0.094},
            "itd": {"portfolio": 0.128, "benchmark": 0.098},
        },
        attribution_narrative=(
            "Brinson-Fachler attribution for March shows that selection effects within "
            "U.S. equities drove the majority of active return (+18bps), followed by a "
            "positive allocation effect from our overweight to private credit (+8bps). "
            "International equity selection was a modest detractor (-5bps) due to yen "
            "strength headwinds in our Japan allocation."
        ),
        attribution_rows=[
            {"block_name": "US Equity", "allocation": 0.0004, "selection": 0.0018, "total": 0.0022},
            {"block_name": "Intl Equity", "allocation": -0.0001, "selection": -0.0005, "total": -0.0006},
            {"block_name": "Fixed Income", "allocation": 0.0001, "selection": 0.0002, "total": 0.0003},
            {"block_name": "Private Credit", "allocation": 0.0008, "selection": 0.0001, "total": 0.0009},
            {"block_name": "Cash", "allocation": -0.0001, "selection": 0.0000, "total": -0.0001},
        ],
        attribution_total={"allocation": 0.0011, "selection": 0.0016, "total": 0.0027},
        risk_narrative=(
            "Portfolio risk metrics remain comfortably within the parameters established "
            "for the Moderate profile. Annualized volatility of 9.4% sits well below the "
            "12% ceiling, while the Sharpe ratio of 1.08 reflects efficient risk utilization. "
            "The drawdown profile shows a maximum peak-to-trough decline of -4.8% over the "
            "trailing 12 months, consistent with the portfolio's moderate risk tolerance."
        ),
        volatility=0.094,
        sharpe=1.08,
        max_drawdown=-0.048,
        cvar_95=-0.024,
        drawdown_series=dd_series,
        stress_scenarios=[
            {"name": "GFC Replay", "portfolio_return": -0.218, "max_drawdown": -0.245},
            {"name": "COVID Shock", "portfolio_return": -0.152, "max_drawdown": -0.178},
            {"name": "Taper Tantrum", "portfolio_return": -0.054, "max_drawdown": -0.068},
            {"name": "Rate Shock +200bp", "portfolio_return": -0.088, "max_drawdown": -0.112},
        ],
        all_holdings=[
            HoldingRow("Vanguard S&P 500 ETF", "VOO", "US Equity", 0.22, 0.148, 0.03, "Core"),
            HoldingRow("T. Rowe Price Blue Chip Growth", "TRBCX", "US Equity", 0.13, 0.162, 0.69, "Core"),
            HoldingRow("Vanguard Total Intl Stock ETF", "VXUS", "Intl Equity", 0.18, 0.085, 0.07, "New"),
            HoldingRow("iShares Core US Agg Bond", "AGG", "Fixed Income", 0.15, 0.032, 0.03, "Core"),
            HoldingRow("PIMCO Income Fund", "PONAX", "Fixed Income", 0.10, 0.058, 0.72, "Reduced"),
            HoldingRow("Cliffwater Direct Lending", "CDLF", "Private Credit", 0.12, 0.092, 1.85, "Core"),
            HoldingRow("Vanguard Federal Money Mkt", "VMFXX", "Cash", 0.06, 0.052, 0.11, "Core"),
            HoldingRow("Fidelity Govt Money Market", "SPAXX", "Cash", 0.04, 0.051, 0.42, "Core"),
        ],
        watchpoints=[
            WatchItem(text="Credit spreads near historic tights — watch for reversal signals", urgency="monitor"),
            WatchItem(text="June FOMC decision — 65% probability of rate cut", urgency="track"),
            WatchItem(text="European elections — potential fiscal policy implications", urgency="track"),
        ],
        snapshot_kv={
            "Instruments": "8",
            "Profile": "Moderate",
            "Benchmark": "60/40 Composite",
            "Inception": "Apr 2024",
            "AUM": "$12.4M",
        },
        is_backtest=True,
        language="en",
    )


async def main():
    out_dir = Path(__file__).resolve().parent.parent / ".data"
    out_dir.mkdir(parents=True, exist_ok=True)

    from vertical_engines.wealth.pdf.html_renderer import html_to_pdf
    from vertical_engines.wealth.pdf.templates.long_form_dd import render_long_form_dd
    from vertical_engines.wealth.pdf.templates.monthly_client import render_monthly_client

    # ── Long-Form DD ──────────────────────────────────────
    print("Building Long-Form DD Report data...")
    lfr_data = _build_long_form_data()

    print("Rendering Long-Form DD HTML...")
    lfr_html = render_long_form_dd(lfr_data, language="en")

    # Save HTML for debugging
    html_path = out_dir / "preview_long_form_dd.html"
    html_path.write_text(lfr_html, encoding="utf-8")
    print(f"  HTML saved: {html_path}")

    print("Converting to PDF via Playwright...")
    lfr_pdf = await html_to_pdf(lfr_html, print_background=True)
    pdf_path = out_dir / "preview_long_form_dd.pdf"
    pdf_path.write_bytes(lfr_pdf)
    print(f"  PDF saved: {pdf_path} ({len(lfr_pdf):,} bytes)")

    # ── Monthly Client Report ─────────────────────────────
    print("\nBuilding Monthly Client Report data...")
    mcr_data = _build_monthly_data()

    print("Rendering Monthly Client Report HTML...")
    mcr_html = render_monthly_client(mcr_data, language="en")

    html_path = out_dir / "preview_monthly_client.html"
    html_path.write_text(mcr_html, encoding="utf-8")
    print(f"  HTML saved: {html_path}")

    print("Converting to PDF via Playwright...")
    mcr_pdf = await html_to_pdf(mcr_html, print_background=True)
    pdf_path = out_dir / "preview_monthly_client.pdf"
    pdf_path.write_bytes(mcr_pdf)
    print(f"  PDF saved: {pdf_path} ({len(mcr_pdf):,} bytes)")

    print("\nDone. Open the PDFs to validate the visual layout.")


if __name__ == "__main__":
    asyncio.run(main())
