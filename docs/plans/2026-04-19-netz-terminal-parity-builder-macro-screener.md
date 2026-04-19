# Netz Terminal Parity — Builder / Macro / Screener

**Date:** 2026-04-19
**Owner:** Andrei
**Scope decision locked:** Visual + interaction parity for the 3 remaining UX bundle pages (`Netz Terminal - Builder.html`, `Netz Terminal - Macro.html`, `Netz Terminal - Screener.html`). Terminal.html parity already landed via PRs #230–#234.
**Execution model:** 4–5 independently-mergeable sub-PRs sized for a single Opus session each. Sessions run in parallel with Gemini; do not cross-touch files outside the PR’s scope.

---

## 0. Ground truth & assumptions

- UX bundle IS checked into repo at `docs/ux/Netz Terminal/`:
  - `Netz Terminal - Builder.html` + `builder.css` (726 lines) + `builder-app.jsx` (381) + `builder-data.jsx` + `builder-preview.jsx`.
  - `Netz Terminal - Macro.html` + `macro.css` (629) + `macro-app.jsx` (695) + `macro-data.jsx`.
  - `Netz Terminal - Screener.html` + `screener.css` (398) + `screener-app.jsx` (602) + `screener-data.jsx`.
  - Shared `assets/` + `_check/` (bundle QA snapshots).
  - Opus diffs against these at visual-QA time; the `.jsx` files are reference-only (React) — never imported.
- Infra to REUSE (do NOT rewrite):
  - `@netz/ui/terminal` primitives: `Pill`, `Kbd`, `KpiCard`, `DensityToggle`, `AccentPicker`, `ThemeToggle` (PR #231).
  - `TerminalShell`, `TerminalTopNav`, `TerminalBreadcrumb`, `TerminalTweaksPanel`, `TerminalStatusBar`, `LayoutCage`, `CommandPalette` (PRs #230/#232).
  - `terminal-tweaks.svelte.ts` (density/accent/theme — in-memory only).
  - `MarketDataStore` (Tiingo WS + REST fallback) already wired to `(terminal)/+layout.svelte`.
  - Formatters `formatMonoTime` / `formatCompactCurrency` / `formatPpDrift` / `formatMonoPercent` from `@netz/ui/formatters/mono`.
  - Tokens `--terminal-*` namespace canonical; `--term-*` in bundle CSS are naming differences only — remap at port time, no aliases in `@netz/ui`.
- Bundle JSX uses React `useState`/`setInterval` sims + `Math.random` ticks — **ignore all JS**, port visuals only.
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

Each row: **Current** → **Gap vs bundle** → **Patch**.

### A.SCREENER — `/terminal-screener`

Route: `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.svelte`
Supporting: `frontends/wealth/src/lib/components/screener/terminal/{TerminalScreenerShell,TerminalScreenerFilters,TerminalDataGrid}.svelte`
Bundle: `Netz Terminal - Screener.html` + `screener.css` + `screener-app.jsx`

| # | Current | Gap vs bundle | Patch |
|---|---|---|---|
| S1 | `TerminalScreenerShell` renders filters + datagrid. URL-owned filter state via `parseFiltersFromURL`. `FundFocusMode` overlay on row click. | OK — architecture matches the bundle’s two-column (filter rail + grid). No structural change. | No-op. |
| S2 | `TerminalScreenerFilters.svelte` — raw filter inputs (checkboxes + numeric sliders inline). | Bundle uses a **FilterChipGroup** model: each applied filter renders as a dismissible pill with operator + value. Unapplied filters hide in a collapsible drawer at left. | Introduce `<FilterChipRow>` at the top of the grid (shows applied filters as `Pill as="button" tone="accent"` with X). Filter inputs remain in the rail but are collapsed by default; chip row is the primary driver. See §B.1. |
| S3 | Datagrid uses `TerminalDataGrid` (custom `<table>`). | Bundle shows tabular row with **mini sparkline column** (inline 60×18 sparkline per row — last 12mo NAV trend), plus star-elite badge, pill for strategy. | Add `<MiniSparkline />` primitive (§B.2) to `TerminalDataGrid` row renderer. Sparkline data comes from `fund_risk_metrics.nav_trend_sparkline` if present; otherwise omit column (flag backend gap §D). |
| S4 | Column set: name, strategy, aum, return_1y, sharpe, expense, dd. | Bundle adds **BLENDED MOMENTUM** column (pre-computed `blended_momentum_score` from `fund_risk_metrics`) and **10Y RETURN** column. | Add columns to `TerminalDataGrid` config. Data already exists in `fund_risk_metrics`. |
| S5 | Row click → `FundFocusMode` overlay. | OK. bundle `screener-app.jsx` shows same overlay structure. | No-op. |
| S6 | `screener.css` uses `--term-*` tokens (e.g. `--term-void`, `--term-fg-primary`). | Must remap to `--terminal-*`. | Port only the layout rules (grid template, row heights, column widths). All color refs → `--terminal-*`. |
| S7 | No DensityToggle integration in screener surface. | Bundle rows compress with `[data-density="compact"]`. | `<TerminalDataGrid>` must consume `--t-row-height` (already defined). Verify row height does NOT use hardcoded px. |
| S8 | `screener-page-root` overrides `.lc-cage--standard` padding to `--terminal-space-2`. | OK — matches the bundle's edge-to-edge density. | No-op. |
| S9 | No keyboard nav in grid. | Bundle: `↑/↓` moves row focus; `Enter` opens FundFocusMode; `/` focuses filter search. | Add keyboard handler on `containerEl` in `+page.svelte`. Guard: skip when input focused (reuse util from `TerminalShell`). |

### A.MACRO — `/macro`

Route: `frontends/wealth/src/routes/(terminal)/macro/+page.svelte`
Supporting: `frontends/wealth/src/lib/components/terminal/macro/{StressHero,SignalBreakdown,RegionalHealthTile,SparklineWall,CommitteeReviewFeed}.svelte`
Bundle: `Netz Terminal - Macro.html` + `macro.css` + `macro-app.jsx`

| # | Current | Gap vs bundle | Patch |
|---|---|---|---|
| M1 | Layout = Hero (full) → SignalBreakdown (2-col) → bottom grid 5fr/4fr/3fr. | Bundle layout = **4 zones**: (1) StressHero + RegimeMatrix side-by-side (7fr/5fr), (2) SignalBreakdown full-width, (3) bottom = RegionalHealth (6fr) + SparklineWall (6fr), (4) CommitteeReviewFeed = right sidebar in Zone 1 OR collapsible drawer. | Restructure `macro-desk` grid. Pull CommitteeReviewFeed out of bottom row; place as a drawer toggled by `Shift+R` (committee review key). Add RegimeMatrix next to Hero. |
| M2 | `.macro-desk { height: calc(100vh - 88px); padding: 24px; }` hardcoded. | Use layout cage tokens. | `height: var(--terminal-shell-cage-height, calc(100vh - 116px))`; keep `padding: 24px` per `feedback_layout_cage_pattern.md` (flex/grid min-h-0 fails). |
| M3 | `setInterval(..., 5*60*1000)` polls macro scores + FRED sparklines. | Bundle sparklines are WS-ticked (Tiingo quote for index-tracking ETFs). Backend FRED series are daily — WS not applicable. | Keep 5min REST poll for FRED. **NEW:** for VIX/USD/10Y sparklines that have Tiingo proxies (VXX, UUP, IEF), swap source to `MarketDataStore` subscription. Adapter `macro-sparkline-adapter.ts` (§B.3) resolves series → symbol → live tick. Sparklines without live proxy stay REST-only. |
| M4 | No RegimeMatrix (drag-drop pin simulation). | Bundle: 4×4 grid of regime cells (rows = stress level, cols = growth quadrant). User drags the active pin to a cell → `simulatedRegime` propagates to Hero + SignalBreakdown shading. | New component `RegimeMatrix.svelte` (§B.4). Local `$state` only, banner “SIMULATION”, `Reset` button. No backend write. |
| M5 | `pinnedRegime` currently persists across pages (global state). | Bundle pin state is page-local (matrix = simulation, not a global lock). | Keep `pinnedRegime` global store as-is for TopNav regime indicator, but matrix simulation writes to a SEPARATE `macroSimulationStore` (page-scoped) that does NOT touch `pinnedRegime`. |
| M6 | `SparklineWall` uses its own sparkline renderer. | Bundle sparklines are identical to screener mini-sparklines (same 60×18 footprint with last/delta label). | Refactor `SparklineWall` to use the new `<MiniSparkline>` primitive from §B.2. Deduplicates. |
| M7 | No chart-type toggle. Sparklines only. | Bundle has **tab group** on SparklineWall: `SPARK / AREA / BARS`. | Add `<Pill as="button">` trio driving `SparklineWall.mode`. Area/bars render via same `lightweight-charts` instance (single-container swap, same pattern as PR #233 Candle/Line toggle). **Out of scope if new lightweight-charts series types required** — ship SPARK-only and flag. |
| M8 | No `.toFixed` / `toLocaleString` in macro components (grep clean). | — | No cleanup needed. |
| M9 | `StressHero` emits `onProceedToAlloc` → `/terminal/allocation`. | Bundle button reads `PROCEED TO BUILDER`. | Rename label; route already correct (`(terminal)/allocation`). Copy change only. |
| M10 | `CommitteeReviewFeed` shows last N reviews inline. | Bundle = drawer, closed by default, opens via `Shift+R` OR badge click in TopNav. | Wrap in `<Drawer side="right" width="380">` (new primitive §B.5 OR reuse `TerminalTweaksPanel` drawer pattern). |

### A.BUILDER — `/allocation/[profile]` (propose→approve surface)

> **§ BUILDER SCOPE PIVOT (2026-04-19)**
>
> The bundle's `Netz Terminal - Builder.html` file represents the **legacy pre-A26 architecture** where the operator supplied CVaR + turnover + min-weight + max-single-position sliders, IC views, factor tilts, and region caps to the optimizer as inputs. That input surface has been **deleted from the product model** by the A26 sprint (PRs #214, #217, #219, #220, #221, #222 merged 2026-04-18).
>
> **New model (A26.1 + A26.2 + A26.3):** CVaR limit on the IPS is the only mandatory human input. The optimizer runs unconstrained by strategic bands in `propose` mode; the operator reviews the proposal (cascade telemetry + diff bars + 18-block targets) and either **approves atomically** (snapshot → `strategic_allocation` + `allocation_approvals`) or sets **ad-hoc per-block overrides** and re-proposes. Realize mode refuses to run until a Strategic is approved.
>
> **Treat the bundle as reference for the _output_ surfaces** (regime header, cascade phase timeline, weights table, risk metrics, stress scenarios, backtest charts — all read-only visualizations of an executed propose run). **Ignore the bundle's input surfaces** — zone B calibration sliders (CVaR/turnover/min-weight), IC views list, factor tilts, region caps, RunControls profile+RUN button. Those are replaced by the ProposeButton / ProposalReviewPanel / OverrideBandsEditor trio already shipped in PR #219.
>
> **Canonical Builder route for Terminal parity = `/(terminal)/allocation/[profile]/` (PR #219).**
> The route `/(terminal)/portfolio/builder/` is **legacy Phase 4+5 Builder** with calibration sliders / tabs / ActivationBar. It is NOT the parity target of PR-4. It may be retired in a follow-up sprint; out of scope for this plan. Opus executor: do not edit `/(terminal)/portfolio/builder/**` in PR-4.

**Route (canonical):** `frontends/wealth/src/routes/(terminal)/allocation/+page.svelte` (3-profile cards) + `frontends/wealth/src/routes/(terminal)/allocation/[profile]/+page.svelte` (per-profile governance surface).
**Supporting components (PR #219 delivered):** `frontends/wealth/src/lib/components/allocation/{StrategicAllocationTable,AllocationDonut,AllocationTable,ProposalReviewPanel,ProposeButton,OverrideBandsEditor,ApprovalHistoryTable}.svelte` + `BLOCK_INSTRUMENTS.ts` + `types.ts`.
**Bundle:** `Netz Terminal - Builder.html` + `builder.css` + `builder-app.jsx` + `builder-preview.jsx` — reference visually for **output tabs only** (Regime / Weights / Risk / Stress / Backtest / Cascade). Discard all input-surface elements.

**What stays from the bundle (visual re-skin targets, mapped to existing PR #219 components):**

| Bundle element | Existing component | Parity action |
|---|---|---|
| Cascade phase timeline (P1 → P1.5 → P2 → P3 → fallback) | `ProposalReviewPanel` metrics row (currently shows E[r] / CVaR / Target / Feasible badge — does NOT render phase timeline yet) | **NEW primitive** `CascadeTimeline.svelte` (wealth-local to `components/allocation/`) — reads `cascade_telemetry.phases[]` from the propose run. Mount in `ProposalReviewPanel` header above the diff bars. |
| Regime context strip (top of bundle) | Not rendered on allocation page | **NEW** `RegimeContextStrip.svelte` read-only (current regime + stress + window from `GET /macro/regime`). Mount above the KPI row. |
| Weights diff bars | `ProposalReviewPanel` diff bar chart (svelte-echarts) | OK — already shipped; re-skin colors to `--terminal-*` tokens. |
| 18-row allocation table | `StrategicAllocationTable` + `AllocationDonut` | OK — re-skin to Netz Terminal density + tokens. |
| IPS summary strip (target return / max CVaR / rebalance freq) | None | **NEW** `IpsSummaryStrip.svelte` (wealth-local, §B.7) — reads CVaR limit from `StrategicAllocationResponse.cvar_limit`. Rendered in the KPI row OR as a footer strip. |
| Breadcrumb + LayoutCage | `(terminal)/+layout.svelte` | OK — already wired. |

**What is REMOVED from the bundle (never implement):**

| Bundle input element | Why removed | Replacement |
|---|---|---|
| Zone B CalibrationPanel (CVaR / turnover / min-weight / max-single-position sliders) | A26 eliminated pre-run IC parameters except CVaR limit. | CVaR limit is set on `portfolio_calibration` via admin API (not in allocation UI per A26.3 Section scope). `OverrideBandsEditor` modal replaces all other block-level constraints. |
| IC views list (left rail) | A26.1 bypasses BL posterior + `_load_ic_views` in propose mode. | Deleted. |
| Factor tilts | Never implemented in backend; legacy bundle artifact. | Deleted. |
| Region caps / sector caps | Replaced by per-block `override_min/override_max` on any of the 18 canonical blocks. | `OverrideBandsEditor` per-block modal. |
| `RunControls` RUN + profile dropdown | Profile is URL param `[profile]`; "run" is now `ProposeButton`. | `ProposeButton` (SSE-wired, `fetch + ReadableStream`). |
| `ActivationBar` "all tabs visited" gate | No tabs exist in propose→approve flow. | Deleted. Approval gate is enforced server-side by the approve-proposal endpoint. |
| MONTE CARLO / ADVISOR tabs | Tab navigation dropped. Advisor output surfaces inline in `ProposalReviewPanel`. | Deleted. (Monte Carlo visualization may return as a post-approval analytics backlog item — out of scope.) |

**Diff rows (current `(terminal)/allocation/**` vs bundle sanitized reference):**

| # | Current | Gap vs bundle (sanitized) | Patch |
|---|---|---|---|
| B1 | `/allocation/[profile]/+page.svelte` renders: breadcrumb + KPI row (CVaR / Expected Return / Last Approved / Status badge) + 2-column main grid (Strategic table + donut \| ProposalReviewPanel OR ProposeButton) + ApprovalHistoryTable collapsible. | Bundle adds a **RegimeContextStrip** above KPI row (current regime + stress + window). Not yet rendered. | Add `<RegimeContextStrip>` (§B.8) at top of page. Reads `GET /macro/regime` (same endpoint as Macro StressHero) via loader. |
| B2 | `ProposalReviewPanel` shows metrics row + diff bars + expandable 18-block table + `Approve Allocation` / `Dismiss Proposal` actions. | Bundle shows cascade phase timeline (P1 / P1.5 / P2 / P3 winner) between metrics row and diff bars. | Insert `<CascadeTimeline>` (§B.6) between metrics row and diff bars. Reads `cascade_telemetry.phases[]` + `winner_signal` + `coverage` from the propose run payload. |
| B3 | `ProposalReviewPanel` metrics row: E[r] / CVaR / Target CVaR / Feasible badge. | Bundle adds **coverage bar** underneath cascade timeline (PR-A14 coverage signal already in data). | `CascadeTimeline` renders coverage as a thin progress bar under the phase row. Color via `--sev-warn` if <50%, `--sev-critical` if <20%, `--terminal-status-success` otherwise. |
| B4 | No IPS summary strip — only the inline KPI row. | Bundle has dedicated `IPS SUMMARY` strip with pills (CVaR limit, last-approved profile, rebalance cadence). | Add `<IpsSummaryStrip>` (§B.7) beneath the breadcrumb OR as a footer. Reads `StrategicAllocationResponse.cvar_limit` + `last_approved_at` + static cadence label. |
| B5 | `ApproveRejectBar` / standalone approve+reject bar not present — approve button lives inside `ProposalReviewPanel`. | Bundle shows a dedicated footer `ApproveRejectBar` beneath the results zone. | Acceptable as-is — do not duplicate. Keep approve button inside `ProposalReviewPanel`. Cosmetic: align the panel's action footer to bundle's ApproveRejectBar visual (same density, `Pill` accent primary for Approve + `Pill` ghost for Dismiss). |
| B6 | `.toFixed`/`Intl` audit in allocation components. | — | Grep sweep on PR open; PR #219 shipped clean but verify. Formatters must come from `@netz/ui`. |
| B7 | `data-allocation-root` attribute for LayoutCage padding override. | Currently uses the `h-[calc(100vh-88px)] p-6 overflow-y-auto` pattern directly. Bundle shows edge-to-edge density similar to screener. | Add `data-allocation-root` + match the screener override so cage padding collapses to `--terminal-space-2`. Preserve the `calc(100vh-88px)` height per `feedback_layout_cage_pattern.md`. |
| B8 | `StrategicAllocationTable` row click: no action. | OK — per PR-A26.3 Section C spec ("no drill-down in v1"). | No-op. Override edit still lives on the row-action icon. |
| B9 | Approve with `cvar_feasible=false` → confirm modal in `ProposalReviewPanel`. | OK — matches A26.2 Section C spec (`confirm_cvar_infeasible=true` body flag). | No-op. Verify visual parity: destructive tone on `Confirm Approval` button. |
| B10 | SSE propose flow: `fetch` + `ReadableStream` per `CLAUDE.md` + `ProposeButton`. | OK. | No-op. Verify events `propose_started / optimizer_started / optimizer_phase_complete / propose_ready / propose_cvar_infeasible / completed` render as a progress indicator with cascade-phase awareness (drives §CascadeTimeline update during the stream for pre-settlement visual). |
| B11 | `OverrideBandsEditor` modal includes rationale textarea (min 10 chars) + min/max numeric + Clear/Save. | OK per A26.2 Section D. | No-op. Re-skin modal tokens to Netz Terminal. |
| B12 | `ApprovalHistoryTable` collapsible (default collapsed) showing active/superseded rows with CVaR + E[r] snapshots. | OK. | No-op. Re-skin to Terminal density + tokens. |

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

### B.6 `CascadeTimeline` — **wealth-local (allocation only for now)**
Path: `frontends/wealth/src/lib/components/allocation/CascadeTimeline.svelte`
Consumers: `ProposalReviewPanel` only. If Builder-legacy page is re-added later, promote then.
Props:
```ts
interface CascadePhase {
  id: "phase_1_ru_max_return" | "phase_2_ru_robust" | "phase_3_min_variance" | "phase_4_min_cvar_fallback";
  status: "succeeded" | "failed" | "skipped" | "degraded";
  solver?: "clarabel" | "scs" | null;
  duration_ms?: number | null;
}
interface CascadeTimelineProps {
  phases: CascadePhase[];
  winnerSignal: string;            // sanitized label: "proposal_ready" | "proposal_cvar_infeasible" | "no_approved_allocation" | ...
  coverage?: number | null;        // 0..1 from cascade_telemetry.coverage (PR-A14)
  mode?: "live" | "settled";       // "live" drives dashed phase outlines while SSE streams; "settled" shows winner badge
}
```
Horizontal chevron row of 4 phases; winner phase highlighted; coverage bar (thin, full-width) under the row. All colors via `--terminal-*` + `--sev-*` tokens. No `svelte-echarts` — pure markup (cheap to render during SSE progress).

### B.7 `IpsSummaryStrip` — **wealth-local (allocation only)**
Path: `frontends/wealth/src/lib/components/allocation/IpsSummaryStrip.svelte`
Consumers: Allocation `[profile]` page.
Props:
```ts
interface IpsSummaryStripProps {
  cvarLimit: number | null;          // from StrategicAllocationResponse.cvar_limit
  lastApprovedAt: string | null;     // ISO datetime or null
  lastApprovedBy: string | null;
  profile: "conservative" | "moderate" | "growth";
  cadenceLabel?: string;             // default "Quarterly review"
}
```
Renders 3–4 `<Pill tone="neutral" size="xs">` pills: `CVaR ≤ X%`, `Approved {formatRelativeTime}`, `Profile: {label}`, `Cadence: {cadenceLabel}`. Read-only.

### B.8 `RegimeContextStrip` — **wealth-local (allocation only)**
Path: `frontends/wealth/src/lib/components/allocation/RegimeContextStrip.svelte`
Consumers: Allocation `[profile]` page. (Macro page already has inline regime rendering via StressHero — do not duplicate.)
Props:
```ts
interface RegimeContextStripProps {
  regime: string;           // e.g. "RISK_OFF"
  stressLevel: number;      // 0..1
  window: string;           // "1Y rolling"
}
```
Loader fetches `GET /macro/regime` once at page load; no live tick. Keeps UI copy plain-English (tooltip explains regime label).

### B.9 Keyboard nav util — **reuse existing**
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

### C.BUILDER (`/allocation/[profile]`)

All endpoints confirmed against A26 prompts and `(terminal)/allocation/[profile]/+page.server.ts`.

| Panel | Component | Source | Status |
|---|---|---|---|
| Strategic allocation (18 rows) | `StrategicAllocationTable` + `AllocationDonut` | `GET /portfolio/profiles/{profile}/strategic-allocation` → `StrategicAllocationResponse` (A26.3 Section A). Rows show `target_weight`, `drift_min/max`, `override_min/max`, `excluded_from_portfolio`, `approved_at/by`. | OK (PR #219 shipped). |
| Latest proposal | `ProposalReviewPanel` | `GET /portfolio/profiles/{profile}/latest-proposal` → `LatestProposalResponse` (A26.1 Section C) with `cascade_telemetry.proposed_bands[]`, `proposal_metrics`, `winner_signal`. 404 when no proposal exists. | OK (PR #219 shipped). |
| Propose trigger | `ProposeButton` | `POST /portfolio/profiles/{profile}/propose-allocation` → 202 + `{job_id, sse_url}` (A26.1 Section C). Open SSE via `fetch + ReadableStream`; events: `propose_started / optimizer_started / optimizer_phase_complete / propose_ready / propose_cvar_infeasible / completed`. | OK (PR #219 shipped). |
| Approve | Action inside `ProposalReviewPanel` | `POST /portfolio/profiles/{profile}/approve-proposal/{run_id}` → body `{confirm_cvar_infeasible: bool, operator_message?: string}` (A26.2 Section C). | OK (PR #219 shipped). Verify confirm-modal fires for `cvar_feasible=false`. |
| Override per block | `OverrideBandsEditor` | `POST /portfolio/profiles/{profile}/set-override` → body `{block_id, override_min, override_max, rationale}` (A26.2 Section D). | OK (PR #219 shipped). |
| Approval history | `ApprovalHistoryTable` | `GET /portfolio/profiles/{profile}/approval-history?limit=5&offset=N` → `ApprovalHistoryResponse` (A26.3 Section A). | OK (PR #219 shipped). |
| Cascade timeline | `CascadeTimeline` (NEW §B.6) | Data subset of `latest-proposal.cascade_telemetry` already fetched. Additionally consumed live during SSE propose events (`mode="live"` during stream, `mode="settled"` after). NO new endpoint. | **NEW — PR-4 ships this**. |
| Regime strip | `RegimeContextStrip` (NEW §B.8) | `GET /macro/regime` (shared with Macro page). Fetched once at page load via loader. | **NEW — PR-4 ships this**. |
| IPS summary strip | `IpsSummaryStrip` (NEW §B.7) | Derived client-side from `StrategicAllocationResponse.cvar_limit` + `last_approved_at` + `last_approved_by` + static cadence label. NO new endpoint. | **NEW — PR-4 ships this**. |

**No backend endpoint is introduced by PR-4.** All data is already served by A26.1/A26.2/A26.3 endpoints. `cascade_telemetry.phases[]` structure is read from `LatestProposalResponse.cascade_telemetry` (JSONB); verify field shape against A26.1 Section B telemetry schema at PR-4 open.

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
Files: `(terminal)/allocation/**`, `lib/components/allocation/**` (NOT `(terminal)/portfolio/builder/**` — that legacy surface is out of scope for PR-4).
- `.toFixed(` — grep. Expect 0 (PR #219 shipped using `@netz/ui` formatters); fix any residue.
- `.toLocaleString(` — hold 0.
- `new Intl.NumberFormat` / `DateTimeFormat` — hold 0.
- `new EventSource` — **hold 0**. SSE in `ProposeButton` uses `fetch + ReadableStream`.
- `localStorage` / `sessionStorage` — hold 0.
- Hardcoded hex in new `CascadeTimeline` coverage bar — **must use** `--terminal-status-success` / `--sev-warn` / `--sev-critical`.
- Emojis — hold 0.
- `{#each … as x}` without `(x.id)` — 0 (18-block tables must key on `block_id`; cascade phases must key on `phase.id`).

### D.9 CI extension
Extend `scripts/check-terminal-tokens-sync.mjs` to grep the 3 new route dirs:
```
(terminal)/terminal-screener/**
(terminal)/macro/**
(terminal)/allocation/**
```
Add to existing list (Terminal.html sprint covered only `(terminal)/portfolio/live/**`). Do NOT add `(terminal)/portfolio/builder/**` — that legacy surface is outside the parity target and may be retired in a follow-up.

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

### E.BUILDER (`/allocation/[profile]`)
- **Visual**: 1440×900 parity with the **sanitized** `Netz Terminal - Builder.html` (output surfaces only — regime strip + cascade timeline + weights table + diff bars + approval history). No input sliders, no tab navigation, no ActivationBar.
- **Runtime**:
  - Page loads cleanly for all 3 profiles (`conservative / moderate / growth`) against the dev DB canonical org.
  - `RegimeContextStrip` renders current regime/stress/window from `/macro/regime`.
  - `IpsSummaryStrip` renders CVaR pill + approval metadata pills above the 2-column grid.
  - `CascadeTimeline` renders the 4 phase chevrons with winner highlighted + coverage bar tint (§B6 thresholds).
  - During SSE propose stream, `CascadeTimeline` is rendered inline inside `ProposeButton`'s progress area (mode="live", phases advance as `optimizer_phase_complete` events arrive). After `completed`, panel flips to `ProposalReviewPanel` with mode="settled".
  - Approve `cvar_feasible=false` proposal still requires confirm modal; body includes `confirm_cvar_infeasible: true`.
  - `OverrideBandsEditor` refuses save without rationale (min 10 chars).
  - ZERO ambiguity that the proposal view is read-only — all edit affordances live in `OverrideBandsEditor` per-block modal; Strategic table cells are never directly editable (regression guard against §G.BUILDER.3).
- **Lint**: grep §D.BUILDER all 0.
- **Affordance check (§G.BUILDER.3 regression guard)**:
  - Diff bars hover cursor is `default`, not `pointer`.
  - Weights/target cells have no click handlers.
  - "Override" action icon is the ONLY focusable interactive element in rows.

### E.ALL (cross-page)
- `pnpm -F wealth check` exits 0.
- Playwright smoke (extend `terminal.spec.ts` from PR #234):
  - Screener: `/` → filter chip renders on set → `ESC` clears FocusMode.
  - Macro: drag regime cell → Hero class updates → no network POSTs.
  - Builder (`/allocation/{profile}`): page loads → cascade timeline mounts with 4 phases + coverage bar in `ProposalReviewPanel` when a proposal exists; propose SSE drives live-mode cascade timeline progression.
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

### PR-4 — `feat/terminal-parity-builder-on-propose-approve`
**Scope = re-skin + 3 new read-only primitives on top of the existing propose→approve surface (PR #219).** No backend changes, no new endpoints, no input sliders.

**Edits:**
- NEW `CascadeTimeline.svelte` (§B.6) wealth-local in `components/allocation/`.
- NEW `IpsSummaryStrip.svelte` (§B.7) wealth-local in `components/allocation/`.
- NEW `RegimeContextStrip.svelte` (§B.8) wealth-local in `components/allocation/`.
- Mount `<CascadeTimeline>` inside `ProposalReviewPanel` (between metrics row and diff bars) AND inside `ProposeButton` live-progress area during SSE stream.
- Mount `<IpsSummaryStrip>` + `<RegimeContextStrip>` in `/allocation/[profile]/+page.svelte` above the 2-column grid.
- `data-allocation-root` attribute + LayoutCage padding override matching screener density.
- Token/density re-skin on `StrategicAllocationTable`, `ProposalReviewPanel`, `ApprovalHistoryTable`, `OverrideBandsEditor` — remap any legacy class names to `--terminal-*`; remove any residual hex.
- Lint sweep `.toFixed` / `Intl.*` across `lib/components/allocation/**`.
- Extend `scripts/check-terminal-tokens-sync.mjs` with `(terminal)/allocation/**` (if not already covered by PR-1 CI edit).
- Playwright smoke extension: propose→approve flow with cascade timeline visible (live + settled modes).

**Out of scope (forbidden in PR-4):**
- Any edit under `/(terminal)/portfolio/builder/**` (legacy surface).
- Any CVaR slider / turnover slider / min-weight slider / max-single-position slider.
- Any IC views / factor tilts / region caps UI.
- Any tab navigation (REGIME / WEIGHTS / RISK / STRESS / BACKTEST / MONTE CARLO / ADVISOR).
- Any `ActivationBar` / `RunControls` / dry-run button.
- PR-A13 achievable-return band panel.
- Backend endpoint changes (cascade_telemetry shape is consumed as-is).

**Dependencies:** PR-1 primitives (`MiniSparkline` unused here, `Drawer` unused here — no hard dep). Independent of PR-2/PR-3.
**Size estimate:** 3 new components + 4 edits + lint sweep + CI + Playwright. ~420 LoC.

### PR-5 (optional if PR-4 overflows) — `feat/terminal-parity-builder-lint-sweep`
Splits the token/density re-skin + `.toFixed` sweep out of PR-4 if the 3 new primitives + their integration exceeds one Opus session. Trigger condition: `CascadeTimeline` + live-mode SSE integration lands in PR-4a; re-skin lands in PR-4b.

---

## G. Open risks per page

### G.SCREENER
1. **`nav_trend_sparkline` column may not exist in `fund_risk_metrics`.** Must verify at PR-2 open. If absent, ship MiniSparkline column hidden; add backend task to `global_risk_metrics` worker (lock 900_071). Never compute sparkline client-side — defeats the point of pre-computed risk metrics.
2. **TerminalDataGrid virtualization interaction with keyboard row focus.** Row focus via DOM `.focus()` may jump scroll if virtualized row is out of viewport. Mitigate: `scrollIntoView({ block: "nearest" })` on focus change; verify in Playwright.
3. **FilterChipRow vs TerminalScreenerFilters duplication.** Chip row is derived from URL state; filter rail writes to URL. Source-of-truth clash if chip X-removal and rail checkbox get out of sync. Mitigate: chip `onRemove` calls the same `handleFiltersChange` as rail; never writes to a separate store.

### G.MACRO
1. **RegimeMatrix drag-drop on touch devices.** Pointer events cover touch, but verify on tablet bundle preview. Scope: desktop-first (Andrei runs terminal on 32″ monitor per memory); touch = nice-to-have.
2. **Simulated regime leak into global `pinnedRegime`.** Must not propagate. Enforce by putting `macroSimulationStore` in page-local scope — do NOT import from `$lib/state/*` (which is app-global).
3. **SparklineWall live-tick subscription churn.** MarketDataStore subscribe/unsubscribe on mount/unmount. Verify `$effect` cleanup unsubscribes all 3 proxies. WS reconnect during page switch shouldn’t leak listeners.
4. **Tiingo quote for UUP/IEF may not be in default tenant subscription basket.** Backend `MarketDataStore` ticker whitelist — if UUP isn’t subscribed, sparkline stays REST. Flag and defer; not a blocker.

### G.BUILDER (`/allocation/[profile]`)
1. **Bundle confusion — legacy Builder surfaces tempt re-implementation.** Opus executor reading the bundle may try to port calibration sliders / IC views / factor tilts / `RunControls` RUN button / ActivationBar tab gates because the HTML+JSX still contain them. **Mitigation:** the §BUILDER SCOPE PIVOT block at the top of §A.BUILDER is the anchor; re-read before any edit. Any PR-4 commit touching `/(terminal)/portfolio/builder/**` or introducing a CVaR slider / turnover slider / factor-tilts / IC-views UI is out of scope — reject in review.
2. **Cascade telemetry shape drift.** `cascade_telemetry.phases[]` schema shipped by A26.1 Section B may differ slightly from what `CascadeTimeline` expects. Verify at PR-4 open by fetching `latest-proposal` from dev DB canonical org and pasting the JSONB sample into the PR body. If shape differs (e.g., flat dict keyed by phase name vs. list), adapt `CascadeTimeline` props — do NOT change backend telemetry shape in PR-4.
3. **Read-only vs. editable affordance ambiguity.** bundle's Weights / Risk / Stress / Backtest tabs historically felt "tweakable" because they sat next to input sliders. In the propose→approve model, those outputs are read-only. **Mitigation:** no hover-cursor=pointer on result cells; no inline editing controls; overrides are explicitly gated behind the `OverrideBandsEditor` modal (per-block), never as a cell edit. Acceptance criteria §E.BUILDER enforces this.
4. **Live-mode vs. settled-mode cascade timeline.** During SSE propose stream, phases arrive sequentially (`optimizer_phase_complete`). `CascadeTimeline` must degrade gracefully: show pending / in-progress / complete states per phase without flicker. Avoid replacing the component on every event — mutate `phases[]` in place via `$state`.
5. **`RegimeContextStrip` depends on `/macro/regime`.** That endpoint may not be mounted on the wealth frontend's standard loader context (Macro page fetches it directly). Confirm at PR-4 open that the server loader can call `/macro/regime` without additional auth scope. If not, strip this element and flag as a backlog item (fallback: render without regime strip; don't block PR).
6. **PR-A13 achievable-return band UX is a future sprint.** Memory flags PR-A13 UX brief exists (2026-04-17). PR-4 visually ships the propose→approve surface; the feasibility-frontier / achievable-return band panel is out of scope. If Opus attempts to bundle, split into a separate PR.
7. **Legacy `/portfolio/builder` retirement decision not yet made.** That route still mounts tabs + calibration sliders. PR-4 must NOT edit it (scope guard). Separate post-sprint decision: delete the route, leave it dark, or re-target it to embed the new allocation surface. Flag for Andrei.

---

## H. Execution order

**Andrei’s suggestion accepted with one swap:**

1. **PR-1 (primitives)** — unblocks both Screener + Macro. Small, low-risk, merge first.
2. **PR-2 (Screener)** — most isolated; filters + grid rendering. No shell changes. Single data source. Validates MiniSparkline in production.
3. **PR-3 (Macro)** — introduces RegimeMatrix + Drawer. Depends on PR-1 drawer. Visual complexity mid-tier.
4. **PR-4 (Builder = `/allocation/[profile]` propose→approve re-skin)** — 3 new read-only primitives (`CascadeTimeline`, `IpsSummaryStrip`, `RegimeContextStrip`) on top of PR #219 surface. No dependency on PR-2/PR-3; could run in parallel after PR-1 but sequenced last to surface any breakage from Screener/Macro primitive changes before touching the governance-critical allocation page.

Rationale: primitives before consumers; Screener validates shared primitives in simplest context; Macro stress-tests Drawer + live-tick wiring; Builder (`/allocation/[profile]`) consumes stable primitives + ships the scope-pivot read-only primitives last. Split into PR-4a (components + integration) and PR-4b (re-skin + lint sweep) if PR-4 exceeds one Opus session — splitting is recommended given the scope-pivot risk (see §G.BUILDER.1): PR-4a can focus all attention on "do not implement legacy bundle inputs" while PR-4b is purely mechanical token/density work.

---

## Appendix — Post-merge backlog (not this sprint)

- PR-A13 achievable-return band panel for `/allocation/[profile]` (CVaR sensitivity / feasibility frontier visualization).
- Retirement decision on legacy `/(terminal)/portfolio/builder` route (delete / dark / redirect to `/allocation/[profile]`).
- CASCADE detail drawer (expand `CascadeTimeline` phase chevron → show full `cascade_telemetry` JSONB per phase including solver / κ / degraded signals).
- SparklineWall AREA / BARS modes (Macro §M7).
- `nav_trend_sparkline` column in `global_risk_metrics` worker (if missing).
- Tiingo subscription basket expansion for macro proxies (UUP/IEF).
- Touch support for RegimeMatrix drag-drop.
- Post-approval analytics tabs (Monte Carlo / Backtest) surfaced elsewhere than the governance page — candidate home is `/portfolio/[id]/analytics`.
