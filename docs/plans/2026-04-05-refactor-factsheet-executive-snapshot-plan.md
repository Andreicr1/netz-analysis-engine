---
title: "Refactor: Fund Fact Sheet — Executive Snapshot Consolidation"
type: refactor
status: active
date: 2026-04-05
---

# Refactor: Fund Fact Sheet — Executive Snapshot Consolidation

## Overview

Redesign the Fund Fact Sheet from a dense 2-column analytical page into a focused "Executive Snapshot" — full-width hybrid layout, token-driven CSS, simplified holdings, benchmark integration, and Bloomberg-style header. Consolidates the best of the current implementation (analytical charts, scoring radar, peer boxplot) with Figma design improvements (KPI prominence, Investment Objective highlight, institutional footer).

## Problem Statement / Motivation

The current fact sheet has:
- **Hardcoded hex values** in `factsheet.css` (lines 9-17) duplicating `tokens.css` — violates D4/D5 design decisions
- **2-column sticky layout** that wastes space — right column (firm/strategy/team) is secondary info occupying 30% of viewport
- **50 holdings + Reverse Lookup** — too much detail for an executive view; belongs in Analytics tab
- **No benchmark comparison** — NAV chart shows single series, returns table has no benchmark column
- **No NAV/1D Change KPIs** — analyst's first question ("what's the price?") isn't answered at a glance
- **Investment Objective buried** in sidebar — should be the first narrative element

## Proposed Solution

Three-phase refactoring following user's rigid execution plan:

**Phase 1 — Bloomberg Header + Token Migration:** Eliminate all hardcoded hex from `factsheet.css`, migrate to Tailwind utilities with `--ii-*` tokens. Redesign header with fund name large + ticker prominent right + Print/PDF actions.

**Phase 2 — Simplification:** Holdings cut to 10 (read-only table). Remove ReverseLookupPanel, ContextPanel import, and all click interactivity. Remove 2-column layout entirely.

**Phase 3 — Analytical Motor:** Keep differentiating charts (Scoring Radar, Peer Boxplot, Sector Treemap, Sector Evolution). Add benchmark line to NAV chart. Add benchmark column to returns table. Move Team/Firm to institutional footer.

## Technical Considerations

### Token Architecture
- `@investintell/ui` tokens use `--ii-*` prefix (dark-first `:root`, `.light` override)
- shadcn bridge: `--background`, `--foreground`, `--card`, `--primary`, `--muted`, `--muted-foreground` all alias `--ii-*`
- Tailwind classes (`bg-background`, `text-foreground`, `bg-card`, `text-muted-foreground`, `border-border`) map to shadcn bridge tokens
- Chart palette tokens exist: `--ii-chart-1` through `--ii-chart-5` + `--ii-chart-accent`
- Print: use `[data-theme="light"]` token set inside `@media print` — no dedicated print palette needed

### Backend Data Gaps
- **1D Change:** Compute on frontend from `nav_history` last 2 entries. If < 2 entries, show em-dash. No backend change needed.
- **Latest NAV:** Derive from `nav_history[nav_history.length - 1].nav`. No backend change needed.
- **Benchmark:** Requires backend work — not in scope for this refactor. Add `benchmark_history` field to `FundFactSheet` in a follow-up sprint. For now, the returns table and NAV chart render fund-only data; the layout reserves space for benchmark columns (empty state ready).
- **Holdings limit:** Change backend `[:50]` to `[:10]` in `screener.py` fact-sheet endpoint. The Analytics tab will have its own endpoint for full holdings.

### Component Removal
- `ReverseLookupPanel` — only consumer is fact sheet page. Remove import + `ContextPanel` usage. Keep the component file for future Analytics tab use.
- `ContextPanel` import — remove from fact sheet only (used elsewhere in the app).

### Print Strategy
- `@media print` applies `[data-theme="light"]` on `.fs-container` to inherit light tokens
- Minimal print-specific overrides: grid collapse, section break-inside, chart height constraints
- ECharts hardcoded colors in chart components are a known issue — defer to a chart-theme-awareness sprint

## Acceptance Criteria

### Phase 1 — Header + Tokens
- [x] `factsheet.css` contains ZERO hardcoded hex values (grep verification: `grep -c '#[0-9a-fA-F]' factsheet.css` = 0, excluding `@media print` light theme reference via token class)
- [x] All styling uses Tailwind utility classes with `--ii-*` CSS custom properties via shadcn bridge (`bg-background`, `text-foreground`, `bg-card`, `text-muted-foreground`, `border-border`)
- [x] Header: fund name (large, left) + ticker (prominent, right, mono font, accent bg)
- [x] Header: manager name + universe badge above fund name
- [x] Header: "Print Fact Sheet" and "PDF" action buttons top-right
- [x] KPI cards full-width: NAV, 1D Change (green/red conditional), AUM, Expense Ratio, Strategy
- [x] 1D Change computed from last 2 `nav_history` entries, colored with `text-[--ii-success]` / `text-[--ii-danger]`
- [x] "As of {date}" displayed in header (from latest nav_date)

### Phase 2 — Simplification
- [x] Holdings table shows exactly 10 rows (Holding, Sector, Weight) — read-only, no click actions
- [x] Backend `screener.py` fact-sheet query changed from `[:50]` to `[:10]`
- [x] `ReverseLookupPanel` import removed from fact sheet page
- [x] `ContextPanel` import removed from fact sheet page
- [x] All Reverse Lookup state variables (`rlOpen`, `rlTarget`, `openReverseLookup`) removed
- [x] 2-column grid layout (`grid-template-columns: 2fr 0.85fr`) eliminated
- [x] No sticky right column (`position: sticky` on `.fs-col-right` removed)
- [x] Layout: hybrid — full-width header/KPIs, then single-column flow with CSS Grid for chart pairs

### Phase 3 — Analytical Motor
- [x] Investment Objective promoted: immediately below KPI cards, before charts. Uses `bg-[--ii-surface-accent]` with `border border-[--ii-border-accent]` subtle highlight
- [x] Scoring Radar + Peer Boxplot side-by-side (CSS Grid 2-col)
- [x] NAV Performance chart full-width (benchmark line deferred — layout ready)
- [x] Sector Treemap + Sector Evolution side-by-side (CSS Grid 2-col)
- [x] Annual Returns table with columns: Period, Fund, Benchmark (em-dash placeholder), +/- (em-dash placeholder)
- [x] Share Classes table retained (Class, Ticker, ER%, 1Y Ret, Net Assets)
- [x] Management Team + Firm Overview moved to bottom as "Institutional Footer" in a 2-col grid
- [x] All chart pairs collapse to single-column on `max-width: 768px`
- [x] `@media print` uses `[data-theme="light"]` token set, single-column, `break-inside: avoid`

## Implementation Phases

### Phase 1: Bloomberg Header + Token Migration

**Files modified:**
- `frontends/wealth/src/routes/(app)/screener/fund/[id]/factsheet.css` — full rewrite to Tailwind utilities
- `frontends/wealth/src/routes/(app)/screener/fund/[id]/+page.svelte` — header restructure, KPI cards

**Steps:**
1. Rewrite `factsheet.css`: remove all 380 lines of hardcoded CSS. Replace with minimal Tailwind `@apply` rules for print-only and chart container sizing. All component styling moves to utility classes in the Svelte template.
2. Restructure header in `+page.svelte`:
   - Top row: universe badge + manager name (left) | Print/PDF buttons (right)
   - Main row: fund name `text-3xl font-extrabold` (left) | ticker in `font-mono text-xl text-[--ii-brand-primary] bg-[--ii-surface-accent] px-3 py-1 rounded-md` (right)
   - "As of" date below ticker
3. Rebuild KPI cards: 5-card grid (`grid-cols-5`), each with label + value. 1D Change logic:
   ```js
   const latestNav = nav_history.at(-1)?.nav ?? null;
   const prevNav = nav_history.at(-2)?.nav ?? null;
   const change1d = (latestNav && prevNav) ? (latestNav - prevNav) / prevNav : null;
   ```
4. Print/PDF buttons: `window.print()` for both (PDF = browser "Save as PDF"). Simple `<button>` elements with printer/download icons.

### Phase 2: Simplification

**Files modified:**
- `frontends/wealth/src/routes/(app)/screener/fund/[id]/+page.svelte` — remove RL, simplify holdings
- `backend/app/domains/wealth/services/screener.py` — holdings limit `[:10]`

**Steps:**
1. Remove from `+page.svelte`:
   - `import ReverseLookupPanel` line
   - `import { ..., ContextPanel } from "@investintell/ui"` — remove `ContextPanel` from import
   - `rlOpen`, `rlTarget` state variables
   - `openReverseLookup()` function
   - Entire `<ContextPanel>` block at bottom
   - `<style>` block with `.rl-container`
   - `<button class="fs-holding-btn">` wrappers in holdings table — replace with plain `<td>`
2. Holdings table: render only `top_holdings` (now 10 items). Columns: Holding, Ticker (new — from `h.ticker` if available), Weight.
3. Backend: in `screener.py`, find the `[:50]` slice on top_holdings in the fact-sheet endpoint and change to `[:10]`.
4. Remove 2-column grid: eliminate `.fs-grid`, `.fs-col-left`, `.fs-col-right` structure. Replace with single `<div>` flow.

### Phase 3: Analytical Motor + Layout

**Files modified:**
- `frontends/wealth/src/routes/(app)/screener/fund/[id]/+page.svelte` — section reordering, grid pairs, footer

**Steps:**
1. **Investment Objective** — new section immediately after KPI cards:
   ```svelte
   {#if strategy_narrative}
   <section class="rounded-xl bg-[--ii-surface-accent] border border-[--ii-border-accent] p-6 mb-8">
     <h3 class="text-xs font-semibold uppercase tracking-wide text-[--ii-text-muted] mb-2">Investment Objective</h3>
     <p class="text-sm leading-relaxed text-[--ii-text-secondary]">{strategy_narrative}</p>
   </section>
   {/if}
   ```
2. **Chart pairs** — CSS Grid containers:
   - Row 1: `grid grid-cols-1 md:grid-cols-2 gap-6` → Scoring Radar | Peer Boxplot
   - Row 2: Full-width → NAV Performance chart (height 350px)
   - Row 3: `grid grid-cols-1 md:grid-cols-2 gap-6` → Sector Treemap | Sector Evolution
3. **Annual Returns table** — add Benchmark and +/- columns (em-dash placeholders until backend provides data):
   ```
   | Period | Fund | Benchmark | +/- |
   | 2025   | +8.2%| —         | —   |
   ```
4. **Institutional Footer** — move Team + Firm to bottom in `grid grid-cols-1 md:grid-cols-2 gap-8`:
   - Left: Firm Overview (description + website)
   - Right: Management Team (cards)
5. **Section collapse** — wrap each section in `{#if data}` blocks so empty sections are hidden entirely (no "not available" walls for sparse-data universes like UCITS/private).
6. **Print styles** — minimal `factsheet.css` retained for:
   ```css
   @media print {
     .fs-container { color-scheme: light; }
     .fs-container * { color: var(--ii-text-primary); }
     .fs-no-print { display: none !important; }
     .fs-section { break-inside: avoid; }
   }
   ```

## Section Order (Final Layout)

```
1. Header (fund name, ticker, manager, universe badge, as-of date, Print/PDF)
2. KPI Cards (NAV, 1D Change, AUM, Expense Ratio, Strategy)
3. Investment Objective (accent panel)
4. Scoring Radar + Peer Boxplot (side-by-side)
5. NAV Performance Chart (full-width, benchmark-ready)
6. Sector Treemap + Sector Evolution (side-by-side)
7. Annual Returns Table (Fund + Benchmark placeholder + +/-)
8. Top 10 Holdings (Holding, Ticker, Weight)
9. Share Classes (Class, Ticker, ER%, 1Y Ret, Net Assets)
10. Institutional Footer: Firm Overview | Management Team
```

## Dependencies & Risks

| Risk | Mitigation |
|------|-----------|
| ECharts hardcoded hex in chart components won't respect token migration | Out of scope — chart internals keep current colors. Only the page-level CSS migrates to tokens. Chart theme awareness is a separate sprint. |
| Benchmark data not available in backend | Layout reserves space with em-dash placeholders. Follow-up sprint adds `benchmark_history` to `FundFactSheet` via strategy-to-benchmark mapping in ConfigService. |
| Print quality degradation from token migration | Test print output explicitly. `@media print` applies light theme tokens. Charts will still render with dark colors on print — known limitation. |
| Holdings ticker field may not exist on all N-PORT data | Show em-dash if `h.ticker` is null/undefined. |

## Future Considerations (Explicitly Deferred)

- **Benchmark integration:** Add `strategy_label -> benchmark_ticker` mapping to ConfigService, `benchmark_history` field to `FundFactSheet`, benchmark line to `NavPerformanceChart`, benchmark column values to returns table.
- **Chart theme awareness:** Make ECharts options read from CSS custom properties instead of hardcoded hex.
- **Backend PDF generation:** Playwright-rendered institutional PDF (vs. browser print-to-PDF).
- **Reverse Lookup in Analytics tab:** Move the `ReverseLookupPanel` to the Analytics sub-page with full holdings table + concentration analysis.
- **Loading skeleton:** Progressive rendering with streaming for slow SEC data gathering.

## Sources & References

### Internal References
- Current fact sheet page: `frontends/wealth/src/routes/(app)/screener/fund/[id]/+page.svelte`
- Current CSS: `frontends/wealth/src/routes/(app)/screener/fund/[id]/factsheet.css`
- Token system: `packages/investintell-ui/src/lib/styles/tokens.css`
- Backend fact sheet endpoint: `backend/app/domains/wealth/services/screener.py` (line ~2131)
- Benchmark resolver: `backend/app/domains/wealth/services/benchmark_resolver.py`
- Design decisions D4/D5: `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md`

### Design Input
- Figma mockup: Fund Fact Sheet dark mode (user-provided screenshot, 2026-04-05)
- Figma variables: `docs/ux/Investintell Variables.json`
