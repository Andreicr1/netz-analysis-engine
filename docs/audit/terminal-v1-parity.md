# Terminal V1 — Bundle Parity Audit

**Sprint:** `feat/terminal-v1-bundle-parity` (2026-04-19)
**Reference bundle:** `docs/ux/Netz Terminal/` (4 HTMLs + 11 JSX + 4 CSS)
**Terminal app:** `frontends/terminal/` consuming `@investintell/ii-terminal-core`
**Scope:** Structural parity only. Data content (rows/values/tickers) is out of scope.

## 0 · Scope rules (read first)

The bundle is a React static demo with synthetic fixtures (`INSTRUMENTS`,
`ALERTS`, `MACRO_REGIMES`, etc.). The terminal is a Svelte 5 app driven by
real backend data. Differences in what's shown are legitimate. This audit
catalogs only **structural** divergences:

- Missing regions / panels
- Wrong grid topology (columns, rows, fixed vs flex)
- Wrong column sets (counts, order, identity)
- Missing affordances (sort, filter, visual drift bar, flash animation,
  crosshair readout, status dot, big-price display)
- Wrong labels or pill counts
- Hairline / density / spacing mismatches the surface CSS can't carry
  alone

It does not catalog:

- Different row counts (bundle fixtures vs backend)
- Different tickers or names
- Styling details already resolved by the ported surface CSS (X3)
- Features the bundle invents that have no backend (catalogued as
  "out of scope — future sprint")

Per the sprint's scanner discipline: **no shadcn semantic classes** may
land in fixes. Invariant F is a hard gate.

## 1 · Phase A — Breadcrumb removal

**Status: no-op (already on `origin/main`).**

`packages/ii-terminal-core/src/lib/components/terminal/shell/TerminalShell.svelte`
already declares the `hideWorkflowStepper: boolean` prop and collapses the
`.ts-shell--no-crumb` row when it is true. `frontends/terminal/src/routes/+layout.svelte`
passes `hideWorkflowStepper={true}` to TerminalShell. Wealth's
`(terminal)/+layout.svelte` passes nothing, so the default `false`
preserves the breadcrumb for `/(terminal)/**` routes as required.

The sprint plan named the prop `hideBreadcrumb`. Renaming to that name is
pure churn — same behavior, same callers. Keeping `hideWorkflowStepper`.

**Acceptance criteria, verified by source:**
- Terminal `/live`, `/allocation`, `/screener`, `/macro`: breadcrumb
  hidden via `hideWorkflowStepper={true}` ✓
- Wealth `/(terminal)/**`: breadcrumb visible via default ✓

No commits 1–2 from the plan are produced. Phase A drops to documentation.

## 2 · LIVE surface

**Bundle:** `Netz Terminal.html` + `terminal-app.jsx` + `terminal-panels.jsx` +
`terminal-chart.jsx` + `terminal-data.jsx`
**Terminal:** `frontends/terminal/src/routes/live/+page.svelte` consuming
`@investintell/ii-terminal-core/components/terminal/live/*`

### 2.1 Grid topology

| Region | Bundle | Terminal | Match? |
|---|---|---|---|
| Root grid | 3-col (LEFT / CENTER / RIGHT), status + topbar outside | 3-col (280px / 1fr / 280px), chrome outside (TerminalShell) | ✓ structural |
| LEFT stack | PortfolioSelector · Watchlist (60) · AlertStream (25) · TradeLog (**20**) | PortfolioSelector · Watchlist (60) · Alerts (25) · TradeLog (**15**) | **flex 15→20** |
| CENTER stack | ChartToolbar · Chart · Bottom(Summary 200px + Holdings 1fr) | same | ✓ |
| RIGHT stack | NewsFeed (55) · MacroRegime (45) | NewsFeed (55) · MacroRegime-panel (45) | ✓ grid, **wrong panel identity** (see 2.6) |

**D-1** LEFT TradeLog flex share should be 20 (not 15) so the 60/25/20
ratio matches the bundle's stated weights.

### 2.2 Watchlist component

Bundle `Watchlist` (`terminal-panels.jsx:147-189`) renders a 4-column
header + 4-column rows:

```
TICKER  NAME  LAST  CHG%
```

Header has `.phead` with title + counter badge; actions area has `+` add
and `⇅` sort icon buttons.

Terminal `Watchlist.svelte` renders no column header; rows are 2-column
(`wl-row-left` stacks ticker/name/weight, `wl-row-right` stacks
change/price). Header shows `WATCHLIST` + portfolio name. Footer has a
ticker search form.

**D-2** Bundle has a 4-col header table; terminal has no header row. The
bundle's grid layout is more scannable for institutional density.
**Fix candidate:** add a 4-col header + restructure rows to a 4-col
grid. Keep the terminal's footer search — it's a UX gain over the
bundle's `+` icon button (which does nothing in the demo).

**D-3** Bundle rows carry a `flash-up` / `flash-down` animation on price
tick (`terminal-app.jsx:234-247`). Terminal rows have only hover
transition. This is a high-value affordance for a live workbench.
**Fix candidate:** flash the row background on `MarketDataStore`
price-tick events (200ms ease-out).

**D-4** Header counter (bundle shows item count beside title). Terminal
header shows portfolio name — different purpose. Keeping terminal's
portfolio name (higher info density), but counter badge can coexist.
Low priority; defer.

### 2.3 HoldingsTable component

Bundle `Holdings` (`terminal-panels.jsx:288-393`) renders 8 columns with
sort + filter:

```
TK  NAME / SECTOR  LAST  CHG%  WT  DRIFT-BAR  Δ pp  TGT
```

Drift column renders a ±4pp visual bar with centerline and directional
fill. Filter input in header. All column headers sortable with ▲/▼
indicators.

Terminal `HoldingsTable.svelte` renders 7 columns:

```
Fund  Ticker  Weight  Target  Drift  Price  Change
```

No sector, no drift bar visual, no filter, no sort.

**D-5** Missing sector column on the NAME cell — bundle shows sector as
a second line beside fund name. **Fix candidate:** add sector sub-line
to the Fund cell when `instrument.sector` is available (it already
flows from `instruments.attributes.sector` via the backend resolver).
If sector is unavailable for many holdings, show fund name alone.

**D-6** Missing drift visual bar — bundle renders `.drift-bar-wrap` with
centerline + directional fill bar. Terminal shows only drift as colored
text. This is a high-value institutional affordance.
**Fix candidate:** add an inline drift bar column between drift-value
and target; use existing status-success/warn/error tokens for color.

**D-7** Column order mismatch — bundle puts LAST/CHG% **before** WT;
terminal puts Weight/Target/Drift first and price/change last. The
bundle's order aligns with a market-data-first reading (what's the
market doing → what's my exposure). **Fix candidate:** reorder so
Ticker → Name → Last → Change% → Weight → Target → Drift → Price
(fold price/last together).

**D-8** Missing filter input — bundle has a `FILTER ⌕` input in header.
**Fix candidate:** add header input that filters rows by ticker or
fund name (client-side; table is always ≤50 rows).

**D-9** Missing sort — all bundle column headers click to toggle sort.
**Fix candidate:** wire sort on ticker/weight/drift/change at minimum.

### 2.4 ChartToolbar component

Bundle `ChartToolbar` (`terminal-panels.jsx:455-481`) has 3 groups:

```
[ticker big-price ▲ dayPct%]   [1D 1W 1M 3M 1Y 5Y MAX]   [+COMPARE  INDICATORS  ⟲ REBALANCE]
```

- Ticker-head and big price side-by-side (ticker smaller, price big).
- 7 timeframe buttons including **MAX**.
- REBALANCE button in toolbar (primary CTA).

Terminal `ChartToolbar.svelte` has:

```
[ticker // name // price ±change%]   [CANDLE LINE | 1D 1W 1M 3M 6M 1Y | Compare | Indicators]
```

- 6 timeframes; missing 5Y, MAX.
- Has CANDLE/LINE mode toggle (gain over bundle).
- No REBALANCE button.

**D-10** Missing timeframes 5Y and MAX — bundle has both.
**Fix candidate:** add them. Terminal's `TerminalPriceChart` likely
needs a date-range widening, but the toolbar can emit the TF; if the
backend REST response is empty for 5Y/MAX, chart degrades gracefully.

**D-11** Missing REBALANCE button in toolbar. Bundle fires
`onRebalance` both from toolbar and from Summary panel; terminal only
surfaces it in Summary. **Fix candidate:** add toolbar button that
triggers the same handler.

**D-12** Big-price display — bundle renders price as `.chart-price-big
.big` (fontSize 22+, weight 600). Terminal has a single inline price
(11px). For a live workbench the big price is the central signal.
**Fix candidate:** scale price to 16–18px in toolbar.

### 2.5 Price chart crosshair readout

Bundle `CandleChart` (`terminal-chart.jsx:104-271`) on hover renders an
**O/H/L/C/V tooltip rect** near the crosshair, plus watermark
`TICKER · Daily` and a pulsing last-tick dot.

Terminal uses `lightweight-charts` via `TerminalPriceChart.svelte` which
handles its own crosshair and tooltip. Not a structural gap — the lib
provides equivalent affordances. Leave as-is.

### 2.6 MacroRegime → MacroRegimePanel (major divergence — deferred)

Bundle `MacroRegime` (`terminal-panels.jsx:431-452`) shows **6 regional
regime rows** (US / EU / CN / BR / JP / EM-xCN) with stress % + trend
arrow + label. Answers "what regime is each region in?".

Terminal `MacroRegimePanel.svelte` shows **8 FRED indicators** (VIX /
CPI / DXY / 10Y / IG / HY / FF / UNRATE) with value + delta arrow.
Answers "what are my market indicators?".

**D-13 — DEFERRED.** Backend verification (2026-04-19):
`GET /macro/scores` returns regions keyed by US / EUROPE / ASIA / EM —
**4 regions, not 6**, with `composite_score`, `coverage`, `dimensions`,
and `analysis_text` (free-text committee summary, not a row-sized
label). There is **no per-region qualitative label** like "Mid-cycle
expansion". Rewriting the panel to `US — 42 — ↗ —` rows with no trend
and no label is strictly worse than the existing FRED indicators: it
ships jargon (a composite score number) without the surrounding context
that makes a regime snapshot useful.

To do this right, the backend needs to expose a per-region regime label
(either as a new column on `macro_regional_snapshots` or derived from
the committee review's executive summary). Tracked as future work.

### 2.7 PortfolioSelector / Summary / NewsFeed / TradeLog / AlertStream

These are broadly aligned. PortfolioSelector dropdown, Summary rows
(AUM / Day P/L / Holdings / Drift pill / Last Rebal + REBALANCE
button), NewsFeed cards, TradeLog rows all mirror the bundle structure.
No structural divergences beyond 2.1's flex ratio.

## 3 · BUILDER surface

**Bundle:** `Netz Terminal - Builder.html` + `builder-app.jsx` +
`builder-preview.jsx` + `builder-data.jsx`
**Terminal:** `frontends/terminal/src/routes/allocation/[profile]/+page.svelte`
(X3.1 Builder Workspace — fused `/allocation` + `/portfolio/builder`)

### 3.1 Conceptual divergence (recognized)

Bundle Builder is aspirational. It depicts a **7-tab optimizer
workspace** with a cascade simulation animation, an activation gate,
and tabs for REGIME / WEIGHTS / RISK / STRESS / BACKTEST / MONTE
CARLO / ADVISOR. The terminal's fused X3.1 Builder has **3 tabs**
(STRATEGIC / PORTFOLIO / STRESS) mapped to actually-implemented
backend capabilities.

The gap is not a bug — it's future product. Forcing empty `BACKTEST`
/ `MC` / `ADVISOR` tabs to ship would add dead UI. Bringing the
cascade animation from the prior Phase 4 work into this surface is
already done inside PortfolioTabContent.

**Out of scope for this sprint:** Monte Carlo tab, Backtest tab
(equity-curve + drawdown SVGs), Advisor tab (insight cards), the
separate REGIME / WEIGHTS / RISK tabs as top-level nav. Document as
future work.

### 3.2 In-scope divergences

**D-14** Bundle's left column has Zone A (Regime Context bands
strip) + Zone B (full calibration panel with presets, factor tilts,
constraints, region caps, optimizer params) + Zone C (run
controls). Terminal's Strategic/Portfolio/Stress tabs re-use
`RegimeContextStrip` but the calibration panel in
`PortfolioTabContent.svelte` is narrower — factor tilts and region
caps don't appear as explicit controls. Need to verify when
writing fixes whether they're present at all.
**Fix candidate:** if calibration presets (CONSERVATIVE/MODERATE/
AGGRESSIVE) are missing, surface a 3-button row at the top of
PortfolioTabContent mapping to the ProfileStrip profile. If factor
tilt sliders are entirely absent, defer to a later sprint — they
require backend plumbing. Keep this audit honest.

**D-15** Bundle's tab row is 7 pulsing-during-run tabs with a
"visited" gate. Terminal's 3-tab row has no pulse or activation
gate. The pulse visual indicates which tab's data is currently
being computed in the cascade. Since terminal's cascade runs in
PortfolioTabContent and emits progress via SSE, a pulsing tab is
achievable.
**Fix candidate:** decorate BuilderTabStrip tabs with a `pulsing`
visual state when a construction run is streaming. Low priority
if backend doesn't already emit phase metadata per tab.

### 3.3 Out-of-scope list (to document in PR)

- 7-tab top nav (we have 3; the other 4 are product-gap, not
  parity-gap)
- Cascade timeline bar (already covered by
  `CascadeTimelineBar.svelte` in a prior sprint — verify it's
  surfaced)
- BACKTEST / MC / ADVISOR tab content
- Factor tilt sliders
- Activation gate (SEND TO COMPLIANCE)
- KPI ribbon above tab content (EXP RETURN / VOL / SHARPE / MAX DD
  / TRACK ERR)

## 4 · SCREENER surface

**Bundle:** `Netz Terminal - Screener.html` + `screener-app.jsx` +
`screener-data.jsx`
**Terminal:** `frontends/terminal/src/routes/screener/+page.svelte` +
`TerminalScreenerShell.svelte` + `TerminalScreenerFilters.svelte` +
`TerminalDataGrid.svelte`

### 4.1 Grid topology

Both render 2-col (LEFT filter rail / RIGHT results). ✓

### 4.2 Filter rail

Bundle `FilterRail` (`screener-app.jsx:5-97`) has 9 groups:

1. Universe (chip row)
2. Strategy (chip row)
3. Geography (chip row)
4. AUM min/max (range inputs)
5. Return 1Y min/max
6. Sharpe min/max
7. Max Drawdown min/max
8. Expense Ratio max
9. Netz Elite only (toggle)

Plus footer: `RESET`, `SAVE PRESET`.

Terminal's `TerminalScreenerFilters.svelte` (from the `FilterState`
export in the page) exposes the same filters: `fundUniverse`,
`strategies`, `geographies`, `aumMin/Max`, `returnMin/Max`,
`expenseMax`, `eliteOnly`, `sharpeMin/Max`, `drawdownMin/MaxPct`,
`volatilityMax`, `return10yMin/Max`. Terminal has **more** filters
(volatility max, 10Y return range) — a gain over bundle.

**D-16** Bundle has a `SAVE PRESET` action in the filter footer.
Terminal doesn't. Given presets require backend persistence, this
is an out-of-scope future feature. Note only.

**D-17** Need to verify terminal filters render as chip rows for
universe/strategy/geography (matching bundle) — if they render as
check-list or dropdown, that's a density downgrade. Will inspect
when writing fixes.

### 4.3 Results table

Bundle `ResultsTable` (`screener-app.jsx:322-374`) has 15 columns,
all sortable:

```
TICKER · NAME · UNIVERSE · MANAGER · STRATEGY · GEO · AUM · 1Y% · 3Y% · 10Y% · SHARPE · VOL% · MAX DD% · EXP% · SCORE
```

Terminal's `TerminalDataGrid` — column set needs verification in
fix phase. Based on the URL filter set, columns should include at
minimum: ticker, name, AUM, return 1Y, sharpe, drawdown, expense,
score. Missing columns are D-18.

**D-18** (pending verification) Column set parity with bundle's 15.

**D-19** Toolbar above table — bundle has summary "X/Y funds · N
elite · avg 1Y X% · avg Sharpe Y", search input, EXPORT CSV
button, + COMPARE button. Terminal — verify if these exist. If
partial, identify missing.

### 4.4 FundFocus mode

Bundle `FundFocus` (`screener-app.jsx:184-319`) is a full-screen
modal with:
- Header (name + elite badge + ticker/manager/strategy/geo/inception)
- 6-cell KPI grid (AUM / 1Y / 3Y / Sharpe / Vol / Max DD)
- Performance chart (growth of 100 · 3Y rolling)
- Peer Sharpe bars (top 5 peers in strategy)
- Composite Score radar (6-axis polygon + side bar list)
- Footer (CLOSE / OPEN DD REPORT / ADD TO WATCHLIST / ADD TO
  PORTFOLIO)

Terminal has `FundFocusMode.svelte` — structure TBD in fix phase.

**D-20** (pending verification) FundFocusMode completeness.

## 5 · MACRO surface

**Bundle:** `Netz Terminal - Macro.html` + `macro-app.jsx` +
`macro-data.jsx` (+ `macro.css`)
**Terminal:** `frontends/terminal/src/routes/macro/+page.svelte`

### 5.0 D-10 / D-21 verification note (2026-04-19)

- `GET /market-data/historical/{ticker}` accepts an optional `start_date`
  ISO query param; the terminal's current call at `live/+page.svelte`
  does **not** pass it, so every TF button renders the default
  6-month window. D-10's "add 5Y/MAX" fix therefore also resolves a
  pre-existing bug: wiring `start_date` from the active TF makes all
  timeframes actually work.
- `GET /macro/scores` returns 4 regions (US/EUROPE/ASIA/EM), no per-
  region label. `/macro` zone layout does not contain a per-region
  tile grid — StressHero + SignalBreakdown + SparklineWall are all
  global-scoped. A region segment in a new macro toolbar would
  therefore be decorative. D-21 deferred.

### 5.1 Grid topology — significant divergence

Bundle lays out:

- Top toolbar: Region seg (GLOBAL / US / EU / ASIA / BR) + Window
  seg + REGIME pill + LIQ pill + `+ COMPARE` + `OPEN CHART (N)`
- Main grid 3-col:
  - LEFT column = cross-asset MiniCards grouped by RATES / FX /
    EQUITY / COMMODITY / CREDIT
  - CENTER column = Regime Matrix (interactive pin) + Liquidity
    panel + Sentiment tiles (top row) + CB calendar + Economic
    pulse (bottom row)
  - RIGHT column = Macro News feed

Terminal `/macro` lays out (per page header comment):
- Zone 1: StressHero (7fr) + RegimeMatrix (5fr) side-by-side
- Zone 2: SignalBreakdown (full width)
- Zone 3: RegionalHealth (6fr) + SparklineWall (6fr)
- CommitteeReviewFeed in a right-anchored drawer (Shift+R)

These are **different compositions of the same inputs**. Terminal's
zone-based layout is more specialized (RegionalHealth +
SignalBreakdown are institutional-grade rewrites of bundle's
MiniCard/EconPulse concept). Trying to force bundle's exact grid
would regress the terminal's information density.

**D-21** Missing top toolbar (Region seg, Window seg, REGIME/LIQ
pills, + COMPARE, OPEN CHART). Terminal goes directly into Zone 1.
The region segment is a high-value affordance — it's how PMs
pivot macro context.
**Fix candidate:** add a MacroToolbar above Zone 1 with at least
the REGION segment (GLOBAL / US / EU / ASIA / BR) + the current
regime pill (which today is stored in `pinnedRegime`). The
window/timeframe segment can come later; the bundle's compare
flow requires bundle's MiniCard model which we don't have.

**D-22** MACRO news feed panel not visible in terminal's zone
layout. Bundle has it as the right column. Terminal's
CommitteeReviewFeed is review/committee-specific, not general
macro news.
**Fix candidate:** defer — real news requires a data source
(bundle uses a fixture). If a macro news endpoint exists, wire
it; else out of scope.

### 5.2 Regime Matrix

Bundle `RegimeMatrix` (`macro-app.jsx:21-123`) is a draggable SVG
pin with 4 quadrant labels (OVERHEATING / STAGFLATION /
GOLDILOCKS / REFLATION), axis labels, and an 18-month trail
polyline.

Terminal `RegimeMatrix.svelte` — verify during fix phase whether
the 4 quadrant labels + trail are present.

**D-23** (pending verification) RegimeMatrix has 4 quadrant labels,
axis labels (GROWTH / INFLATION), trail polyline, draggable pin.

### 5.3 Out-of-scope

- MiniCard model (cross-asset ticker cards grouped by sector)
- Liquidity gauge (G4 CB balance delta needle)
- Sentiment tiles
- CB calendar panel (central-bank meeting rate expectations)
- Economic pulse panel (actual vs consensus surprises)
- Asset drawer (compare-up-to-4 flow)
- Compare mode

These are substantial future-product features. Note in PR.

## 6 · Summary — divergence triage

Items marked **FIX** are implementable this sprint; items marked
**DEFER** are future-product or require backend work.

| ID | Surface | Component | Divergence | Action |
|---|---|---|---|---|
| D-1 | LIVE | +page grid | TradeLog flex 15 → 20 | **FIX** |
| D-2 | LIVE | Watchlist | No 4-col header / 2-col rows | **FIX** |
| D-3 | LIVE | Watchlist | No flash-up/down on tick | **FIX** |
| D-4 | LIVE | Watchlist | No counter badge | DEFER (low value) |
| D-5 | LIVE | Holdings | No sector sub-line on fund name | **FIX** |
| D-6 | LIVE | Holdings | No drift visual bar | **FIX** |
| D-7 | LIVE | Holdings | Column order mismatch | **FIX** |
| D-8 | LIVE | Holdings | No filter input | **FIX** |
| D-9 | LIVE | Holdings | No column sort | **FIX** |
| D-10 | LIVE | ChartToolbar | Missing 5Y and MAX timeframes | **FIX** (verified backend supports `start_date`; also fixes pre-existing bug where TF buttons don't pass a lookback) |
| D-11 | LIVE | ChartToolbar | Missing REBALANCE button | **FIX** |
| D-12 | LIVE | ChartToolbar | Price not "big" (22px class) | **FIX** (capped at 16px — 22px won't fit in 32px toolbar without bumping `lw-toolbar` height) |
| D-13 | LIVE | MacroRegimePanel | Wrong panel identity — indicators instead of regional regime | **DEFER** (verified: `/macro/scores` returns 4 regions only (US/EUROPE/ASIA/EM) with `composite_score` but **no per-region qualitative label**. Rewrite would ship `US — 42 — ↗ —` rows with no trend and no label — strictly worse than existing FRED indicators. Needs backend to expose per-region regime label before this is a net gain.) |
| D-14 | BUILDER | ZoneB calibration | Presets / factor tilts / caps missing | DEFER (backend plumbing) |
| D-15 | BUILDER | TabStrip | No pulsing tabs during cascade | DEFER (needs phase-tab mapping) |
| D-16 | SCREENER | FilterRail | No SAVE PRESET | DEFER (persistence) |
| D-17 | SCREENER | FilterRail | Chip-row rendering unverified | Verify in fix pass |
| D-18 | SCREENER | ResultsTable | Column set vs bundle's 15 | Verify / **FIX** |
| D-19 | SCREENER | Toolbar | Summary line, EXPORT CSV, + COMPARE | Verify / **FIX** (partial) |
| D-20 | SCREENER | FundFocus | Full modal structure | Verify in fix pass |
| D-21 | MACRO | Toolbar | Missing Region seg + LIQ pill + REGIME pill | **DEFER** (verified: `/macro` renders zones, not a per-region tile grid. A Region segment would be decorative — StressHero, SignalBreakdown, SparklineWall are all global-scoped. Adding the toggle without a filter target is exactly the "jargon UI without function" anti-pattern `feedback_smart_backend_dumb_frontend` forbids. Requires a redesign of the zone layout to accept region scoping first.) |
| D-22 | MACRO | Right col | Missing macro news feed | DEFER (data source) |
| D-23 | MACRO | RegimeMatrix | 4 quadrants + trail + drag | Verify in fix pass |

## 7 · Out-of-scope future product

Tracked here so future sprints can pick up without re-auditing:

1. **Builder** 7-tab workspace with BACKTEST / MC / ADVISOR tabs + KPI
   ribbon + activation gate. Requires stress/backtest/MC/advisor
   backend output already available — Sprint 2c.
2. **Macro** cross-asset MiniCard layer (RATES / FX / EQUITY / CRED /
   COMMODITY grouping) + Liquidity gauge + Sentiment tiles + CB
   calendar + Economic pulse. Heavy; Sprint 3.
3. **Macro news** feed — needs data source.
4. **Screener SAVE PRESET** — needs persistence.
5. **Command palette search** — already has a component but content
   coverage is Sprint 2a.1.

## 8 · Verification plan

Post-fix, the PR body will include side-by-side screenshots for each
of the 4 surfaces (bundle HTML opened locally vs terminal dev at
`:5175`). A screenshot is not a pixel gate — it's evidence that the
structural items listed in this doc are addressed or accounted for.

Scanner (`node scripts/check-terminal-tokens-sync.mjs`) runs before
each commit in Phase C. Invariant F (no shadcn semantic classes) and
Invariant H (no `$wealth/*` imports in terminal) must stay green
throughout.
