# Phase 3 Fix Sprint 4 — Data Trust + Score Integration

**Date:** 2026-04-12
**Branch:** `feat/phase-3-fix-sprint-4`
**Scope:** 6 atomic commits fixing data correctness issues that destroy institutional trust
**Estimated duration:** 2-3 hours concentrated Opus session
**Prerequisite reading:** this file only (self-contained)
**Depends on:** Fix Sprint 3 merged (main has infinite scroll, manager filter, metric ranges)

## Why this sprint exists

Screenshots from 2026-04-12 show the screener displaying incorrect or missing data:

1. **1Y and 10Y Returns show "—" for every row** despite data existing in the database. An institutional analyst seeing all-dashes in the returns columns concludes the system has no data — immediate loss of trust.
2. **ER% shows "0.00" for almost every row** which is impossible — no fund has a 0% expense ratio. The scale is wrong somewhere in the pipeline (stored as decimal 0.0075, displayed as 0.00 after rounding, or the column is simply NULL/zero in the response).
3. **TREND sparkline column shows NAV direction** — this was never a planned feature and conflicts with the deterministic ELITE ranking based on composite_score. "Trend" sounds like speculation. The column should show the fund's SCORE (0-100) instead.
4. **Filters are all expanded by default** consuming excessive sidebar space on 13" displays with internal scrollbar.

Issues 1-3 are **data correctness bugs** that violate the mandate:

> Máximo de percepção visual é válida somente quando a infraestrutura está correta, reportando dados reais e precisos, do contrário o sistema não é confiável.

A beautiful grid showing wrong numbers is worse than an ugly grid showing right numbers.

## READ FIRST

1. `backend/app/domains/wealth/routes/screener.py` — catalog endpoint, current SELECT columns
2. `backend/app/domains/wealth/queries/catalog_sql.py` — query builder, column selection from JOINed tables
3. `backend/app/domains/wealth/schemas/catalog.py` — `UnifiedFundItem` response schema, field types
4. `backend/app/core/db/migrations/versions/0116_mv_fund_risk_latest.py` — MV columns (does it include returns?)
5. `backend/app/core/db/migrations/versions/0078_consolidated_screener_views.py` (or equivalent) — `mv_unified_funds` columns (does it include returns, expense_ratio?)
6. `backend/quant_engine/scoring_service.py` — composite score computation, component weights, output format
7. `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte` — column rendering, sparkline implementation, where SCORE column replaces TREND
8. `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerFilters.svelte` — section expand/collapse state
9. `frontends/wealth/src/lib/components/terminal/focus-mode/fund/FundFocusMode.svelte` — where score composition module will be added
10. `frontends/wealth/src/lib/components/analytics/entity/EntityAnalyticsVitrine.svelte` — existing analytics modules that score composition joins

## Pre-flight — SQL investigation (MANDATORY before any code)

These 4 diagnostic queries must be run against the local dev DB BEFORE starting any commit. Capture the output and include it in the commit 1 and commit 2 messages. This is the data archaeology that drives every fix.

```sql
-- Q1: What return columns exist on mv_unified_funds?
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'mv_unified_funds'
  AND column_name ILIKE '%return%'
ORDER BY ordinal_position;

-- Q2: What return columns exist on mv_fund_risk_latest?
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'mv_fund_risk_latest'
  AND column_name ILIKE '%return%'
ORDER BY ordinal_position;

-- Q3: What does expense_ratio_pct ACTUALLY look like in the data?
SELECT
  expense_ratio_pct,
  COUNT(*) AS cnt
FROM mv_unified_funds
WHERE expense_ratio_pct IS NOT NULL
GROUP BY expense_ratio_pct
ORDER BY cnt DESC
LIMIT 20;

-- Q4: Sample of returns + ER + score for 10 real funds
SELECT
  u.external_id,
  u.name,
  u.expense_ratio_pct,
  u.avg_annual_return_pct,
  r.sharpe_1y,
  r.manager_score,
  r.elite_flag
FROM mv_unified_funds u
LEFT JOIN mv_fund_risk_latest r ON r.instrument_id = u.instrument_id
WHERE u.expense_ratio_pct IS NOT NULL
LIMIT 10;
```

Also run:

```sql
-- Q5: Do return columns exist ANYWHERE that the catalog could source them?
SELECT table_name, column_name
FROM information_schema.columns
WHERE column_name ILIKE '%return%'
  AND table_schema = 'public'
  AND table_name IN ('mv_unified_funds', 'mv_fund_risk_latest', 'fund_risk_metrics',
                      'nav_monthly_returns_agg', 'sec_fund_prospectus_returns',
                      'sec_fund_prospectus_stats', 'sec_fund_classes')
ORDER BY table_name, column_name;

-- Q6: What is the composite score distribution?
SELECT
  COUNT(*) AS total,
  COUNT(manager_score) AS with_score,
  MIN(manager_score) AS min_score,
  AVG(manager_score) AS avg_score,
  MAX(manager_score) AS max_score,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY manager_score) AS median_score
FROM mv_fund_risk_latest;
```

**STOP after running Q1-Q6. Record all outputs. These inform every commit below.**

The column names, scales, and data availability you discover may DIFFER from what I assume below. Adapt every commit to the ACTUAL data, not to my assumptions. This is the "infrastructure correctness" mandate in action.

---

# COMMIT 1 — fix(screener): wire 1Y/10Y return columns from correct data source

## Problem

1Y and 10Y Returns show "—" in the grid. Data exists in the DB but the catalog query doesn't serve it.

## Investigation-driven fix

Based on Q1/Q2/Q5 results:

### If returns live on `mv_unified_funds` (most likely — `avg_annual_return_pct` from XBRL):

The `mv_unified_funds` view (migration 0078) consolidates 6 universe branches with prospectus stats. Per CLAUDE.md, `sec_fund_classes` has `avg_annual_return_pct` (from N-CSR XBRL, migration 0066). The MV likely carries this forward.

Fix: ensure the catalog query builder's SELECT list includes the return column(s) from `mv_unified_funds`, and the response schema `UnifiedFundItem` has corresponding fields.

The grid currently renders columns `1Y RET` and `10Y RET`. Map these to:
- `1Y RET` → `avg_annual_return_pct` (if that's what the XBRL data represents) OR `sharpe_1y`-derived annualized return if a separate return column exists
- `10Y RET` → may not exist in current data (XBRL prospectus returns are often inception-to-date or specific periods). If 10Y doesn't exist, show "—" but with a tooltip "10Y data not available" instead of silently showing "—".

### If returns live on `fund_risk_metrics` (computed by risk_calc worker):

The `fund_risk_metrics` hypertable might have computed annualized return fields. Check Q2/Q5 output. If yes, surface them via `mv_fund_risk_latest` (which Session 2.B already JOINs).

### If returns live on `sec_fund_prospectus_returns`:

Per CLAUDE.md, this is a global table with prospectus-reported returns. If the catalog doesn't JOIN it, add the JOIN. But be careful — this table might have multiple rows per fund (different periods, different share classes). Need a single representative return per fund.

**The commit MUST include the Q1/Q2/Q5 output in the commit body** so the data archaeology is permanently documented.

## Verification

1. `POST /screener/catalog` response includes return values (not all NULL/None)
2. Grid shows actual numbers in 1Y RET column for funds that have data
3. Grid shows "—" ONLY for funds that genuinely lack return data (with tooltip explaining why)
4. Numbers are in the correct scale (e.g., 12.5 for 12.5% annual return, not 0.125)
5. `make test` green

---

# COMMIT 2 — fix(screener): expense ratio scale correction

## Problem

ER% shows "0.00" for almost every row. Impossible — no fund has a 0% expense ratio. Either:
- (a) The backend sends the value as a tiny decimal (0.0075 for 0.75%) and the frontend rounds to 2 decimal places → "0.01" or "0.00"
- (b) The column is NULL for most rows and the frontend shows "0.00" instead of "—"
- (c) The backend divides by 100 before sending (0.0075 / 100 = 0.0000075 → "0.00")

## Investigation-driven fix

Based on Q3 output:

### If `expense_ratio_pct` is stored as 0.75 (meaning 0.75%):

The frontend should display it as `0.75%`. Use `formatNumber(value, 2) + "%"` — NOT `formatPercent(value)` which would show `75.00%`.

Check the frontend DataGrid column rendering for ER%:
- If it uses `formatPercent(value)` → that's the bug. `formatPercent(0.0075)` = `0.75%` which is correct IF the stored value is 0.0075. But if stored as 0.75, `formatPercent(0.75)` = `75.00%` which is wrong.
- If it uses `formatNumber(value, 2)` → should show `0.75` which needs the `%` suffix added.

**The correct pipeline depends on what Q3 reveals.** Read the data, then fix the pipeline.

### If `expense_ratio_pct` is mostly NULL:

The data isn't populated for most funds. This is a data quality issue from the XBRL enrichment pipeline (migration 0066). The frontend should show "—" for NULL (not "0.00"). Check if the frontend defaults NULL to 0.

## Deliverable

1. Fix the scale in the backend response schema OR in the frontend display — wherever the conversion is wrong
2. NULL values display as "—" (em-dash), not "0.00"
3. Non-NULL values display as "X.XX%" with correct magnitude (0.75% for a 0.75% expense ratio, not 75% or 0.0075%)

**Include Q3 output in the commit body** documenting what the actual DB values are.

## Verification

1. Funds with known expense ratios show correct values (e.g., Vanguard index funds ~0.03-0.20%)
2. NULL expense ratios show "—"
3. No "0.00" for rows that actually have data
4. Scale is correct: a fund with 0.75% ER shows "0.75%", not "75%" or "0.01%"

---

# COMMIT 3 — refactor(screener): replace TREND sparkline column with SCORE numeral

## Problem

The TREND column shows a NAV sparkline via batch endpoint. This feature:
1. Was never part of the planned terminal scope
2. Shows "trend" which sounds like speculation, conflicting with the deterministic ELITE ranking based on composite_score
3. Provides less actionable information than the actual SCORE number that drives ELITE ranking

The user explicitly said: "Melhor seria que nessa coluna traga o Score do fundo."

## Deliverable

### Replace sparkline with score display

In `TerminalDataGrid.svelte`:

1. Remove the TREND column header, replace with `SCORE`
2. Remove the sparkline Canvas rendering for this column
3. Remove the batch sparkline fetch trigger (the sparkline endpoint call, the debounce, the cache Map)
4. Render the composite score as a colored number:

```svelte
<div class="score-cell" class:score-high={score >= 70} class:score-mid={score >= 40 && score < 70} class:score-low={score < 40}>
  {score != null ? formatNumber(score, 1) : "—"}
</div>
```

Color coding:
- `score >= 70` → `var(--terminal-status-success)` (green) — high quality
- `score >= 40 && score < 70` → `var(--terminal-accent-amber)` (amber) — moderate
- `score < 40` → `var(--terminal-status-error)` (red) — low quality / concern

5. Score data comes from `asset.manager_score` (already in the response from `mv_fund_risk_latest` JOIN — verify field name with Q6 output)

### Column width

SCORE column: fixed 56px (enough for "100.0" in monospace). Right-aligned, tabular-nums.

### What happens to sparklines

The sparkline batch endpoint (`POST /screener/sparklines`) and the Canvas drawing code stay in the codebase — they're consumed by other surfaces (Focus Mode vitrine, future portfolio live workbench). Only the DataGrid column stops rendering sparklines. Do NOT delete the endpoint or the `drawSparkline` function.

## Verification

1. SCORE column shows numbers (e.g., "51.7", "65.2", "38.9") with color coding
2. Green for ≥70, amber for 40-69, red for <40
3. NULL scores show "—"
4. Column header reads "SCORE"
5. No sparkline Canvas elements in the DataGrid rows
6. Batch sparkline endpoint still works if called directly (not broken, just not called by DataGrid)
7. Score values match Q6 output ranges (median ~51.7 per the quant engine report)

---

# COMMIT 4 — feat(screener): score composition module in FocusMode

## Problem

FocusMode opens EntityAnalyticsVitrine which shows 7 analytics modules (risk stats, drawdown, capture, rolling returns, distribution, eVestment, insider sentiment). None of them show the SCORE COMPOSITION — the breakdown of WHY a fund has its composite score. This is the most actionable piece of information for an institutional analyst deciding whether to approve a fund.

## Deliverable

### New module: ScoreCompositionPanel

Add `frontends/wealth/src/lib/components/analytics/entity/ScoreCompositionPanel.svelte`:

The panel shows a horizontal bar chart (or radar chart if ≤6 components) breaking down the composite score into its components:

```typescript
interface ScoreComponent {
  name: string;       // "Return Consistency", "Risk-Adjusted Return", etc.
  weight: number;     // 0.20, 0.25, etc.
  value: number;      // component raw score (0-100)
  weighted: number;   // weight * value (contribution to composite)
}
```

The 6 default components per CLAUDE.md scoring_service.py:
- Return Consistency (0.20)
- Risk-Adjusted Return (0.25)
- Drawdown Control (0.20)
- Information Ratio (0.15)
- Flows Momentum (0.10)
- Fee Efficiency (0.10)

### Layout

```
SCORE COMPOSITION                    COMPOSITE: 65.2
┌─────────────────────────────────────────────────┐
│ Risk-Adj Return  ■■■■■■■■■■■■■■■░░░  72  (18.0) │
│ Drawdown Control ■■■■■■■■■■■░░░░░░░  58  (11.6) │
│ Return Consist.  ■■■■■■■■■■■■░░░░░░  62  (12.4) │
│ Information Ratio■■■■■■■■■░░░░░░░░░  55  ( 8.3) │
│ Fee Efficiency   ■■■■■■■■■■■■■■■■░░  85  ( 8.5) │
│ Flows Momentum   ■■■■■■░░░░░░░░░░░░  32  ( 3.2) │
└─────────────────────────────────────────────────┘
                                    SUM:     62.0
```

Each bar:
- Width proportional to `value` (0-100 scale → 0-100% bar fill)
- Color: component `value >= 70` → green, `40-69` → amber, `<40` → red
- Right-aligned numbers: raw score + (weighted contribution)
- Header shows composite score prominently

### Data source

The entity analytics endpoint (`/entity-analytics/{id}`) should already return scoring data. Investigate:
- Does the response include score component breakdown?
- If not, does `fund_risk_metrics` store individual component scores?
- If not, the score composition needs to be computed on-the-fly from the scoring_service inputs (sharpe, drawdown, etc.) — more complex but doable.

### Integration into EntityAnalyticsVitrine

Add `ScoreCompositionPanel` as the FIRST module in the vitrine cascade (before risk stats). The score composition is the most important summary view — it answers "is this fund good and WHY" in one glance.

If the vitrine currently has 7 modules, it becomes 8. The cascade timing (choreo slots) accommodates this — the stagger pattern from Part A handles N modules.

### Styling

Terminal-native horizontal bars:
- Bar track: `var(--terminal-bg-panel-raised)`, 1px hairline border
- Bar fill: solid color matching the score threshold
- Labels: monospace, `var(--terminal-text-10)`, right-aligned values
- Header: `SCORE COMPOSITION` in uppercase, `var(--terminal-text-14)`, with composite score in `var(--terminal-accent-amber)` at the right

### If score components are NOT available in the data

If investigation reveals that individual component scores are not stored (only the composite), the panel shows a simplified view:

```
COMPOSITE SCORE: 65.2

Component weights (scoring model):
  Risk-Adjusted Return  25%
  Return Consistency    20%
  Drawdown Control      20%
  Information Ratio     15%
  Flows Momentum        10%
  Fee Efficiency        10%

Individual component scores not available.
Run risk_calc worker with --verbose to populate.
```

This is a degraded but honest display. Under the mandate, showing "data not available" is better than showing nothing or showing fake data. The component scores will populate once the Tiingo migration fixes the score inputs.

## Verification

1. Open FocusMode on a fund with a composite score → ScoreCompositionPanel renders as first module
2. Bar lengths match the component values
3. Colors match thresholds (green/amber/red)
4. Weighted contributions sum to approximately the composite score
5. Funds without score data show the degraded view
6. `svelte-check` clean on new file

---

# COMMIT 5 — refactor(screener): filters collapsed by default with accordion toggle

## Problem

All filter sections (UNIVERSE, STRATEGY, GEOGRAPHY, METRICS, MANAGER) are expanded by default, requiring a scrollbar in the filter sidebar. On 13" displays this pushes metric filters out of view. The sidebar should maximize data density by collapsing sections and letting the user expand what they need.

## Deliverable

### Accordion pattern in TerminalScreenerFilters

Each filter section gets a collapsible header:

```svelte
{#each filterSections as section (section.id)}
  <div class="filter-section">
    <button
      class="filter-section-header"
      onclick={() => toggleSection(section.id)}
      aria-expanded={expandedSections.has(section.id)}
    >
      <span class="filter-section-title">{section.title}</span>
      <span class="filter-section-chevron" class:expanded={expandedSections.has(section.id)}>
        ▸
      </span>
    </button>
    {#if expandedSections.has(section.id)}
      <div class="filter-section-body" in:slide={{ duration: 150 }}>
        <!-- section content -->
      </div>
    {/if}
  </div>
{/each}
```

### Default state

```typescript
let expandedSections = $state(new Set<string>([]));
// ALL collapsed by default. User clicks to expand.
```

The ELITE chip stays OUTSIDE the accordion — it's a top-level toggle, always visible, not collapsible.

### Active filter indicator

When a section is collapsed BUT has active filters, show a count badge on the section header:

```svelte
<span class="filter-section-title">
  STRATEGY
  {#if activeStrategyCount > 0}
    <span class="filter-active-count">{activeStrategyCount}</span>
  {/if}
</span>
```

Badge: small circle with count, `var(--terminal-accent-cyan)` background, monospace number. Tells the user "this section has N active filters" without needing to expand it.

### Styling

- Section header: 28px height, monospace uppercase, `var(--terminal-fg-secondary)`, hover → `var(--terminal-fg-primary)`, cursor pointer
- Chevron: `▸` rotates to `▾` when expanded (CSS transform or content swap)
- Section body: `slide` transition 150ms for smooth expand/collapse
- Active count badge: inline, 16px circle, `var(--terminal-accent-cyan)` bg, `var(--terminal-bg-void)` text, font-size `var(--terminal-text-10)`

### "Expand All" / "Collapse All" controls

Add two small action links next to the "FILTERS" sidebar title:

```svelte
<div class="filter-sidebar-header">
  <span class="filter-sidebar-title">FILTERS</span>
  <div class="filter-sidebar-actions">
    <button class="filter-action" onclick={expandAll}>ALL</button>
    <button class="filter-action" onclick={collapseAll}>NONE</button>
  </div>
</div>
```

## Verification

1. Open screener → all filter sections collapsed, ELITE chip visible at top
2. Click STRATEGY → section expands with slide animation
3. Select "Equity" → collapse STRATEGY → badge shows "1" on the header
4. Click "ALL" → all sections expand
5. Click "NONE" → all sections collapse
6. On 13" display: entire filter sidebar visible without internal scrollbar when collapsed
7. Active filters still work when their section is collapsed (the filter state persists, only the UI is hidden)

---

# COMMIT 6 — test(screener): data accuracy validation + visual smoke test

## Deliverable

### Data accuracy validation (mandatory — not just visual check)

Run these verification queries against the local dev DB AND compare with what the frontend displays:

```sql
-- Pick 5 specific funds by ticker
SELECT
  u.external_id AS ticker,
  u.name,
  u.expense_ratio_pct,
  u.avg_annual_return_pct,
  r.manager_score,
  r.sharpe_1y,
  r.max_drawdown_1y,
  r.elite_flag,
  r.elite_rank_within_strategy
FROM mv_unified_funds u
LEFT JOIN mv_fund_risk_latest r ON r.instrument_id = u.instrument_id
WHERE u.external_id IN ('VDIPX', 'FXAIX', 'VFIAX', 'FBGRX', 'PRLAX')
ORDER BY u.external_id;
```

Open the screener in browser. Find these 5 funds. Compare EVERY number:
- ER% in grid matches `expense_ratio_pct` from DB (with correct scale)
- 1Y RET in grid matches `avg_annual_return_pct` from DB (with correct scale)
- SCORE in grid matches `manager_score` from DB
- ELITE badge shows on funds where `elite_flag = true`

If ANY number doesn't match, the data pipeline has a remaining bug. Fix it BEFORE shipping this commit.

### Visual smoke test

Verify ALL previous features still work:
1. Infinite scroll loads beyond 200
2. Manager typeahead with chips
3. Metric range filters
4. ELITE filter chip
5. FocusMode opens with score composition as first module
6. Filters collapse/expand with active count badges
7. SCORE column shows colored numbers (green/amber/red)
8. ER% shows correct values (not 0.00 for non-null rows)
9. 1Y RET shows actual return values for funds that have data
10. Keyboard shortcuts all still work

### Update SCREENER_SMOKE_CHECKLIST.md

Add data accuracy items (36-45) covering the specific fund comparisons and scale verifications.

## Verification

1. Data accuracy: 5 funds verified number-by-number against DB
2. All 10 visual smoke items pass
3. Checklist updated
4. `svelte-check` clean
5. `pnpm build` clean
6. `make test` green

---

# FINAL FULL-TREE VERIFICATION

1. `svelte-check` → 0 new errors
2. `pnpm --filter netz-wealth-os build` → clean
3. `make test` → green
4. `make lint` → clean
5. Data accuracy: returns, ER%, SCORE verified against DB for 5 specific funds
6. SCORE column replaces TREND with correct color coding
7. FocusMode score composition renders (with bars or degraded message)
8. Filters collapse by default on page load
9. Active filter count badges show on collapsed sections
10. Infinite scroll, manager filter, metric ranges, ELITE all still work

# SELF-CHECK

- [ ] Q1-Q6 SQL investigation run BEFORE any code, outputs captured
- [ ] Commit 1: returns column wired from correct source, numbers match DB
- [ ] Commit 2: ER% scale fixed, NULL shows "—", non-null shows correct percentage
- [ ] Commit 3: TREND sparkline gone, SCORE number with color coding in its place
- [ ] Commit 4: ScoreCompositionPanel in FocusMode showing component breakdown
- [ ] Commit 5: all filter sections collapsed by default, active count badges, expand/collapse works
- [ ] Commit 6: 5 funds verified number-by-number against DB, zero discrepancies
- [ ] Sparkline batch endpoint NOT deleted (used by other consumers)
- [ ] drawSparkline function NOT deleted (used by other consumers)
- [ ] Terminal tokens only, formatters only, no hex, no localStorage

# VALID ESCAPE HATCHES

1. Return columns do NOT exist anywhere in the joinable tables → report Q5 output, show that no return data is available in the current schema. Display "—" with tooltip "Return data pending — Tiingo migration will populate" and note in commit body.
2. `expense_ratio_pct` is NULL for 95%+ of rows → this is a data population issue, not a display bug. Show "—" for NULL. Fix the display for the 5% that DO have data. Note in commit body.
3. Score component individual values are NOT stored in `fund_risk_metrics` → use the degraded ScoreCompositionPanel view (weights-only, no bars). Note that full component scores require a worker enhancement (out of scope for this sprint).
4. `in:slide` transition from `svelte/transition` conflicts with the virtual scroll in the filter sidebar → use CSS `max-height` transition instead of Svelte `slide`.
5. The data accuracy check reveals a systematic offset (all values off by a factor) → fix the factor, re-run, re-verify. Do NOT ship until the numbers match.

# NOT VALID ESCAPE HATCHES

- "Returns data isn't important, analysts use Sharpe instead" → NO, the user explicitly flagged returns as a trust issue. If data exists in the DB, show it. If it doesn't, show "—" honestly.
- "0.00% is close enough for ER display" → NO, 0.00% means "free fund" which is a LIE. Show the actual value or "—".
- "Sparklines are more visually appealing than a number" → NO, the user explicitly said "trend soa como especulação" and asked for SCORE. Ship SCORE.
- "Accordion is over-engineering for 5 filter sections" → NO, user explicitly said "fica muito mais elegante com filtros colapsados". Ship collapsed.

# REPORT FORMAT

1. Six commit SHAs with messages
2. **Q1-Q6 SQL investigation output** — full, unedited. This is the most important part of the report — the data archaeology that justifies every fix.
3. Per commit: files modified, fix applied, verification
4. Commit 1 extra: which table/column the returns came from, sample values
5. Commit 2 extra: what `expense_ratio_pct` actually stored (Q3 output), scale fix applied
6. Commit 3 extra: score distribution in the grid (how many green/amber/red)
7. Commit 4 extra: screenshot or description of ScoreCompositionPanel in FocusMode (bars or degraded view, which outcome)
8. Commit 6 extra: 5-fund accuracy comparison table (DB value vs displayed value per column)
9. Full-tree verification

Begin by reading this brief, then run Q1-Q6 on the local dev DB. Record outputs. THEN start commit 1 — not before.
