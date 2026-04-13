# Terminal Harmonization Plan

**Date:** 2026-04-13
**Status:** Ready for execution
**Depends on:** Phase 4 (Builder) + Phase 5 (Live) + regime fixes (PRs #139-#140) -- all merged
**Goal:** Eliminate visual debt across Builder, Screener, and Live; extract missing Layer 2/3 primitives; sanitize all quant jargon leaks; wire SSE sanitization gaps.

---

## Problem Statement

Phases 4-5 were executed before Phase 1 primitives were fully extracted. Result: three terminal pages speak two visual dialects. The Screener has 115 hardcoded hex values and uses Urbanist font. The Builder's CalibrationPanel is a legacy (app) component transplanted into the terminal. Lightweight-charts components have ~45 hardcoded hex values with zero token consumption. 22 quant jargon leaks exist across 16 files.

---

## Session Structure (6 sessions, ordered by dependency)

### Session H0 -- Missing Primitives + SSE Sanitization
**Scope:** Extract Layer 2/3 primitives from existing Builder/Live code + wire sanitize_payload() gaps
**Risk:** LOW -- extracting existing patterns, not inventing new ones

#### H0-A: Layer 2 Layout Primitives

Create `frontends/wealth/src/lib/components/terminal/layout/`:

| Component | Extract From | Behavior |
|---|---|---|
| `Panel.svelte` | Builder tab panels, Live panels | Slot-based: header/body/footer. Uses `--terminal-bg-panel`, `--terminal-border-hairline`, 0 radius. Props: `flush` (no padding), `scrollable` |
| `PanelHeader.svelte` | Builder tab headers, Live section headers | 28px height, monospace uppercase 9px, `--terminal-fg-tertiary`, optional right-slot for actions |
| `SplitPane.svelte` | Builder 2-column (40/60), Live 3-column | CSS grid wrapper with named areas. Props: `columns` (template string), `gap` |
| `StackedPanels.svelte` | Live bottom row | Vertical stack with hairline dividers between children |

#### H0-B: Layer 3 Data Primitives

Create `frontends/wealth/src/lib/components/terminal/data/`:

| Component | Extract From | Behavior |
|---|---|---|
| `StatSlab.svelte` | PortfolioSummary KPI items, BacktestTab metrics | Label (9px mono caps) + Value (14px mono) + optional Delta. Props: `label`, `value`, `delta`, `deltaColor` |
| `KeyValueStrip.svelte` | MacroRegimePanel rows, AdvisorTab metrics | Horizontal strip of key-value pairs with consistent spacing |
| `LiveDot.svelte` | TerminalStatusBar (inline), DriftMonitorPanel dots | 6px indicator dot. Props: `status: "success"|"warn"|"error"|"muted"` maps to `--terminal-status-*` |

#### H0-C: Lightweight-Charts Factory

Create `packages/investintell-ui/src/lib/charts/terminal-lw-options.ts`:

```
createTerminalLightweightChartOptions() -- reads --terminal-* CSS custom properties
Returns: ChartOptions with layout, grid, crosshair, timeScale, rightPriceScale
Replaces: ~45 hardcoded hex values in TerminalPriceChart + TerminalResearchChart
```

Pattern: mirror `createTerminalChartOptions()` but for lightweight-charts API. Read tokens via `readTerminalTokens()` (already exists).

#### H0-D: SSE Sanitization Wiring

3 backend files need `sanitize_payload()` before publish:

| File | Current | Fix |
|---|---|---|
| `backend/app/domains/wealth/workers/drift_monitor.py` | Raw event emit | Import `sanitize_payload`, wrap before publish |
| `backend/vertical_engines/wealth/monitoring/alert_engine.py` | Raw event emit | Same |
| `backend/app/domains/wealth/services/rebalancing/preview_service.py` | Raw event emit | Same |

Add test: assert zero banned substrings from each emitter output.

#### H0 Exit Criteria
- All Layer 2/3 components render correctly in TerminalShell cage
- LW factory reads tokens, returns valid ChartOptions
- `make check` passes
- 3 SSE emitters route through `sanitize_payload()`

---

### Session H1 -- Quant Jargon Sanitization (all 22 leaks)
**Scope:** Fix all 22 jargon leaks across 16 files. Pure string replacements, zero logic changes.
**Risk:** LOW -- text-only changes

#### Terminal components (7 leaks):

| File | Line(s) | Current | Replacement |
|---|---|---|---|
| `terminal/builder/RiskTab.svelte` | 68 | `data: ["CVaR"]` | `data: ["Tail Loss"]` |
| `terminal/builder/RiskTab.svelte` | 183 | `ariaLabel="CVaR contribution..."` | `ariaLabel="Tail loss contribution..."` |
| `terminal/builder/AdvisorTab.svelte` | 144-149 | Raw API keys via `.replace(/_/g, " ")` | Label dictionary (map `cvar_*` to "Tail loss *") |
| `state/portfolio-workspace.svelte.ts` | 204 | `"Heuristic Recovery"` | `"Recovery"` |
| `terminal/builder/CascadeTimeline.svelte` | 38 | `aria-label="Optimizer cascade..."` | `"Construction phase timeline"` |
| `terminal/shell/TerminalTopNav.svelte` | 238 | `REGIME` | `MARKET` |
| `terminal/live/MacroRegimePanel.svelte` | 111 | `MACRO REGIME` | `MARKET CONDITIONS` |

#### Display mappings (3 leaks):

| File | Line(s) | Current | Replacement |
|---|---|---|---|
| `terminal/shell/TerminalContextRail.svelte` | 75 | display `"REGIME"` | `"ENVIRONMENT"` |
| `terminal/focus-mode/FocusMode.svelte` | 82 | display `"REGIME"` | `"ENVIRONMENT"` |
| `constants/regime.ts` | 3-8, 28 | `Risk On/Off/Crisis`, `CVaR tightened` | Match `taa.ts` labels, `Risk budget tightened` |

#### Legacy portfolio components (12 leaks):

| File | Line(s) | Current | Replacement |
|---|---|---|---|
| `portfolio/CalibrationPanel.svelte` | 334 | `"...defaults for CVaR..."` | `"...defaults for tail loss budget..."` |
| `portfolio/CalibrationPanel.svelte` | 343 | `"Maximum CVaR the optimizer..."` | `"Maximum tail loss (95% confidence)..."` |
| `portfolio/CalibrationPanel.svelte` | 410 | `"Black-Litterman blending"` | `"Expected return blending"` |
| `portfolio/CalibrationPanel.svelte` | 432-433 | `"GARCH forward volatility"`, `"GARCH(1,1)..."` | `"Forward-looking volatility"`, `"Use forward-looking conditional..."` |
| `portfolio/CalibrationPanel.svelte` | 467 | `"...close CVaR gaps"` | `"...close risk budget gaps"` |
| `portfolio/CalibrationPanel.svelte` | 474 | `"CVaR confidence level"` | `"Tail loss confidence level"` |
| `portfolio/CalibrationPanel.svelte` | 483 | `"Risk aversion (lambda)"` | `"Risk aversion"` |
| `portfolio/CalibrationPanel.svelte` | 497 | `"Manual Ledoit-Wolf shrinkage..."` | `"Covariance shrinkage override..."` |
| `portfolio/ConstructionNarrative.svelte` | 52 | `"Running CLARABEL optimizer cascade..."` | `"Optimizing portfolio allocation..."` |
| `model-portfolio/ConstructionAdvisor.svelte` | 266,318,387,399,434 | `CVaR` in labels | `Tail Loss` / `Tail Risk` |
| `model-portfolio/FundSelectionEditor.svelte` | 329 | `"4-phase CLARABEL cascade optimizer"` | `"portfolio will be re-optimized"` |
| `portfolio/live/TerminalAllocator.svelte` | 106 | `USE CLARABEL OPTIMIZER` | `OPTIMIZE ALLOCATION` |
| `model-portfolio/RebalancePreview.svelte` | 83,85 | `CVaR Limit Warning` | `Risk Limit Warning` |
| `portfolio/StressTestPanel.svelte` | 205 | `CVaR Stressed` | `Stressed Tail Loss` |
| `portfolio/StressCustomShockTab.svelte` | 79 | `Stressed CVaR` | `Stressed Tail Loss` |
| `research/terminal/TerminalResearchChart.svelte` | 271,301,288 | `GARCH VOL` | `CONDITIONAL VOL` / `FORWARD VOL` |

#### H1 Exit Criteria
- `grep -ri "cvar\|clarabel\|garch\b\|ledoit\|black.litterman\|marchenko" frontends/wealth/src/` returns zero hits in user-visible strings (comments OK)
- `make check` passes

---

### Session H2 -- Live Workbench Polish
**Scope:** Lightest debt surface (9 hex, 3 border issues). Validates H0 primitives work in real streaming context.
**Risk:** LOW

**Changes:**
1. `TerminalPriceChart.svelte` -- migrate ~20 JS hex + ~25 CSS hex to `createTerminalLightweightChartOptions()` from H0-C. Replace alien blue `#2d7ef7` with `--terminal-accent-cyan`.
2. `TerminalResearchChart.svelte` -- same migration. Remove `"Urbanist"` font declaration. Replace `.neg`/`.purple`/`.amber` utility classes with `--terminal-status-*` tokens.
3. `HoldingsTable.svelte` line 193 -- replace `border-bottom: 1px solid var(--terminal-fg-muted)` with `var(--terminal-border-hairline)`
4. `DriftMonitorPanel.svelte` line 248 -- same border fix
5. Refactor Live panels to compose from H0 `Panel`/`StatSlab`/`LiveDot` where applicable

#### H2 Exit Criteria
- Zero hardcoded hex in any Live component
- All tokens from `terminal.css`
- `pnpm check` passes in wealth frontend

---

### Session H3 -- Builder CalibrationPanel Terminal-ization
**Scope:** The biggest single visual debt item. CalibrationPanel uses `--ii-*` tokens, Urbanist font, rounded corners, `@investintell/ui` Select/Button.
**Risk:** MEDIUM -- must verify CalibrationPanel is not consumed by (app) routes

**Decision (2026-04-13):** Refactor in-place, NO fork. `(app)/` routes will become read-only (Phase 9), so maintaining a separate component is waste. CalibrationPanel gets terminal tokens directly.

**Changes (in-place or fork):**
1. Replace `font-family: "Urbanist"` with `var(--terminal-font-mono)` on root + all children (CalibrationSliderField, CalibrationSelectField)
2. Replace all `--ii-*` tokens with `--terminal-*` equivalents
3. Replace `border-radius: 6px/999px/4px` with `0`
4. Replace `@investintell/ui` `<Select>` with terminal-native `<select>` (match `builder-select` pattern)
5. Replace `@investintell/ui` `<Button>` with terminal-native buttons (match `rc-btn` pattern)
6. Replace `@investintell/ui` `<Tabs.Root>` with terminal tab pattern (match `builder-tab`)
7. Replace regime badge pill (999px) with square badge
8. Replace stress bar rounded track with flat track
9. Remove `:global` overrides from `builder/+page.svelte` lines 211-240 (no longer needed)
10. Replace `background: #141519` with `var(--terminal-bg-panel)`

**Also fix RiskTab factory bypass:**
- Refactor both chart options through `createTerminalChartOptions()` with grid overrides
- Add tooltip chrome (0 radius, no shadow)
- Wire choreo animation slots

#### H3 Exit Criteria
- CalibrationPanel visually indistinguishable from right-column Builder styling
- Zero `--ii-*` tokens in terminal context
- Zero `border-radius > 0` except native slider thumb
- RiskTab charts go through factory

---

### Session H4 -- Screener Token Migration
**Scope:** Heaviest rewrite (115 hex across 3 files + Urbanist font + Svelte 4 import)
**Risk:** MEDIUM -- large CSS surface area, but no logic changes

**Changes:**
1. `TerminalScreenerShell.svelte` -- replace all hex with `--terminal-*` tokens, replace `"Urbanist"` with `var(--terminal-font-mono)`
2. `TerminalScreenerFilters.svelte` -- replace ~40 hex values, replace font, replace `accent-color: #2d7ef7` with `--terminal-accent-cyan`, square the filter count badge
3. `TerminalDataGrid.svelte` -- replace ~35 hex values, replace font, migrate sparkline canvas colors to `readTerminalTokens()`
4. `+page.svelte` -- migrate `$app/stores` to `$app/state` (Svelte 5)
5. Fix `MonteCarloTab.svelte` line 156 -- `.toLocaleString()` to `formatNumber()`
6. Fix `BacktestTab.svelte` line 265 -- `font-size: 14px` to `var(--terminal-text-14)`

**Optional (lower priority):**
- Relocate screener components from `$lib/components/screener/terminal/` to `$lib/components/terminal/screener/` for directory consistency

#### H4 Exit Criteria
- Zero hardcoded hex in screener components
- `var(--terminal-font-mono)` on all screener roots
- `$app/state` import (Svelte 5)
- `pnpm check` passes

---

### Session H5 -- Cross-Page Navigation + Final Polish
**Scope:** Navigation flow improvements + remaining cosmetic fixes
**Risk:** LOW

**Changes:**
1. Add lifecycle forward links: Screener "Open in Builder" action, Builder "Back to Screener" link
2. Replace `window.location.href` with `goto()` in TerminalTopNav alert click (line 148)
3. Standardize row border treatment across all tables to `var(--terminal-border-hairline)`
4. Wire `svelteTransitionFor()` from choreo into key Svelte transitions (panel mount, tab switch)
5. Visual validation: browser test all 3 pages end-to-end

#### H5 Exit Criteria
- Lifecycle flow navigable in 3 clicks (Screener -> Builder -> Live)
- Consistent border treatment across all terminal tables
- `make check` passes
- Visual validation in browser confirms brutalist coherence

---

## Files Inventory (all sessions combined)

### New Files (H0):
- `frontends/wealth/src/lib/components/terminal/layout/Panel.svelte`
- `frontends/wealth/src/lib/components/terminal/layout/PanelHeader.svelte`
- `frontends/wealth/src/lib/components/terminal/layout/SplitPane.svelte`
- `frontends/wealth/src/lib/components/terminal/layout/StackedPanels.svelte`
- `frontends/wealth/src/lib/components/terminal/data/StatSlab.svelte`
- `frontends/wealth/src/lib/components/terminal/data/KeyValueStrip.svelte`
- `frontends/wealth/src/lib/components/terminal/data/LiveDot.svelte`
- `packages/investintell-ui/src/lib/charts/terminal-lw-options.ts`

### Modified Files (H1-H5, ~35 files):
**Jargon sanitization (16 files):** RiskTab, AdvisorTab, CascadeTimeline, portfolio-workspace.svelte.ts, TerminalTopNav, MacroRegimePanel, TerminalContextRail, FocusMode, regime.ts, CalibrationPanel, ConstructionNarrative, ConstructionAdvisor, FundSelectionEditor, TerminalAllocator, RebalancePreview, StressTestPanel, StressCustomShockTab, TerminalResearchChart

**Live charts (2 files):** TerminalPriceChart, TerminalResearchChart

**Live polish (2 files):** HoldingsTable, DriftMonitorPanel

**Builder (5 files):** CalibrationPanel, CalibrationSliderField, CalibrationSelectField, RiskTab, builder/+page.svelte

**Screener (4 files):** TerminalScreenerShell, TerminalScreenerFilters, TerminalDataGrid, terminal-screener/+page.svelte

**Backend SSE (3 files):** drift_monitor.py, alert_engine.py, preview_service.py

**Minor fixes (2 files):** MonteCarloTab, BacktestTab

---

## Validation Sequence (after all sessions)

```bash
# 1. Frontend checks
cd frontends/wealth && pnpm check && pnpm lint

# 2. Backend checks
make check

# 3. Jargon grep (zero hits expected in user-visible strings)
grep -ri "cvar\|clarabel\|garch\b\|ledoit\|black.litterman" frontends/wealth/src/ \
  --include="*.svelte" --include="*.ts" | grep -v "//\|<!--\|/\*"

# 4. Hex grep in terminal components (zero hits expected)
grep -rn "#[0-9a-fA-F]\{3,8\}" \
  frontends/wealth/src/lib/components/terminal/ \
  frontends/wealth/src/routes/\(terminal\)/ \
  --include="*.svelte" | grep -v "terminal.css\|choreo\|test"

# 5. Visual validation in browser (all 3 pages)
make dev-wealth
# Test: Screener -> Builder -> Live flow
# Verify: monospace font, 0 radius, terminal tokens, no blue accent
```
