# Netz Terminal Parity — Builder / Macro / Screener

**Date:** 2026-04-19
**Owner:** Andrei
**Scope decision locked:** Visual + interaction parity for the 3 remaining Figma pages (`Netz Terminal - Builder.html`, `Netz Terminal - Macro.html`, `Netz Terminal - Screener.html`). Terminal.html parity already landed via PRs #230–#234.
**Execution model:** 4–5 independently-mergeable sub-PRs sized for a single Opus session each. Sessions run in parallel with Gemini; do not cross-touch files outside the PR’s scope.

---

## 0. Ground truth & assumptions

- Figma bundle IS checked into repo at `docs/ux/Netz Terminal/`:
  - `Netz Terminal - Builder.html` + `builder.css` (726 lines) + `builder-app.jsx` (381) + `builder-data.jsx` + `builder-preview.jsx`.
  - `Netz Terminal - Macro.html` + `macro.css` (629) + `macro-app.jsx` (695) + `macro-data.jsx`.
  - `Netz Terminal - Screener.html` + `screener.css` (398) + `screener-app.jsx` (602) + `screener-data.jsx`.
  - Shared `assets/` + `_check/` (Figma QA snapshots).
  - Opus diffs against these at visual-QA time; the `.jsx` files are reference-only (React) — never imported.
- Infra to REUSE (do NOT rewrite):
  - `@netz/ui/terminal` primitives: `Pill`, `Kbd`, `KpiCard`, `DensityToggle`, `AccentPicker`, `ThemeToggle` (PR #231).
  - `TerminalShell`, `TerminalTopNav`, `TerminalBreadcrumb`, `TerminalTweaksPanel`, `TerminalStatusBar`, `LayoutCage`, `CommandPalette` (PRs #230/#232).
  - `terminal-tweaks.svelte.ts` (density/accent/theme — in-memory only).
  - `MarketDataStore` (Tiingo WS + REST fallback) already wired to `(terminal)/+layout.svelte`.
  - Formatters `formatMonoTime` / `formatCompactCurrency` / `formatPpDrift` / `formatMonoPercent` from `@netz/ui/formatters/mono`.
  - Tokens `--terminal-*` namespace canonical; `--term-*` in Figma CSS are naming differences only — remap at port time, no aliases in `@netz/ui`.
- Figma JSX uses React `useState`/`setInterval` sims + `Math.random` ticks — **ignore all JS**, port visuals only.
- `(terminal)/+layout.svelte` already mounts breadcrumb, tweaks context, and LayoutCage. No layout-shell changes allowed in this sprint.
- Scope decisions confirmed by Andrei 2026-04-19:
  - **Macro RegimeMatrix pin** = client-only `$state`, no backend write. UI banner “SIMULATION”.
  - **Screener** canonical route is `/terminal-screener`; `FundFocusMode` overlay remains the fund-detail surface.
  - **Builder** page already exists (Phase 4 + 5 complete). This sprint only touches **visual parity** + **breadcrumb/toolbar alignment** + **CalibrationSlider band-panel scaffold** for PR-A13 (the achievable-return band UX is a separate sprint; this plan ships only the visual slot).
- **Out of scope for this plan**:
  - PR-A13 achievable-return band computation (backend-driven, separate sprint).
  - Any new backend endpoint. If a panel has no live data, flag in §D; never mock.
  - Rebalance FocusMode re-litigation (locked in Phase 5).
  - Feasibility frontier UX (sequenced after PR-A11/A13 per memory).

---

## A. Diff-style audit per page

Each row: **Current** → **Gap vs Figma** → **Patch**.

### A.SCREENER — `/terminal-screener`

Route: `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.svelte`
Supporting: `frontends/wealth/src/lib/components/screener/terminal/{TerminalScreenerShell,TerminalScreenerFilters,TerminalDataGrid}.svelte`
Figma: `Netz Terminal - Screener.html` + `screener.css` + `screener-app.jsx`

| # | Current | Gap vs Figma | Patch |
|---|---|---|---|
| S1 | `TerminalScreenerShell` renders filters + datagrid. URL-owned filter state via `parseFiltersFromURL`. `FundFocusMode` overlay on row click. | OK — architecture matches Figma’s two-column (filter rail + grid). No structural change. | No-op. |
| S2 | `TerminalScreenerFilters.svelte` — raw filter inputs (checkboxes + numeric sliders inline). | Figma uses a **FilterChipGroup** model: each applied filter renders as a dismissible pill with operator + value. Unapplied filters hide in a collapsible drawer at left. | Introduce `<FilterChipRow>` at the top of the grid (shows applied filters as `Pill as="button" tone="accent"` with X). Filter inputs remain in the rail but are collapsed by default; chip row is the primary driver. See §B.1. |
| S3 | Datagrid uses `TerminalDataGrid` (custom `<table>`). | Figma shows tabular row with **mini sparkline column** (inline 60×18 sparkline per row — last 12mo NAV trend), plus star-elite badge, pill for strategy. | Add `<MiniSparkline />` primitive (§B.2) to `TerminalDataGrid` row renderer. Sparkline data comes from `fund_risk_metrics.nav_trend_sparkline` if present; otherwise omit column (flag backend gap §D). |
| S4 | Column set: name, strategy, aum, return_1y, sharpe, expense, dd. | Figma adds **BLENDED MOMENTUM** column (pre-computed `blended_momentum_score` from `fund_risk_metrics`) and **10Y RETURN** column. | Add columns to `TerminalDataGrid` config. Data already exists in `fund_risk_metrics`. |
| S5 | Row click → `FundFocusMode` overlay. | OK. Figma `screener-app.jsx` shows same overlay structure. | No-op. |
| S6 | `screener.css` uses `--term-*` tokens (e.g. `--term-void`, `--term-fg-primary`). | Must remap to `--terminal-*`. | Port only the layout rules (grid template, row heights, column widths). All color refs → `--terminal-*`. |
| S7 | No DensityToggle integration in screener surface. | Figma rows compress with `[data-density="compact"]`. | `<TerminalDataGrid>` must consume `--t-row-height` (already defined). Verify row height does NOT use hardcoded px. |
| S8 | `screener-page-root` overrides `.lc-cage--standard` padding to `--terminal-space-2`. | OK — matches Figma edge-to-edge density. | No-op. |
| S9 | No keyboard nav in grid. | Figma: `↑/↓` moves row focus; `Enter` opens FundFocusMode; `/` focuses filter search. | Add keyboard handler on `containerEl` in `+page.svelte`. Guard: skip when input focused (reuse util from `TerminalShell`). |

### A.MACRO — `/macro`

Route: `frontends/wealth/src/routes/(terminal)/macro/+page.svelte`
Supporting: `frontends/wealth/src/lib/components/terminal/macro/{StressHero,SignalBreakdown,RegionalHealthTile,SparklineWall,CommitteeReviewFeed}.svelte`
Figma: `Netz Terminal - Macro.html` + `macro.css` + `macro-app.jsx`

| # | Current | Gap vs Figma | Patch |
|---|---|---|---|
| M1 | Layout = Hero (full) → SignalBreakdown (2-col) → bottom grid 5fr/4fr/3fr. | Figma layout = **4 zones**: (1) StressHero + RegimeMatrix side-by-side (7fr/5fr), (2) SignalBreakdown full-width, (3) bottom = RegionalHealth (6fr) + SparklineWall (6fr), (4) CommitteeReviewFeed = right sidebar in Zone 1 OR collapsible drawer. | Restructure `macro-desk` grid. Pull CommitteeReviewFeed out of bottom row; place as a drawer toggled by `Shift+R` (committee review key). Add RegimeMatrix next to Hero. |
| M2 | `.macro-desk { height: calc(100vh - 88px); padding: 24px; }` hardcoded. | Use layout cage tokens. | `height: var(--terminal-shell-cage-height, calc(100vh - 116px))`; keep `padding: 24px` per `feedback_layout_cage_pattern.md` (flex/grid min-h-0 fails). |
| M3 | `setInterval(..., 5*60*1000)` polls macro scores + FRED sparklines. | Figma sparklines are WS-ticked (Tiingo quote for index-tracking ETFs). Backend FRED series are daily — WS not applicable. | Keep 5min REST poll for FRED. **NEW:** for VIX/USD/10Y sparklines that have Tiingo proxies (VXX, UUP, IEF), swap source to `MarketDataStore` subscription. Adapter `macro-sparkline-adapter.ts` (§B.3) resolves series → symbol → live tick. Sparklines without live proxy stay REST-only. |
| M4 | No RegimeMatrix (drag-drop pin simulation). | Figma: 4×4 grid of regime cells (rows = stress level, cols = growth quadrant). User drags the active pin to a cell → `simulatedRegime` propagates to Hero + SignalBreakdown shading. | New component `RegimeMatrix.svelte` (§B.4). Local `$state` only, banner “SIMULATION”, `Reset` button. No backend write. |
| M5 | `pinnedRegime` currently persists across pages (global state). | Figma pin state is page-local (matrix = simulation, not a global lock). | Keep `pinnedRegime` global store as-is for TopNav regime indicator, but matrix simulation writes to a SEPARATE `macroSimulationStore` (page-scoped) that does NOT touch `pinnedRegime`. |
| M6 | `SparklineWall` uses its own sparkline renderer. | Figma sparklines are identical to screener mini-sparklines (same 60×18 footprint with last/delta label). | Refactor `SparklineWall` to use the new `<MiniSparkline>` primitive from §B.2. Deduplicates. |
| M7 | No chart-type toggle. Sparklines only. | Figma has **tab group** on SparklineWall: `SPARK / AREA / BARS`. | Add `<Pill as="button">` trio driving `SparklineWall.mode`. Area/bars render via same `lightweight-charts` instance (single-container swap, same pattern as PR #233 Candle/Line toggle). **Out of scope if new lightweight-charts series types required** — ship SPARK-only and flag. |
| M8 | No `.toFixed` / `toLocaleString` in macro components (grep clean). | — | No cleanup needed. |
| M9 | `StressHero` emits `onProceedToAlloc` → `/terminal/allocation`. | Figma button reads `PROCEED TO BUILDER`. | Rename label; route already correct (`(terminal)/allocation`). Copy change only. |
| M10 | `CommitteeReviewFeed` shows last N reviews inline. | Figma = drawer, closed by default, opens via `Shift+R` OR badge click in TopNav. | Wrap in `<Drawer side="right" width="380">` (new primitive §B.5 OR reuse `TerminalTweaksPanel` drawer pattern). |

### A.BUILDER — `/portfolio/builder`

Route: `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte`
Supporting: `frontends/wealth/src/lib/components/terminal/builder/*.svelte` (12 components — Phase 4+5 complete)
Figma: `Netz Terminal - Builder.html` + `builder.css` + `builder-app.jsx` + `builder-preview.jsx`

| # | Current | Gap vs Figma | Patch |
|---|---|---|---|
| B1 | 2-column 40/60 layout. Left = Zone A/B/C (regime+calibration+runctrl). Right = Zone D (cascade) + Zone E (7 tabs). | Figma = same 40/60 but **Zone B (CalibrationPanel)** uses a dense slider stack (CVaR, turnover, min-weight, max-single-position) in a 2×2 grid; current CalibrationPanel is a vertical list. | Restyle `CalibrationPanel` (imports from `portfolio/` not `terminal/builder/`) — move to `terminal/builder/CalibrationPanel.svelte` OR add a terminal-variant. 2×2 grid; use new `<CalibrationSlider>` primitive (§B.6). |
| B2 | Tab list: REGIME, WEIGHTS, RISK, STRESS, BACKTEST, MONTE CARLO, ADVISOR. | Figma order: REGIME, WEIGHTS, RISK, STRESS, BACKTEST, MONTE CARLO, ADVISOR + new **CASCADE** detail tab (cascade telemetry JSONB from PR-A11). | **Defer CASCADE tab to backlog** — PR-A11 telemetry panel is a separate sprint (already in memory). Flag only. |
| B3 | `CascadeTimeline` renders 4 phases (P1 / P1.5 / P2 / P3) with winner badge. | Figma adds **coverage bar** underneath timeline (PR-A14 coverage signal; already shipped in data). | Extend `CascadeTimeline` to render `cascade_telemetry.coverage` as a thin progress bar below the phase row. Color via `--sev-warn` if <50%, `--sev-critical` if <20%, `--terminal-status-success` otherwise. |
| B4 | `ActivationBar` gates on all-tabs-visited. | Figma footer has left-side `IPS SUMMARY` strip (3 rules chips: target return, max CVaR, rebalance frequency). | Add `<IpsSummaryStrip>` component (§B.7) to `ActivationBar` left slot. Reads from `workspace.ips` (already populated Phase 5). |
| B5 | Breadcrumb not rendered per-page (done at shell level). | OK. | No-op. |
| B6 | `.toFixed`/`Intl` audit in builder components. | Grep: run on PR-B open. Expect 0 (Phase 4 shipped clean). | Lint sweep only. |
| B7 | `data-builder-root` attribute used for LayoutCage override? | Currently no override — cage padding 24px stays. Figma uses edge-to-edge. | Add `data-builder-root` + `:global(.lc-cage--standard:has([data-builder-root])) { padding: var(--terminal-space-2) !important; }` matching screener. Confirm doesn’t break Zone layout. |
| B8 | RegimeContextStrip renders current regime + stress + window. | OK — matches Figma Zone A. | No-op. |
| B9 | RunControls = single `RUN` button + profile dropdown. | Figma adds `DRY RUN` secondary button (runs optimizer without persisting). | **Flag as backend dependency.** Dry-run mode requires backend flag on `/portfolio-construction/runs` endpoint. If not supported, ship without dry-run; display tooltip “Coming soon”. Do NOT mock. |
| B10 | `ConsequenceDialog` fires on destructive actions. | Figma same. | No-op. |
| B11 | Hardcoded tab ID tuple uses `"MONTE CARLO"` with space. | Figma uses `MONTE-CARLO`. | Cosmetic — no-op unless it breaks URL sync (it doesn’t; tab state is in-memory). |

---

## B. New primitives (shared or page-local)

Rule: **2+ page consumers → `@netz/ui/terminal`**. **1 consumer → wealth-local** (`frontends/wealth/src/lib/components/terminal/<page>/`).

### B.1 `FilterChipRow` + `FilterChip` — **wealth-local**
Path: `frontends/wealth/src/lib/components/screener/terminal/FilterChipRow.svelte`
Consumer: Screener only (for now — if Builder ever adds filter chips, promote).
Props:
```ts
interface FilterChip {
  key: string;
  label: string;    // "Strategy"
  operator: string; // "=" | "in" | ">="
  value: string;    // pre-formatted
  onRemove: () => void;
}
interface FilterChipRowProps {
  chips: FilterChip[];
  onClearAll: () => void;
}
```
Renders each chip as `<Pill as="button" tone="accent" size="sm">` with trailing `×`. `CLEAR ALL` link at right. Stubs `FilterOperator` enum from Tzezar audit (memory).

### B.2 `MiniSparkline` — **promote to `@netz/ui/terminal`**
Path: `packages/investintell-ui/src/lib/components/terminal/MiniSparkline.svelte`
Consumers: Screener grid rows (§S3), Macro SparklineWall (§M6). 2 consumers → promote.
Props:
```ts
interface MiniSparklineProps {
  data: number[];       // pre-sampled, no timestamps
  width?: number;       // default 60
  height?: number;      // default 18
  tone?: "up" | "down" | "neutral";  // auto-computed from last vs first if omitted
  strokeWidth?: number; // default 1
}
```
Pure SVG `<polyline>` — no lightweight-charts (too heavy for row use). Tabular-safe width. No hover/tooltip (row-level focus handles detail).

### B.3 `macro-sparkline-adapter.ts` — **wealth-local**
Path: `frontends/wealth/src/lib/components/terminal/macro/macro-sparkline-adapter.ts`
Purpose: Map FRED series → Tiingo symbol when a live proxy exists.
```ts
const SERIES_TO_SYMBOL: Record<string, string> = {
  VIXCLS: "VXX",
  DTWEXBGS: "UUP",
  DGS10: "IEF",
  // CPI, GDP, UNRATE, DFF, BAA10Y → no proxy (REST-only)
};
export function proxyFor(seriesId: string): string | null;
```
Consumer: `SparklineWall` subscribes via `MarketDataStore.subscribe(symbol)` when `proxyFor(id)` returns non-null.

### B.4 `RegimeMatrix` — **wealth-local (macro only)**
Path: `frontends/wealth/src/lib/components/terminal/macro/RegimeMatrix.svelte`
Consumers: Macro only. Stays local.
Props:
```ts
interface RegimeMatrixProps {
  activeRegime: string;       // current real regime (e.g. "RISK_OFF")
  simulatedCell?: { row: number; col: number } | null;
  onSimulate: (cell: { row: number; col: number } | null) => void;
}
```
4×4 grid. Drag-drop uses pointer events (no lib). Banner `SIMULATION — DOES NOT PERSIST` when `simulatedCell !== null`. `Reset` button clears. **In-memory `$state` only.** Zero backend calls.

### B.5 `Drawer` — **promote to `@netz/ui/terminal`**
Path: `packages/investintell-ui/src/lib/components/terminal/Drawer.svelte`
Consumers: CommitteeReviewFeed (Macro), potentially TweaksPanel could refactor into it. 2 consumers → promote.
Props:
```ts
interface DrawerProps {
  open: boolean;
  side?: "left" | "right";      // default right
  width?: number;               // default 320
  label: string;                // aria-label
  onClose: () => void;
  children: Snippet;
}
```
Mount at shell root (outside LayoutCage — per `feedback_layout_cage_pattern.md`). Backdrop scrim uses `--terminal-bg-scrim`. ESC closes. Focus trap via `focus-trap` or manual.

### B.6 `CalibrationSlider` — **wealth-local (builder only)**
Path: `frontends/wealth/src/lib/components/terminal/builder/CalibrationSlider.svelte`
Consumers: Builder only.
Props:
```ts
interface CalibrationSliderProps {
  label: string;          // "CVaR LIMIT"
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;           // "%" | "pp" | "×"
  format?: (v: number) => string; // defaults to formatMonoPercent
  onChange: (v: number) => void;
  helperText?: string;    // "Operator-set constraint"
  warning?: string | null; // e.g. "Below 2% may be infeasible"
}
```
Single-row: label (caps, 10px) + value (mono, 14px) + range input + helper/warning line. Tokens only.

### B.7 `IpsSummaryStrip` — **wealth-local (builder only)**
Path: `frontends/wealth/src/lib/components/terminal/builder/IpsSummaryStrip.svelte`
Consumers: Builder only.
Renders 3 `<Pill tone="neutral" size="xs">` pills for target return, max CVaR, rebalance freq. Reads `workspace.ips` via prop passthrough (NO context in primitive — caller owns).

### B.8 Keyboard nav util — **reuse existing**
`TerminalShell` already exposes `isTypingInInput()` helper. Export from `frontends/wealth/src/lib/utils/keyboard.ts` if not already; all new shortcuts (`/`, `↑↓`, `Shift+R`) must guard with it.

---

## C. Wiring of data per page

### C.SCREENER
| Panel | Component | Source | Status |
|---|---|---|---|
| Filter chips | `FilterChipRow` | Derived from URL searchParams (same `parseFiltersFromURL`) | OK |
| Grid rows | `TerminalDataGrid` | `GET /screener/query` (existing) | OK |
| Mini sparkline | `MiniSparkline` | `fund_risk_metrics.nav_trend_sparkline` (array of last 12 monthly NAV values) | **VERIFY** — if column absent, backend adds it; ship column hidden until ready. Flag §G. |
| Fund detail | `FundFocusMode` | `GET /funds/:id/focus` (existing) | OK |
| Keyboard | — | client-only | OK |

### C.MACRO
| Panel | Component | Source | Status |
|---|---|---|---|
| StressHero | `StressHero` | `GET /macro/regime` | OK |
| RegimeMatrix | `RegimeMatrix` | client `$state` only (NO backend) | OK — simulation-only per scope |
| SignalBreakdown | `SignalBreakdown` | `regime.signal_breakdown` (from regime response) | OK |
| Regional tiles | `RegionalHealthTile` | `GET /macro/scores` | OK |
| Sparkline wall (REST) | `SparklineWall` | `GET /macro/fred?series_id=…` 5min poll | OK |
| Sparkline wall (live) | `SparklineWall` via adapter | `MarketDataStore.subscribe(VXX|UUP|IEF)` | OK (MarketDataStore already mounted in layout) |
| Committee feed | `CommitteeReviewFeed` | `GET /macro/reviews?limit=10` | OK |

### C.BUILDER
| Panel | Component | Source | Status |
|---|---|---|---|
| Regime strip | `RegimeContextStrip` | `workspace.regime` | OK |
| Calibration | `CalibrationPanel` + new sliders | `workspace.calibration` | OK (existing workspace store) |
| Cascade timeline | `CascadeTimeline` | SSE `/portfolio-construction/runs/:id/stream` → `cascade_telemetry` JSONB (PR-A11) + `coverage` (PR-A14) | OK — already wired |
| Tabs | 7 tab components | `workspace.run.result` | OK |
| IPS strip | `IpsSummaryStrip` | `workspace.ips` | OK (Phase 5) |
| Dry-run button | `RunControls` | `POST /portfolio-construction/runs` with `?dry_run=1` | **GAP — backend dependency.** Do not ship; tooltip disabled. |

---

## D. Violations cleanup per page

Grep targets must return **0 matches** across each page’s owned files.

### D.SCREENER
Files: `(terminal)/terminal-screener/**`, `lib/components/screener/terminal/**`, `lib/components/terminal/focus-mode/fund/**`
- `.toFixed(` — **audit** (MiniSparkline last-value label must use `formatMonoPercent`). Fix if found.
- `.toLocaleString(` — hold 0.
- `localStorage` / `sessionStorage` — hold 0.
- `new EventSource` — hold 0.
- Hex literals `#[0-9a-fA-F]{3,6}` — **audit `screener.css` port** — all color refs must be `--terminal-*`. Expected 0 in `.svelte`/`.ts`.
- `new Intl.NumberFormat` / `DateTimeFormat` — hold 0.
- Emojis — hold 0.
- `{#each … as x}` without `(x.id)` — 0 (grid rows must key on `instrument_id`).

### D.MACRO
Files: `(terminal)/macro/**`, `lib/components/terminal/macro/**`
- `.toFixed(` — grep existing macro components. Expect 0 (port was clean).
- `toISOString().substring` — hold 0 (shell already uses `formatMonoTime`).
- Hex literals — **audit port of `macro.css`**; remap every `--term-*` → `--terminal-*`.
- `localStorage` for pin simulation — **MUST be 0**. `macroSimulationStore` is `$state`-only, no persistence.
- `new EventSource` — hold 0.
- Emojis — hold 0.

### D.BUILDER
Files: `(terminal)/portfolio/builder/**`, `lib/components/terminal/builder/**`
- `.toFixed(` — grep. If found in `WeightsTab`/`RiskTab` (likely — Phase 4 shipped with some raw numeric formatting), replace with `formatMonoPercent` / `formatCompactCurrency`.
- `new Intl.*` — hold 0.
- Hardcoded hex in `CascadeTimeline` coverage bar — **must use** `--terminal-status-success` / `--sev-warn` / `--sev-critical`.
- `localStorage` — hold 0.
- Emojis — hold 0.

### D.9 CI extension
Extend `scripts/check-terminal-tokens-sync.mjs` to grep the 3 new route dirs:
```
(terminal)/terminal-screener/**
(terminal)/macro/**
(terminal)/portfolio/builder/**
```
Add to existing list (Terminal.html sprint covered only `(terminal)/portfolio/live/**`).

---

## E. Acceptance criteria per page

### E.SCREENER
- **Visual**: 1440×900 parity with `Netz Terminal - Screener.html` dark default; filter chips horizontal strip at top; grid rows 22px (standard) / 18px (compact); MiniSparkline column renders when data present.
- **Runtime**:
  - `/` focuses filter search; `↑↓` moves row focus; `Enter` opens FundFocusMode; `ESC` closes; all guarded by input-focus detection.
  - URL filter state survives reload (already green — verify).
  - Row count ≥500 renders without jank (virtualization already in `TerminalDataGrid`).
- **Lint**: `pnpm -F wealth lint` exits 0. Grep §D.SCREENER all 0.

### E.MACRO
- **Visual**: 1440×900 parity with `Netz Terminal - Macro.html`; RegimeMatrix beside Hero; CommitteeReviewFeed in drawer (closed default); SparklineWall shows live ticks for VXX/UUP/IEF proxies.
- **Runtime**:
  - Drag-drop on RegimeMatrix cell → simulated regime propagates to Hero shading + SignalBreakdown weights within 1 frame.
  - `Reset` clears simulation.
  - `Shift+R` toggles CommitteeReviewFeed drawer.
  - No backend writes on simulation (network tab confirms 0 requests on drag).
- **Lint**: grep §D.MACRO all 0.

### E.BUILDER
- **Visual**: 1440×900 parity with `Netz Terminal - Builder.html`; 2×2 calibration grid; IPS summary strip in ActivationBar; cascade coverage bar below timeline.
- **Runtime**:
  - Calibration sliders debounce 150ms before writing to `workspace.calibration`.
  - CascadeTimeline coverage bar tint matches thresholds (§B3).
  - Tab-visit gate still unlocks ActivationBar after all tabs visited (regression check).
  - Dry-run button renders disabled with tooltip; does NOT fire requests.
- **Lint**: grep §D.BUILDER all 0.

### E.ALL (cross-page)
- `pnpm -F wealth check` exits 0.
- Playwright smoke (extend `terminal.spec.ts` from PR #234):
  - Screener: `/` → filter chip renders on set → `ESC` clears FocusMode.
  - Macro: drag regime cell → Hero class updates → no network POSTs.
  - Builder: slider change → coverage bar renders.
- `scripts/check-terminal-tokens-sync.mjs` passes across all 3 routes.

---

## F. Sequencing — 4 sub-PRs (5 if primitives isolated)

Each PR independently mergeable. Target: one Opus session each. Stack-ordered — PR-1 merges first.

### PR-1 — `feat/terminal-parity-shared-primitives`
**Scope** (smallest, unblocks 2 pages):
- `@netz/ui/terminal/MiniSparkline.svelte` (§B.2) + exports + vitest.
- `@netz/ui/terminal/Drawer.svelte` (§B.5) + exports + vitest (ESC + focus-trap test).
- Extend `scripts/check-terminal-tokens-sync.mjs` with 3 new route dirs (§D.9).
- No route file touched.
Size: 2 components + 1 CI edit + tests. ~220 LoC.

### PR-2 — `feat/terminal-parity-screener`
**Scope**:
- `FilterChipRow` + `FilterChip` wealth-local (§B.1).
- `TerminalDataGrid`: add MiniSparkline column, BLENDED MOMENTUM column, 10Y RETURN column.
- Port layout rules from `screener.css` (no colors — token remap).
- Keyboard nav (`/`, `↑↓`, `Enter`) with input-focus guard.
- Column hidden fallback if `nav_trend_sparkline` absent (§G risk 1).
- Playwright smoke extension.
- Dep: PR-1 (MiniSparkline).
Size: 3 components touched + 1 new + test. ~350 LoC.

### PR-3 — `feat/terminal-parity-macro`
**Scope**:
- `RegimeMatrix.svelte` (§B.4) + `macroSimulationStore.svelte.ts` page-scoped.
- `macro-sparkline-adapter.ts` (§B.3).
- `SparklineWall` refactor → MiniSparkline + live-tick subscription for proxies.
- Restructure `macro-desk` grid (§M1).
- CommitteeReviewFeed → `<Drawer>` + `Shift+R` shortcut.
- Label change "PROCEED TO BUILDER".
- Playwright smoke extension.
- Dep: PR-1 (MiniSparkline + Drawer).
Size: 2 new components + 1 store + 1 adapter + 3 edits. ~480 LoC.

### PR-4 — `feat/terminal-parity-builder`
**Scope**:
- `CalibrationSlider.svelte` (§B.6) + `IpsSummaryStrip.svelte` (§B.7).
- `CalibrationPanel` terminal-variant (2×2 grid).
- `CascadeTimeline`: coverage bar row.
- `ActivationBar`: mount `IpsSummaryStrip`.
- `RunControls`: disabled dry-run button + tooltip (NO backend call).
- `data-builder-root` + LayoutCage padding override.
- Lint sweep `.toFixed` in builder components.
- Playwright smoke extension.
- Dep: none on PR-2/PR-3 (independent).
Size: 2 new components + 4 edits + lint sweep. ~380 LoC.

### PR-5 (optional if PR-4 overflows) — `feat/terminal-parity-builder-lint-sweep`
Splits the `.toFixed` sweep + data-builder-root override out if PR-4 exceeds one Opus session.

---

## G. Open risks per page

### G.SCREENER
1. **`nav_trend_sparkline` column may not exist in `fund_risk_metrics`.** Must verify at PR-2 open. If absent, ship MiniSparkline column hidden; add backend task to `global_risk_metrics` worker (lock 900_071). Never compute sparkline client-side — defeats the point of pre-computed risk metrics.
2. **TerminalDataGrid virtualization interaction with keyboard row focus.** Row focus via DOM `.focus()` may jump scroll if virtualized row is out of viewport. Mitigate: `scrollIntoView({ block: "nearest" })` on focus change; verify in Playwright.
3. **FilterChipRow vs TerminalScreenerFilters duplication.** Chip row is derived from URL state; filter rail writes to URL. Source-of-truth clash if chip X-removal and rail checkbox get out of sync. Mitigate: chip `onRemove` calls the same `handleFiltersChange` as rail; never writes to a separate store.

### G.MACRO
1. **RegimeMatrix drag-drop on touch devices.** Pointer events cover touch, but verify on tablet Figma preview. Scope: desktop-first (Andrei runs terminal on 32″ monitor per memory); touch = nice-to-have.
2. **Simulated regime leak into global `pinnedRegime`.** Must not propagate. Enforce by putting `macroSimulationStore` in page-local scope — do NOT import from `$lib/state/*` (which is app-global).
3. **SparklineWall live-tick subscription churn.** MarketDataStore subscribe/unsubscribe on mount/unmount. Verify `$effect` cleanup unsubscribes all 3 proxies. WS reconnect during page switch shouldn’t leak listeners.
4. **Tiingo quote for UUP/IEF may not be in default tenant subscription basket.** Backend `MarketDataStore` ticker whitelist — if UUP isn’t subscribed, sparkline stays REST. Flag and defer; not a blocker.

### G.BUILDER
1. **CalibrationSlider debounce vs optimizer re-run.** Current Phase 4 behavior: any workspace.calibration change invalidates last run. 150ms debounce reduces chatter; confirm doesn’t desync with RunControls `RUN` button state.
2. **Dry-run button without backend.** Risk of shipping a dead button. Tooltip must be unambiguous (`"Dry-run mode coming in next sprint"`); alternatively, hide behind feature flag `FEATURE_BUILDER_DRY_RUN` (default false).
3. **`CalibrationPanel` currently imported from `$lib/components/portfolio/` not `terminal/builder/`.** Moving it risks breaking the non-terminal `/portfolio` surface. Safer: copy to `terminal/builder/CalibrationPanel.svelte` as a new variant; keep original intact.
4. **PR-A13 CVaR slider + achievable-return band.** Memory flags PR-A13 UX brief exists (2026-04-17). This sprint ships the slider ONLY; the band panel is a separate sprint. Do NOT implement band computation here — coordinate with Andrei if Opus attempts to bundle.

---

## H. Execution order

**Andrei’s suggestion accepted with one swap:**

1. **PR-1 (primitives)** — unblocks both Screener + Macro. Small, low-risk, merge first.
2. **PR-2 (Screener)** — most isolated; filters + grid rendering. No shell changes. Single data source. Validates MiniSparkline in production.
3. **PR-3 (Macro)** — introduces RegimeMatrix + Drawer. Depends on PR-1 drawer. Visual complexity mid-tier.
4. **PR-4 (Builder)** — highest reuse (slider + strip only new), but Builder is already the most complex page — do last so any breaking changes from PR-2/PR-3 primitives surface first.

Rationale: primitives before consumers; Screener validates shared primitives in simplest context; Macro stress-tests Drawer + live-tick wiring; Builder consumes stable primitives + touches the already-hardened Phase 4+5 surface last.

---

## Appendix — Post-merge backlog (not this sprint)

- CASCADE detail tab in Builder (PR-A11 telemetry panel).
- PR-A13 achievable-return band panel for Builder.
- SparklineWall AREA / BARS modes (Macro §M7).
- Feasibility frontier pre-optimizer UX.
- `nav_trend_sparkline` column in `global_risk_metrics` worker (if missing).
- Builder dry-run backend flag.
- Tiingo subscription basket expansion for macro proxies (UUP/IEF).
- Touch support for RegimeMatrix drag-drop.
