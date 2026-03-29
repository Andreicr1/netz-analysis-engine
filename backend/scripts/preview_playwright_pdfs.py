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
    # Generate 24-month NAV series
    import math

    from vertical_engines.wealth.monthly_report.models import (
        AllocationBar,
        HoldingRow,
        MonthlyReportData,
        MonthlyReturnRow,
        PortfolioActivity,
        WatchItem,
    )
    from vertical_engines.wealth.pdf.svg_charts import DrawdownPoint, NavPoint

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


def _build_fact_sheet_executive_data():
    import uuid

    from vertical_engines.wealth.fact_sheet.models import (
        AllocationBlock,
        FactSheetData,
        HoldingRow,
        NavPoint,
        ReturnMetrics,
        RiskMetrics,
    )

    # 24-month NAV series
    nav_series = []
    for i in range(24):
        m = 4 + i
        y = 2024 + (m - 1) // 12
        m_adj = ((m - 1) % 12) + 1
        t = i / 23
        p_nav = 1.0 + 0.18 * t - 0.03 * __import__("math").sin(__import__("math").pi * t * 2)
        b_nav = 1.0 + 0.14 * t - 0.02 * __import__("math").sin(__import__("math").pi * t * 1.5)
        nav_series.append(NavPoint(
            nav_date=date(y, m_adj, 1),
            nav=round(p_nav, 4),
            benchmark_nav=round(b_nav, 4),
        ))

    return FactSheetData(
        portfolio_id=uuid.uuid4(),
        portfolio_name="Netz Growth Portfolio",
        profile="growth",
        as_of=date(2026, 3, 28),
        inception_date=date(2024, 4, 1),
        returns=ReturnMetrics(
            mtd=0.015, qtd=0.031, ytd=0.042,
            one_year=0.118, three_year=None,
            since_inception=0.245, is_backtest=True,
        ),
        benchmark_returns=ReturnMetrics(
            mtd=0.012, qtd=0.025, ytd=0.035,
            one_year=0.094, three_year=None,
            since_inception=0.198,
        ),
        risk=RiskMetrics(annualized_vol=0.118, sharpe=0.92, max_drawdown=-0.064, cvar_95=-0.032),
        holdings=[
            HoldingRow(fund_name="Vanguard S&P 500 ETF", block_id="us_equity", weight=0.25),
            HoldingRow(fund_name="T. Rowe Price Blue Chip Growth", block_id="us_equity", weight=0.15),
            HoldingRow(fund_name="Vanguard Total Intl Stock ETF", block_id="intl_equity", weight=0.18),
            HoldingRow(fund_name="PIMCO Income Fund", block_id="fixed_income", weight=0.12),
            HoldingRow(fund_name="iShares Core US Aggregate Bond", block_id="fixed_income", weight=0.10),
            HoldingRow(fund_name="Cliffwater Direct Lending Fund", block_id="private_credit", weight=0.12),
            HoldingRow(fund_name="Vanguard Federal Money Market", block_id="cash", weight=0.05),
            HoldingRow(fund_name="Fidelity Govt Money Market", block_id="cash", weight=0.03),
        ],
        allocations=[
            AllocationBlock(block_id="us_equity", weight=0.40),
            AllocationBlock(block_id="intl_equity", weight=0.18),
            AllocationBlock(block_id="fixed_income", weight=0.22),
            AllocationBlock(block_id="private_credit", weight=0.12),
            AllocationBlock(block_id="cash", weight=0.08),
        ],
        nav_series=nav_series,
        benchmark_label="60/40 Composite",
        manager_commentary=(
            "The Growth Portfolio delivered a solid +1.50% return in March, outpacing "
            "the blended benchmark by 30 basis points. The primary driver of outperformance "
            "was our overweight to U.S. large-cap equities. Looking ahead, we remain "
            "constructive while monitoring credit spreads carefully."
        ),
    )


def _build_fact_sheet_institutional_data():
    from vertical_engines.wealth.fact_sheet.models import (
        AttributionRow,
        RegimePoint,
        StressRow,
    )

    data = _build_fact_sheet_executive_data()
    # Institutional adds attribution, stress, regimes, fee_drag
    # Use object.__new__ + manual __init__ since FactSheetData is frozen
    # Instead, rebuild with extra fields
    from vertical_engines.wealth.fact_sheet.models import FactSheetData

    return FactSheetData(
        portfolio_id=data.portfolio_id,
        portfolio_name=data.portfolio_name,
        profile=data.profile,
        as_of=data.as_of,
        inception_date=data.inception_date,
        returns=data.returns,
        benchmark_returns=data.benchmark_returns,
        risk=data.risk,
        holdings=data.holdings,
        allocations=data.allocations,
        nav_series=data.nav_series,
        benchmark_label=data.benchmark_label,
        manager_commentary=data.manager_commentary,
        attribution=[
            AttributionRow("US Equity", 0.0012, 0.0032, 0.0005, 0.0049),
            AttributionRow("Intl Equity", -0.0003, -0.0008, 0.0001, -0.0010),
            AttributionRow("Fixed Income", 0.0002, -0.0001, 0.0000, 0.0001),
            AttributionRow("Private Credit", 0.0018, -0.0005, 0.0002, 0.0015),
            AttributionRow("Cash", -0.0002, 0.0000, 0.0000, -0.0002),
        ],
        stress=[
            StressRow("GFC Replay", date(2008, 9, 1), date(2009, 3, 1), -0.284, -0.312),
            StressRow("COVID Shock", date(2020, 2, 1), date(2020, 4, 1), -0.198, -0.223),
            StressRow("Taper Tantrum", date(2013, 5, 1), date(2013, 9, 1), -0.072, -0.089),
            StressRow("Rate Shock +200bp", date(2022, 1, 1), date(2022, 10, 1), -0.115, -0.142),
        ],
        regimes=[
            RegimePoint(date(2024, 4, 1), "expansion"),
            RegimePoint(date(2025, 8, 1), "contraction"),
            RegimePoint(date(2025, 11, 1), "expansion"),
        ],
        fee_drag={
            "total_instruments": 8,
            "weighted_gross_return": 0.1280,
            "weighted_net_return": 0.1242,
            "weighted_fee_drag_pct": 0.0038,
            "inefficient_count": 2,
            "instruments": [
                {"name": "Vanguard S&P 500 ETF", "fee_breakdown": {"management": 0.0003, "performance": 0.0, "other": 0.0, "total": 0.0003}, "fee_drag_pct": 0.0002, "fee_efficient": True},
                {"name": "T. Rowe Price Blue Chip Growth", "fee_breakdown": {"management": 0.0069, "performance": 0.0, "other": 0.0, "total": 0.0069}, "fee_drag_pct": 0.0058, "fee_efficient": True},
                {"name": "Vanguard Total Intl Stock ETF", "fee_breakdown": {"management": 0.0007, "performance": 0.0, "other": 0.0, "total": 0.0007}, "fee_drag_pct": 0.0005, "fee_efficient": True},
                {"name": "PIMCO Income Fund", "fee_breakdown": {"management": 0.0055, "performance": 0.0017, "other": 0.0, "total": 0.0072}, "fee_drag_pct": 0.0065, "fee_efficient": False},
                {"name": "iShares Core US Aggregate Bond", "fee_breakdown": {"management": 0.0003, "performance": 0.0, "other": 0.0, "total": 0.0003}, "fee_drag_pct": 0.0002, "fee_efficient": True},
                {"name": "Cliffwater Direct Lending", "fee_breakdown": {"management": 0.0150, "performance": 0.0035, "other": 0.0, "total": 0.0185}, "fee_drag_pct": 0.0168, "fee_efficient": False},
                {"name": "Vanguard Federal Money Mkt", "fee_breakdown": {"management": 0.0011, "performance": 0.0, "other": 0.0, "total": 0.0011}, "fee_drag_pct": 0.0008, "fee_efficient": True},
                {"name": "Fidelity Govt Money Market", "fee_breakdown": {"management": 0.0042, "performance": 0.0, "other": 0.0, "total": 0.0042}, "fee_drag_pct": 0.0035, "fee_efficient": True},
            ],
        },
    )


def _build_dd_report_data():
    from vertical_engines.wealth.pdf.templates.dd_report import DDReportPDFData

    chapters = [
        {
            "chapter_tag": "executive_summary",
            "chapter_order": 1,
            "content_md": (
                "## Executive Summary\n\n"
                "The Vanguard S&P 500 ETF (VOO) is a passively managed index fund that "
                "seeks to track the performance of the S&P 500 Index. With over $900 billion "
                "in assets under management, it is one of the largest and most liquid equity "
                "ETFs globally.\n\n"
                "**Key Strengths:**\n\n"
                "- Ultra-low expense ratio of 0.03%, among the lowest in the industry\n"
                "- Exceptional tracking accuracy with minimal tracking error\n"
                "- Deep liquidity with average daily volume exceeding $2 billion\n"
                "- Transparent, rules-based methodology with quarterly rebalancing\n\n"
                "**Areas of Concern:**\n\n"
                "- Market-cap weighting creates concentration risk in mega-cap tech\n"
                "- Top 10 holdings represent approximately 34% of total portfolio weight\n"
                "- No active risk management or downside protection mechanisms\n\n"
                "> The fund's ultra-low expense ratio of 0.03% and exceptional tracking "
                "accuracy position it as the definitive core U.S. equity holding for "
                "institutional portfolios."
            ),
            "evidence_refs": {"SEC Filing": "N-CSR 2025-Q4", "Fund Fact Sheet": "March 2026"},
            "quant_data": {"expense_ratio": "0.03%", "aum": "$912B", "tracking_error": "0.02%"},
            "critic_iterations": 2,
            "critic_status": "accepted",
        },
        {
            "chapter_tag": "investment_strategy",
            "chapter_order": 2,
            "content_md": (
                "## Investment Strategy & Process\n\n"
                "VOO employs a full replication strategy, holding all 503 constituents of the "
                "S&P 500 Index in proportion to their market capitalization weights. The fund "
                "does not engage in securities lending or use derivatives for return enhancement.\n\n"
                "The rebalancing methodology follows S&P Dow Jones Indices' quarterly reconstitution "
                "schedule. Additions and deletions are implemented on the effective date with "
                "minimal market impact due to the fund's scale and Vanguard's sophisticated "
                "transition management capabilities.\n\n"
                "**Sampling approach:** Full replication — no optimization or sampling techniques are "
                "employed, ensuring the highest possible tracking fidelity."
            ),
            "evidence_refs": {},
            "quant_data": {},
            "critic_iterations": 1,
            "critic_status": "accepted",
        },
        {
            "chapter_tag": "manager_assessment",
            "chapter_order": 3,
            "content_md": (
                "## Fund Manager Assessment\n\n"
                "Vanguard Group, founded by John C. Bogle in 1975, is the world's largest "
                "provider of mutual funds and the second-largest provider of exchange-traded "
                "funds. The firm's unique ownership structure — where the funds own the "
                "management company — ensures alignment of interests with investors.\n\n"
                "The Equity Index Group, led by a team of 40+ portfolio managers and analysts, "
                "manages over $5 trillion in indexed equity assets. Key personnel include:\n\n"
                "- **Gerard C. O'Reilly:** Chairman and former CEO of Vanguard\n"
                "- **Michelle Louie:** Head of Equity Index Group\n"
                "- **Walter Nejman:** Senior Portfolio Manager, VOO\n\n"
                "Staff turnover in the indexing team has been minimal, with average tenure "
                "exceeding 12 years."
            ),
            "evidence_refs": {"ADV Part 2": "March 2026", "Team Bio": "Vanguard.com"},
            "quant_data": {},
            "critic_iterations": 2,
            "critic_status": "accepted",
        },
        {
            "chapter_tag": "performance_analysis",
            "chapter_order": 4,
            "content_md": (
                "## Performance Analysis\n\n"
                "VOO has delivered consistent performance closely mirroring the S&P 500 Index "
                "since its inception in September 2010. The annualized tracking difference "
                "of -0.03% precisely matches the fund's expense ratio, indicating zero "
                "slippage from securities lending revenue offsets.\n\n"
                "- **1-Year Return:** +24.8% (benchmark: +24.8%)\n"
                "- **3-Year Annualized:** +9.2% (benchmark: +9.2%)\n"
                "- **5-Year Annualized:** +14.6% (benchmark: +14.6%)\n"
                "- **Since Inception:** +14.1% (benchmark: +14.1%)\n\n"
                "The maximum drawdown of -33.8% occurred during the COVID-19 sell-off "
                "(February-March 2020), with full recovery achieved within 148 trading days."
            ),
            "evidence_refs": {"NAV Data": "Bloomberg Terminal"},
            "quant_data": {"sharpe": "0.92", "max_dd": "-33.8%", "vol": "15.2%"},
            "critic_iterations": 1,
            "critic_status": "accepted",
        },
        {
            "chapter_tag": "risk_framework",
            "chapter_order": 5,
            "content_md": (
                "## Risk Management Framework\n\n"
                "As a passive index fund, VOO's risk management is primarily focused on "
                "tracking accuracy rather than active risk mitigation. The fund's risk profile "
                "is inherently tied to the S&P 500 Index.\n\n"
                "**Concentration Risk:** The top 10 holdings account for 34.2% of the portfolio, "
                "with significant sector concentration in Information Technology (32.1%) and "
                "Healthcare (12.4%). This mega-cap tilt has been both a tailwind (2023-2024) "
                "and a potential vulnerability if sector rotation accelerates.\n\n"
                "**Liquidity Risk:** Minimal. Average daily volume exceeds $2B, with bid-ask "
                "spreads consistently at 1 cent. The creation/redemption mechanism ensures "
                "market price stays within 5bps of NAV."
            ),
            "evidence_refs": {},
            "quant_data": {"beta": "1.00", "r_squared": "0.9999"},
            "critic_iterations": 2,
            "critic_status": "accepted",
        },
        {
            "chapter_tag": "fee_analysis",
            "chapter_order": 6,
            "content_md": (
                "## Fee Analysis\n\n"
                "VOO's expense ratio of 0.03% places it among the lowest-cost equity vehicles "
                "globally. This represents exceptional value for broad U.S. equity exposure.\n\n"
                "**Fee comparison with peers:**\n\n"
                "- VOO (Vanguard): 0.03%\n"
                "- IVV (iShares): 0.03%\n"
                "- SPY (State Street): 0.09%\n"
                "- Average U.S. equity ETF: 0.44%\n\n"
                "The fee advantage compounds significantly over long holding periods. Over 20 years, "
                "the fee drag differential between VOO and the average equity ETF amounts to "
                "approximately 8.5% of total return."
            ),
            "evidence_refs": {},
            "quant_data": {},
            "critic_iterations": 1,
            "critic_status": "accepted",
        },
        {
            "chapter_tag": "operational_dd",
            "chapter_order": 7,
            "content_md": (
                "## Operational Due Diligence\n\n"
                "Vanguard's operational infrastructure is among the most robust in the industry. "
                "The firm's mutual ownership structure eliminates many conflicts of interest "
                "that affect competitor fund families.\n\n"
                "**Custody:** Assets are held by Vanguard's internal transfer agent and custodian, "
                "with Bank of New York Mellon serving as sub-custodian for certain securities.\n\n"
                "**Audit:** PricewaterhouseCoopers serves as the independent auditor. Annual "
                "audits have been unqualified since inception.\n\n"
                "**Regulatory:** Vanguard is registered with the SEC as both an investment "
                "adviser (Form ADV) and as a transfer agent. No material regulatory actions "
                "in the past 10 years."
            ),
            "evidence_refs": {"ADV Part 1": "SEC IAPD"},
            "quant_data": {},
            "critic_iterations": 1,
            "critic_status": "accepted",
        },
        {
            "chapter_tag": "recommendation",
            "chapter_order": 8,
            "content_md": (
                "## Recommendation\n\n"
                "**Decision: APPROVE for inclusion in model portfolios.**\n\n"
                "VOO meets all eliminatory screening criteria and scores favorably across "
                "quantitative and qualitative dimensions. The fund offers:\n\n"
                "- Best-in-class fee efficiency (0.03% ER)\n"
                "- Superior tracking accuracy with negligible tracking error\n"
                "- Deep liquidity suitable for institutional-size positions\n"
                "- Strong operational infrastructure with Vanguard's mutual ownership model\n\n"
                "**Risk considerations:**\n\n"
                "- Concentration risk in mega-cap technology requires monitoring\n"
                "- No active downside protection — complement with hedging strategies\n"
                "- Market-cap weighting may underperform in factor rotation environments\n\n"
                "We recommend a maximum allocation of 25% in growth-oriented portfolios and "
                "20% in moderate profiles, with periodic review of sector concentration dynamics."
            ),
            "evidence_refs": {"Screening": "Layer 1-3 results", "Scoring": "Composite 84/100"},
            "quant_data": {"composite_score": "84", "fee_efficiency": "98", "risk_score": "72"},
            "critic_iterations": 3,
            "critic_status": "accepted",
        },
    ]

    return DDReportPDFData(
        fund_name="Vanguard S&P 500 ETF (VOO)",
        fund_id="demo-voo-001",
        as_of=date(2026, 3, 28),
        confidence_score=0.82,
        decision_anchor="approve",
        chapters=chapters,
        scoring_components={
            "Return Consistency": 88,
            "Risk-Adjusted": 72,
            "Drawdown Control": 65,
            "Information Ratio": 92,
            "Flow Momentum": 78,
        },
        sparkline_data={
            "sharpe": [0.78, 0.82, 0.88, 0.91, 0.85, 0.90, 0.92],
            "max_dd": [-38.0, -25.1, -18.4, -33.8, -12.5, -8.2, -6.4],
            "vol": [18.5, 16.2, 14.8, 22.1, 15.8, 14.2, 15.2],
            "composite_score": [72, 76, 78, 80, 82, 83, 84],
        },
    )


def _build_content_investment_outlook() -> str:
    return (
        "## Global Macro Summary\n\n"
        "The global economy in Q1 2026 reflects a nuanced landscape of moderate expansion "
        "amid residual inflationary pressures. U.S. GDP growth tracks near 2.3% annualized, "
        "supported by resilient consumer spending and a gradual normalization of labor markets. "
        "Core PCE has decelerated to 2.4% year-over-year, providing the Federal Reserve with "
        "flexibility to maintain its current pause.\n\n"
        "European growth has stabilized following a challenging 2025. The ECB's measured easing "
        "cycle is supporting a recovery in credit conditions, though structural headwinds from "
        "energy transition costs and demographic challenges persist.\n\n"
        "## Regional Outlook\n\n"
        "- **United States:** Moderate expansion continues with GDP at 2.3%. Labor markets "
        "rebalancing gradually. Inflation on a clear disinflationary path.\n"
        "- **Europe:** PMI data improving, ECB easing supportive. Watch for political risk "
        "from upcoming elections.\n"
        "- **China:** Property sector overhang weighs on sentiment. Industrial production "
        "surprising to the upside. Policy easing expected to intensify.\n"
        "- **Japan:** BOJ normalization trajectory uncertain. Yen appreciation creating "
        "headwinds for exporters but supporting domestic purchasing power.\n"
        "- **Emerging Markets:** India and Southeast Asia benefit from manufacturing "
        "diversification. Latin America faces commodity price volatility.\n\n"
        "## Asset Class Views\n\n"
        "**Equities:** Constructive but selective. U.S. earnings growth tracking +9% YoY "
        "supports continued equity exposure, but elevated valuations narrow the margin of "
        "safety. Favor quality and profitability factors over pure growth.\n\n"
        "**Fixed Income:** Shorter duration preferred. Yield curve steepening expected as "
        "the Fed navigates its easing cycle. Investment-grade credit attractive on widening.\n\n"
        "**Alternatives:** Private credit continues to offer compelling carry premiums. "
        "Infrastructure benefits from secular trends in energy transition and AI compute.\n\n"
        "## Portfolio Positioning\n\n"
        "Our positioning balances continued equity risk premium exposure with enhanced "
        "downside protection. Key tactical considerations for Q2:\n\n"
        "- Consider adding investment-grade credit if spreads widen 15-20bps\n"
        "- Evaluate protective put spreads on S&P 500 given elevated valuations\n"
        "- Increase EM equity by 2-3% if USD weakens under our base case\n"
        "- Maintain private credit allocation for carry and diversification\n\n"
        "## Key Risks\n\n"
        "- Geopolitical escalation in the Middle East impacting energy prices\n"
        "- U.S. fiscal deficit sustainability given elevated Treasury issuance\n"
        "- Chinese property sector contagion to broader financial system\n"
        "- Unexpected inflation resurgence forcing central bank re-tightening"
    )


def _build_content_flash_report() -> str:
    return (
        "## Market Event\n\n"
        "On March 27, 2026, the Federal Reserve unexpectedly signaled a potential rate "
        "cut at the June FOMC meeting, with Chair Powell citing downside risks to the "
        "labor market outlook. Markets reacted sharply, with the S&P 500 gaining +1.8% "
        "and the 10-year Treasury yield falling 12bps to 3.92%.\n\n"
        "## Market Impact\n\n"
        "**Equities:** Broad-based rally with growth stocks leading. Nasdaq +2.3%, "
        "Russell 2000 +2.8% as rate-sensitive sectors repriced aggressively. Financial "
        "sector underperformed on net interest margin concerns.\n\n"
        "**Fixed Income:** Duration rally across the curve. Investment-grade spreads "
        "tightened 5bps while high-yield compressed 15bps. The 2y/10y spread steepened "
        "8bps to +42bps.\n\n"
        "**Currencies:** USD weakened 0.8% on the DXY index. EUR/USD broke above 1.10 "
        "for the first time since January. EM currencies broadly firmer.\n\n"
        "## Recommended Actions\n\n"
        "- **Maintain current equity positioning** — the dovish pivot supports our "
        "constructive view but avoid chasing the rally\n"
        "- **Extend fixed income duration by 0.5 years** — steepening trade likely "
        "to continue if June cut materializes\n"
        "- **Monitor credit spreads closely** — current tights leave little room for "
        "error; consider adding hedges if HY falls below 280bps\n"
        "- **No immediate EM reallocation** — wait for confirmation of sustained USD "
        "weakness before increasing exposure"
    )


def _build_content_manager_spotlight() -> str:
    return (
        "## Fund Overview\n\n"
        "The Vanguard S&P 500 ETF (VOO) is Vanguard's flagship U.S. equity index fund, "
        "launched in September 2010 as a lower-cost alternative to the State Street SPDR "
        "S&P 500 ETF (SPY). With over $912 billion in assets under management, VOO is "
        "the largest S&P 500 ETF by AUM.\n\n"
        "The fund employs a full replication strategy, holding all 503 constituents of "
        "the S&P 500 Index. Its expense ratio of 0.03% is among the lowest in the "
        "industry, making it a cornerstone holding for institutional and retail portfolios "
        "alike.\n\n"
        "## Investment Strategy\n\n"
        "VOO's strategy is elegantly simple: deliver the S&P 500 return minus the 0.03% "
        "expense ratio. Vanguard achieves this through:\n\n"
        "- **Full replication** — no sampling or optimization, holding all index constituents\n"
        "- **Securities lending revenue** — offsets approximately 0.01% of expenses annually\n"
        "- **Efficient tax management** — ETF structure enables in-kind creation/redemption, "
        "minimizing capital gains distributions\n"
        "- **Scale advantages** — $912B AUM enables sub-basis-point execution costs\n\n"
        "## Performance Assessment\n\n"
        "Trailing performance confirms VOO's exceptional tracking fidelity:\n\n"
        "- 1-Year: +24.8% (tracking difference: -0.03%)\n"
        "- 3-Year Annualized: +9.2% (tracking difference: -0.03%)\n"
        "- 5-Year Annualized: +14.6% (tracking difference: -0.03%)\n"
        "- Since Inception: +14.1% (tracking difference: -0.03%)\n\n"
        "The fund's maximum drawdown of -33.8% during COVID-19 was in line with the "
        "index, with full recovery in 148 trading days. Risk-adjusted metrics remain "
        "strong: Sharpe ratio of 0.92, information ratio effectively zero (by design).\n\n"
        "## Overall Assessment\n\n"
        "> VOO represents the gold standard in passive U.S. equity exposure — its combination "
        "of ultra-low fees, best-in-class tracking, and deep liquidity make it the definitive "
        "core holding for institutional portfolios.\n\n"
        "The fund's unique ownership structure ensures alignment of interests with investors. "
        "The primary risk factor — mega-cap technology concentration — is a feature of the "
        "S&P 500 methodology rather than a fund-specific concern.\n\n"
        "**Recommendation: APPROVE** for inclusion in all model portfolio profiles with a "
        "maximum allocation of 25% for growth-oriented and 20% for moderate profiles."
    )


async def _render_and_save(
    out_dir: Path,
    name: str,
    html_str: str,
) -> None:
    """Save HTML + render PDF for a single template."""
    from vertical_engines.wealth.pdf.html_renderer import html_to_pdf

    html_path = out_dir / f"preview_{name}.html"
    html_path.write_text(html_str, encoding="utf-8")
    print(f"  HTML saved: {html_path}")

    pdf_bytes = await html_to_pdf(html_str, print_background=True)
    pdf_path = out_dir / f"preview_{name}.pdf"
    try:
        pdf_path.write_bytes(pdf_bytes)
    except PermissionError:
        # File may be open in a PDF viewer — write to a timestamped copy
        import time

        ts = int(time.time())
        pdf_path = out_dir / f"preview_{name}_{ts}.pdf"
        pdf_path.write_bytes(pdf_bytes)
    print(f"  PDF saved: {pdf_path} ({len(pdf_bytes):,} bytes)")


async def main():
    out_dir = Path(__file__).resolve().parent.parent / ".data"
    out_dir.mkdir(parents=True, exist_ok=True)

    from vertical_engines.wealth.pdf.templates.long_form_dd import render_long_form_dd
    from vertical_engines.wealth.pdf.templates.monthly_client import render_monthly_client

    # ── 1. Long-Form DD ──────────────────────────────────
    print("1. Long-Form DD Report...")
    lfr_data = _build_long_form_data()
    lfr_html = render_long_form_dd(lfr_data, language="en")
    await _render_and_save(out_dir, "long_form_dd", lfr_html)

    # ── 2. Monthly Client Report ─────────────────────────
    print("\n2. Monthly Client Report...")
    mcr_data = _build_monthly_data()
    mcr_html = render_monthly_client(mcr_data, language="en")
    await _render_and_save(out_dir, "monthly_client", mcr_html)

    # ── 3. Fact Sheet Executive ──────────────────────────
    print("\n3. Fact Sheet Executive...")
    from vertical_engines.wealth.pdf.templates.fact_sheet_executive import (
        render_fact_sheet_executive,
    )

    fse_data = _build_fact_sheet_executive_data()
    fse_html = render_fact_sheet_executive(fse_data, language="en")
    await _render_and_save(out_dir, "fact_sheet_executive", fse_html)

    # ── 4. Fact Sheet Institutional ──────────────────────
    print("\n4. Fact Sheet Institutional...")
    from vertical_engines.wealth.pdf.templates.fact_sheet_institutional import (
        render_fact_sheet_institutional,
    )

    fsi_data = _build_fact_sheet_institutional_data()
    fsi_html = render_fact_sheet_institutional(fsi_data, language="en")
    await _render_and_save(out_dir, "fact_sheet_institutional", fsi_html)

    # ── 5. DD Report ─────────────────────────────────────
    print("\n5. DD Report...")
    from vertical_engines.wealth.pdf.templates.dd_report import render_dd_report

    dd_data = _build_dd_report_data()
    dd_html = render_dd_report(dd_data, language="en")
    await _render_and_save(out_dir, "dd_report", dd_html)

    # ── 6. Content Report — Investment Outlook ───────────
    print("\n6. Content Report — Investment Outlook...")
    from vertical_engines.wealth.pdf.templates.content_report import render_content_report

    io_html = render_content_report(
        _build_content_investment_outlook(),
        title="Investment Outlook",
        language="en",
    )
    await _render_and_save(out_dir, "content_investment_outlook", io_html)

    # ── 7. Content Report — Flash Report ─────────────────
    print("\n7. Content Report — Flash Report...")
    fr_html = render_content_report(
        _build_content_flash_report(),
        title="Market Flash Report",
        language="en",
    )
    await _render_and_save(out_dir, "content_flash_report", fr_html)

    # ── 8. Content Report — Manager Spotlight ────────────
    print("\n8. Content Report — Manager Spotlight...")
    ms_html = render_content_report(
        _build_content_manager_spotlight(),
        title="Manager Spotlight",
        subtitle="Vanguard S&P 500 ETF (VOO)",
        language="en",
        scoring_components={
            "Return Consistency": 88,
            "Risk-Adjusted": 72,
            "Drawdown Control": 65,
            "Information Ratio": 92,
            "Flow Momentum": 78,
            "Fee Efficiency": 98,
        },
    )
    await _render_and_save(out_dir, "content_manager_spotlight", ms_html)

    print("\nAll 8 demos generated. Open the PDFs to validate visual layout.")


if __name__ == "__main__":
    asyncio.run(main())
