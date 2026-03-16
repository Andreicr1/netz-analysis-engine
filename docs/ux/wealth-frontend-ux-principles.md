# Wealth Frontend — UX Principles & Component Specifications
# Sprint 7 Implementation Guide

**Audience:** Experienced institutional investors, portfolio managers, wealth advisors.
**Standard:** Every screen must meet the bar of a Bloomberg terminal — information-dense,
precise, immediately actionable, never condescending.

---

## Core Philosophy

### 1. Numbers always have context
A number without reference is decoration. Every metric must show:
- **vs. limit** — where it stands relative to its constraint
- **vs. history** — direction (improving/deteriorating) with timeframe
- **vs. peers or benchmark** — relative positioning when applicable

Never show CVaR = -7.2% alone.
Always show CVaR = -7.2% / limit -8.0% / utilization 90% / +0.4pp vs. last week.

### 2. Status before detail
The user opens the dashboard to answer one question: "Do I need to act today?"
Answer that in the first 3 seconds. Detail is one click away — never one scroll away.

### 3. Language of decision, not language of computation
The engine produces `trigger_status = "warning"`.
The UI says "Conservative approaching risk limit — monitor closely."
The engine produces `regime = "RISK_OFF"`.
The UI says "⚠ Stress environment active — defensive positioning in effect."
Never expose internal enum values, internal field names, or raw model outputs.

### 4. Drift history is not optional — it is the audit trail
For institutional users, drift history is how they explain portfolio evolution to
end clients, regulators, and investment committees. It must be:
- Always one click away from any portfolio view
- Complete (no gaps in history)
- Exportable (CSV minimum)
- Timestamped to the day

### 5. Density over whitespace
Users are professionals with limited time. Do not pad with whitespace for aesthetics.
Information density should be high. Use ECharts, compact tables, and collapsible
sections — not large empty cards with one number.

---

## Global UI Rules

### Color system (strict semantic meaning — never decorative)
```
--color-ok:      #22c55e   /* green  — within limits, healthy */
--color-warning: #f59e0b   /* amber  — approaching limit, monitor */
--color-breach:  #ef4444   /* red    — limit breached, action required */
--color-neutral: #6b7280   /* gray   — inactive, historical, reference */
--color-regime-risk-on:    #3b82f6  /* blue  */
--color-regime-risk-off:   #f59e0b  /* amber */
--color-regime-inflation:  #f97316  /* orange */
--color-regime-crisis:     #ef4444  /* red */
```

### Typography rules
- Metric values: `font-variant-numeric: tabular-nums` always — columns must align
- Labels above metrics, not beside them — cleaner scanning
- Percentage changes: always show sign (+/-), always colored (green/red)
- Dates: always show day + month + year — never ambiguous

### Interaction rules
- Hover on any metric → tooltip with full breakdown (how it was calculated)
- Click on any chart element → drilldown (never navigate away, use slide panel)
- All charts: zoom via scroll, pan via drag, reset via double-click
- Tables: click column header to sort, shift-click for secondary sort

---

## View 1: Dashboard (`routes/dashboard/+page.svelte`)

### Layout

```
┌─────────────────────────────────────────────────────────┐
│ REGIME BANNER (full width, conditional)                 │
├─────────────┬─────────────┬─────────────────────────────┤
│  Portfolio  │  Portfolio  │  Portfolio                  │
│  Card:      │  Card:      │  Card:                      │
│  Conservative│ Moderate   │  Growth                     │
├─────────────┴─────────────┴─────────────────────────────┤
│ MACRO INDICATORS BAR (full width, compact)              │
├───────────────────────┬─────────────────────────────────┤
│ ALLOCATION SUMMARY    │  DRIFT ALERTS                   │
│ (top 5 deviations)    │  (blocks out of band)           │
├───────────────────────┴─────────────────────────────────┤
│ ACTIVITY FEED (last 10 events: rebalances, regime       │
│ changes, breach events — with timestamps)               │
└─────────────────────────────────────────────────────────┘
```

### Regime Banner
Appears ONLY when regime ≠ RISK_ON. Full-width, colored background.

```
┌─────────────────────────────────────────────────────────┐
│ ⚠  STRESS ENVIRONMENT ACTIVE  │  VIX 28.4  │  Since    │
│    Defensive positioning in effect for all profiles     │
│    Yield curve: -0.12% (inverted) — recession signal   │
│    [View Macro Detail →]                                │
└─────────────────────────────────────────────────────────┘
```

### Portfolio Card (one per profile: Conservative / Moderate / Growth)

```
┌─────────────────────────────────────┐
│ CONSERVATIVE                 ● OK   │  ← status badge (colored dot + text)
├─────────────────────────────────────┤
│  CVaR (95%, 12m rolling)            │
│  ████████████░░  -7.2% / -8.0%     │  ← progress bar: fill = utilization
│  90% of limit        +0.4pp / 7d   │  ← utilization% + delta vs. 7 days ago
│                                     │
│  Breach in: ~8 days if trend holds  │  ← only shown when status=warning
├─────────────────────────────────────┤
│  Regime:  [● RISK_OFF]              │  ← colored chip
│  Drift:   3 blocks out of band      │  ← count of drifting blocks
│  Updated: today 07:31               │
├─────────────────────────────────────┤
│  [View Portfolio →]  [History →]   │
└─────────────────────────────────────┘
```

**Rules:**
- Card border color = status color (green / amber / red)
- "Breach in N days" computed from rolling trend of CVaR — only shown when
  utilization > 80% and trend is deteriorating
- "History →" button opens drift history panel inline (not new page)

### Macro Indicators Bar (compact, always visible)

```
VIX  28.4 ↑  │  10Y-2Y  -0.12% (inverted)  │  CPI YoY  3.8%  │
Fed Funds  5.25%  │  HY Spread  487bps  │  Updated: today 06:00
```

Each indicator: value + direction arrow + color (neutral when normal, amber/red when
outside threshold). Click any indicator → opens full FRED chart.

### Drift Alerts Panel

Shows only blocks that have exited their strategic bands.

```
DRIFT ALERTS — 3 blocks out of band
────────────────────────────────────────────────────────────
us_equity_broad     ████████████  26.1%  Target 22%  +4.1pp ↑  3d
em_asia_equity      ██░░░░░░░░░░   3.8%  Target  6%  -2.2pp ↓  1d
us_fixed_ig         ████░░░░░░░░  14.2%  Target 18%  -3.8pp ↓  5d

[View Full Allocation →]  [Trigger Rebalance →]
```

**Rules:**
- Duration in band breach always shown (Nd)
- "Trigger Rebalance →" only shown to users with IC role
- Sorted by: breach severity (largest deviation first)

---

## View 2: Portfolio Detail (`routes/portfolio/[profile]/+page.svelte`)

This is the most important view. Three-column FCL layout.

```
┌──────────────────┬────────────────────────────────┬──────────────┐
│  ALLOCATION      │  RISK MONITOR                  │  DRIFT       │
│  BLOCKS          │  (main panel)                  │  HISTORY     │
│  (left nav)      │                                │  (right panel│
│                  │                                │  slide-in)   │
└──────────────────┴────────────────────────────────┴──────────────┘
```

### Left Column: Allocation Blocks Navigator

Compact list of all blocks with visual status:

```
Geography × Asset Class          Weight  Status
─────────────────────────────────────────────────
▶ North America
  US Equity Broad                 26.1%  ↑ OW 4.1pp
  US Equity Growth                 8.2%  ✓ in band
  US Fixed IG                     14.2%  ↓ UW 3.8pp
  US Fixed HY                      3.1%  ✓ in band
▶ Developed Europe
  DM Europe Equity                 7.8%  ✓ in band
...
```

Click any block → highlights it in the main panel and shows its detail.

### Main Panel: Risk Monitor

**Tab 1 — CVaR Timeline (default view)**

ECharts line chart, 12-month history:
- Line: daily CVaR rolling value
- Reference line: limit (dashed red)
- Reference line: warning threshold (dashed amber)
- Background bands: colored by regime (blue=RISK_ON, amber=RISK_OFF, etc.)
- Annotations: rebalance events (vertical lines with label)
- X-axis: dates
- Y-axis: CVaR % (negative values, scale inverted so "worse" is visually up)

Below chart, compact stats row:
```
Current: -7.2%  │  30d min: -7.8%  │  30d avg: -6.9%  │
YTD max breach: 0 days  │  Last rebalance: 2026-02-14
```

**Tab 2 — Allocation Detail**

Full allocation table with all blocks:

```
Block                   Strategic  Current  Deviation  Band      Status
────────────────────────────────────────────────────────────────────────
US Equity Broad         22.0%     26.1%    +4.1pp     17-27%    ↑ OUT
US Fixed IG             18.0%     14.2%    -3.8pp     13-23%    ↓ OUT
US Equity Growth         8.0%      8.2%    +0.2pp      3-13%    ✓
DM Europe Equity         8.0%      7.8%    -0.2pp      3-13%    ✓
EM Asia Equity           6.0%      3.8%    -2.2pp      1-11%    ↓ OUT
...
Cash                     0.0%      1.1%    +1.1pp      0-5%     ✓
────────────────────────────────────────────────────────────────────────
Total                  100.0%    100.0%
```

**Columns are not negotiable — all must be visible.**
Deviation column: positive = overweight (shown in amber if out of band),
negative = underweight. Band column shows [min-max].
Status column: ✓ in band, ↑ OUT overweight, ↓ OUT underweight.

**Tab 3 — Rebalance Proposals**

List of pending and historical rebalances with full before/after.

### Right Panel: Drift History (slide-in, always accessible)

**This panel is ALWAYS one click away from the portfolio view.**
Button "Drift History" fixed in top-right of main panel header.

```
DRIFT HISTORY — Conservative Portfolio
Period: [Last 30d ▾]  Export: [CSV]  [PDF]

────────────────────────────────────────────────────────────────────────
Date        Block              Event                   Deviation
────────────────────────────────────────────────────────────────────────
2026-03-14  US Equity Broad    Entered OUT (OW)        +4.1pp  ↑
2026-03-12  US Fixed IG        Entered OUT (UW)        -3.4pp  ↓
2026-03-10  EM Asia Equity     Entered OUT (UW)        -2.1pp  ↓
2026-02-28  US Equity Broad    Returned to band         +2.1pp  ✓
2026-02-14  [REBALANCE]        Maintenance rebalance    — all blocks reset
2026-02-09  US Fixed HY        Entered OUT (OW)        +1.8pp  ↑
2026-02-09  US Equity Broad    Entered OUT (OW)        +3.2pp  ↑
...
────────────────────────────────────────────────────────────────────────
```

**Rules:**
- Rebalance events shown as full-width rows with distinct styling
- "Entered OUT" and "Returned to band" are distinct event types
- Export must include: date, block, event type, current weight, strategic weight, deviation, days_in_breach
- Default period: last 30 days. Options: 30d, 90d, 180d, 1y, All time
- No pagination — scroll within panel. Maximum 500 rows before requiring filter.

**Drift Timeline Chart (above the table)**

ECharts stacked area / line chart:
- One line per block that has been out of band in the selected period
- X-axis: dates
- Y-axis: deviation from strategic weight (pp)
- Zero line prominent
- Band threshold lines (e.g., ±5%) as dashed reference
- Hover: shows all deviations on that date

---

## View 3: Fund Browser (`routes/funds/+page.svelte`)

Users are selecting funds to fill allocation blocks. They are comparing
dozens of options. The UI must support rapid comparison.

### Filter Bar (always visible, top of page)

```
Block: [All ▾]  Geography: [All ▾]  Asset Class: [All ▾]
Min Score: [0──●──────100]  Max Liquidity: [All ▾]  Min AUM: [Any ▾]
Regime Compatibility: [● Show only compatible with current regime]
Clear filters  │  300 funds shown of 312
```

### Fund Table

Sortable, dense. Default sort: score descending.

```
Fund                    Manager        Score   CVaR 3m  Sharpe 1y  AUM      Liq.  Regime
────────────────────────────────────────────────────────────────────────────────────────────
iShares Core S&P 500   BlackRock      ████ 87  -3.1%    1.24       $450B    D+1   ✓
Vanguard Total Bond    Vanguard       ████ 84  -1.8%    0.91       $320B    D+1   ✓
PIMCO Total Return     PIMCO          ███  76  -2.4%    0.87       $70B     D+3   ✓
iShares MSCI EM        BlackRock      ███  71  -8.2%    0.64       $28B     D+1   ✗ RISK_OFF
Fidelity Contrafund    Fidelity       ███  68  -6.1%    0.79       $140B    D+1   ✓
...
```

**Score column:** visual bar (filled portion = score) + number. Never just a number.
**Regime column:** ✓ compatible, ✗ with regime name when incompatible. Tooltip explains why.
**CVaR 3m:** colored — green if well below profile limit, amber if approaching, red if exceeds.

### Expanded Row (click to expand inline — no new page)

```
▼ iShares Core S&P 500 ETF (IVV)    Manager: BlackRock    ISIN: US4642872265
  ─────────────────────────────────────────────────────────────────────────
  Score Breakdown                    Risk Metrics (as of 2026-03-14)
  ─────────────────────────────────────────────────────────────────────────
  Return Consistency    ████░ 4.2/5  CVaR 95% 1m:   -2.1%   VaR 95% 1m:   -1.8%
  Risk-Adjusted Return  █████ 4.8/5  CVaR 95% 3m:   -3.1%   VaR 95% 3m:   -2.7%
  Drawdown Control      ████░ 4.1/5  CVaR 95% 6m:   -4.8%   Max DD 1y:    -8.4%
  Information Ratio     ████░ 4.0/5  Sharpe 1y:      1.24   Sharpe 3y:     1.18
  Flows Momentum        ███░░ 3.2/5  Sortino 1y:     1.87   Volatility 1y:  14.2%
  Lipper Rating         ████░ 4.0/5  Beta vs SPY:    1.00   Alpha 1y:       0.1%
  ─────────────────────────────────────────────────────────────────────────
  CVaR History (12m)                 Drawdown Periods
  [sparkline chart]                  2020-03: -34.2% | 2022-09: -24.8%
  ─────────────────────────────────────────────────────────────────────────
  Compatible with:  ✓ Conservative  ✓ Moderate  ✓ Growth
  Currently used in: Moderate (8.2% of block us_equity_broad)
  [Add to Conservative →]  [View Full Analysis →]
```

---

## View 4: Allocation Editor (`routes/allocation/+page.svelte`)

Two modes: Strategic (IC-only) and Tactical (model-generated).
Three tabs: Strategic | Tactical | Effective.

### Tab 1 — Strategic Allocation (IC-controlled)

For each block, shows a range slider with current target and band:

```
Block: US Equity Broad
Strategic: Conservative  Moderate  Growth
           ──────────────────────────────────────────────────────
Target:    [  22.0%  ]   [  22.0%  ]   [  22.0%  ]
Band:      [17% ████████████████████████████████ 27%]
           min=17%  current=22%  max=27%
Risk Budget: 22.0% of total portfolio risk budget

[Edit] button — only visible to users with IC role
```

When user clicks Edit (IC only), slider becomes interactive with:
- Hard stops at min/max
- Visual indicator if proposed change would breach CVaR limit
- "Simulate impact on CVaR" button before saving
- Rationale text field (required to save)
- Sends to approval queue if role is not ADMIN

### Tab 2 — Tactical Positions (model-generated)

Shows current model overweights/underweights with signal sources:

```
Block                  Overweight  Conviction  Signal Source    Valid Until
────────────────────────────────────────────────────────────────────────────
US Fixed IG            +3.0pp      ████ High   Regime (RISK_OFF) 2026-03-21
US Equity Broad        -2.0pp      ███  Med    Momentum (RSI<40)  2026-03-21
EM Asia Equity         -1.5pp      ██   Low    Regime (RISK_OFF)  2026-03-21
```

Conviction shown as filled bar (not just a number).
Signal source always shown — users want to know why.
"Valid Until" = next tactical review date.

### Tab 3 — Effective Allocation (read-only, combined view)

Shows the result of Strategic + Tactical for each profile, with selected funds:

```
Profile: Conservative
──────────────────────────────────────────────────────────────────────────────
Block              Strategic  Tactical  Effective  Selected Fund(s)
──────────────────────────────────────────────────────────────────────────────
US Equity Broad    22.0%     -2.0pp    20.0%      IVV (100%)
US Fixed IG        18.0%     +3.0pp    21.0%      AGG (60%) + BND (40%)
DM Europe Equity    8.0%      0.0pp     8.0%      VGK (100%)
EM Asia Equity      6.0%     -1.5pp     4.5%      EEM (100%)
Cash                0.0%      0.0pp     0.0%      —
──────────────────────────────────────────────────────────────────────────────
CVaR (effective):  -6.8%  vs. limit -8.0%  →  utilization 85%  ⚠ warning
```

---

## View 5: Risk Monitor (`routes/risk/+page.svelte`)

For users who want to go deep on risk analytics.

### Layout

```
┌────────────────────────────────────────────────────────────┐
│  PROFILE SELECTOR:  [Conservative ●] [Moderate] [Growth]  │
├────────────────────────────────────────────────────────────┤
│  CVaR TIMELINE (full width, tall chart)                    │
│  12 months rolling, all three profiles overlay option      │
├──────────────────────┬─────────────────────────────────────┤
│  REGIME TIMELINE     │  MACRO DETAIL                       │
│  (color band chart)  │  VIX, Yield Curve, CPI, HY Spread  │
│                      │  12m sparklines each                │
└──────────────────────┴─────────────────────────────────────┘
```

### CVaR Timeline Chart — Full Specification

This is the most analytically important chart in the product. It must be precise.

- **Primary line:** rolling CVaR (selected profile)
- **Secondary lines:** other profiles (toggled via legend, lower opacity)
- **Limit line:** dashed red, labeled "Limit: -8.0%"
- **Warning band:** shaded amber area between 80% and 100% of limit
- **Breach zones:** shaded red when CVaR was in breach, with duration label
- **Regime background:** subtle colored bands (blue/amber/orange/red) by regime
- **Rebalance events:** vertical dashed lines, labeled "Rebalance"
- **Hover:** shows exact CVaR, VaR, utilization%, regime, and date
- **Time controls:** 1m | 3m | 6m | 1y | 2y | All — default 1y
- **Y-axis:** inverted scale (worse = visually higher), labeled with % values
- **Bayesian bounds:** optional toggle for CVaR lower_5/upper_95 confidence band
  (shaded gray area around the CVaR line)

### Regime Timeline Chart

ECharts bar chart (categorical, time-based):
- X-axis: dates
- Each bar segment colored by regime (RISK_ON=blue, RISK_OFF=amber, INFLATION=orange, CRISIS=red)
- Hover: shows regime name, duration, key signals that triggered it
- Always synchronized with CVaR chart (same time range)

### Macro Detail

6 sparkline cards in a 3×2 grid:

```
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  VIX          │  │  10Y-2Y Spread│  │  CPI YoY      │
│  28.4  ↑      │  │  -0.12%  ↓   │  │  3.8%  →      │
│  [sparkline]  │  │  [sparkline]  │  │  [sparkline]  │
│  Regime: ⚠    │  │  Inverted     │  │  Above target  │
└───────────────┘  └───────────────┘  └───────────────┘
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  HY Spread    │  │  Fed Funds    │  │  Sahm Rule    │
│  487bps  ↑   │  │  5.25%  →    │  │  0.12  →      │
│  [sparkline]  │  │  [sparkline]  │  │  [sparkline]  │
│  Elevated     │  │  Restrictive  │  │  Below 0.5    │
└───────────────┘  └───────────────┘  └───────────────┘
```

Each card:
- Value + direction arrow + color
- 12-month sparkline (ECharts, no axes, just the shape)
- Contextual label in plain language (not "above threshold")
- Click → opens full chart with full history

---

## View 6: Backtest (`routes/backtest/+page.svelte`)

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  CONFIGURATION                                          │
│  Profile: [Conservative ▾]  Period: [2020-2025 ▾]      │
│  Scenario: [Historical ▾]   [Run Backtest]              │
├─────────────────────────────────────────────────────────┤
│  RESULTS (shown after run)                              │
│  Summary metrics row                                    │
├───────────────────┬─────────────────────────────────────┤
│  CUMULATIVE       │  DRAWDOWN ANALYSIS                  │
│  RETURN CHART     │  Max DD periods                     │
├───────────────────┴─────────────────────────────────────┤
│  STRESS SCENARIOS: 2008 | 2020-Mar | 2022               │
│  Side-by-side performance comparison                    │
├─────────────────────────────────────────────────────────┤
│  CVaR BREACH HISTORY during backtest period             │
│  How many times would limits have been breached?        │
└─────────────────────────────────────────────────────────┘
```

### Results Summary Row

```
Ann. Return  Ann. Vol  Sharpe  Sortino  Max DD    CVaR Breaches  Rebalances
─────────────────────────────────────────────────────────────────────────────
   +8.4%      11.2%    0.87    1.24    -18.4%        3 events       12
```

All values colored relative to expectation. CVaR Breaches is the key risk metric —
how often would the system have triggered.

---

## Component Anti-Patterns (NEVER DO)

1. **Never show a number without context.**
   Bad: "CVaR: -7.2%"
   Good: "CVaR -7.2% | Limit -8.0% | 90% utilized | +0.4pp this week"

2. **Never hide drift history behind multiple clicks.**
   Bad: Menu → Portfolio → Risk → History → Drift
   Good: "Drift History" button visible in the portfolio header always

3. **Never use generic empty states.**
   Bad: "No data available"
   Good: "Waiting for daily pipeline to run. Last update: yesterday 07:31.
         Next update: today ~07:00. [Trigger manual update →]"

4. **Never paginate drift history.**
   Use infinite scroll or a full table with filters. Pagination breaks
   the audit trail narrative.

5. **Never round CVaR to fewer than 1 decimal place.**
   The difference between -7.9% and -8.0% is a limit breach. Precision matters.

6. **Never show regime as a raw enum.**
   Bad: "RISK_OFF"
   Good: "⚠ Stress Environment" with tooltip explaining signals

7. **Never omit the reason a decision was made.**
   Every rebalance event, every regime change, every breach must show
   the signals that caused it. Users need to explain to clients why
   the portfolio changed.

8. **Never show the Pareto front as a scatter plot of 47 points.**
   Use the slider metaphor described above. The scatter is for quantitative
   analysts — this product serves portfolio managers.

---

## ECharts Usage Standards

All charts use `svelte-echarts`. These settings apply globally:

```typescript
const globalChartOptions = {
  animation: true,
  animationDuration: 300,
  backgroundColor: 'transparent',
  textStyle: { fontFamily: 'Inter, system-ui, sans-serif', fontSize: 12 },
  grid: { containLabel: true, left: 8, right: 8, top: 8, bottom: 8 },
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'cross' },
    confine: true,
  },
  toolbox: {
    show: true,
    feature: {
      dataZoom: { show: true },
      restore: { show: true },
      saveAsImage: { show: true, name: 'netz-chart' },
    },
  },
}
```

**Specific chart requirements:**

- CVaR timeline: `yAxis.inverse: true` so worse (more negative) is visually higher
- All time series: `xAxis.type: 'time'` (not category)
- Reference lines: `markLine` with label, always `symbol: 'none'`
- Breach zones: `markArea` with `itemStyle.color` at low opacity
- Sparklines: no grid, no axis, no tooltip, no toolbox — pure shape only
- All percentage Y-axes: `axisLabel.formatter: (v) => v.toFixed(1) + '%'`
- Tabular numbers in all chart labels: `rich` text with `fontVariant: 'tabular-nums'`

---

## API Integration Notes (for Svelte stores)

The stores must handle these specific patterns:

```typescript
// CVaR store — SSE subscription for live updates
export const cvarStore = createCVaRStore({
  profileIds: ['conservative', 'moderate', 'growth'],
  sseEndpoint: '/api/v1/risk/stream',
  pollingFallbackMs: 30_000,  // fallback if SSE drops
})

// Drift store — must persist history locally for offline access
export const driftStore = createDriftStore({
  profileId: 'conservative',
  historyDays: 90,    // always load 90 days on mount
  localStorageKey: 'drift_history_conservative',  // persist between sessions
})

// Regime store — poll every 60s (regime changes infrequently)
export const regimeStore = createRegimeStore({
  pollIntervalMs: 60_000,
  sseEndpoint: '/api/v1/risk/stream',
})
```

**All stores must expose:**
- `status: 'loading' | 'ready' | 'error' | 'stale'`
- `lastUpdated: Date | null`
- `error: string | null`

When `status === 'stale'` (data older than expected pipeline run), show
a banner: "Data may be out of date. Pipeline last ran: [time]. [Refresh →]"

---

## Accessibility Requirements

- All color-coded status must also have text or icon indicator (not color alone)
- All charts must have `aria-label` with description of what is shown
- All interactive controls must be keyboard navigable
- Numeric values in tables must use `role="cell"` and `headers` attribute
- Status badges must use `role="status"` and announce changes to screen readers
- Minimum contrast ratio 4.5:1 for all text (WCAG 2.1 AA)

---

## Localization Notes

- All dates: use `Intl.DateTimeFormat` with user's locale
- All numbers: `Intl.NumberFormat` with explicit `minimumFractionDigits`
- All percentages: always show sign for changes (use `signDisplay: 'always'`)
- Currency amounts: show currency symbol + 2 decimal places minimum
- Regime labels, status labels, signal source labels: all must go through
  paraglide-js i18n keys — never hardcoded strings in templates
