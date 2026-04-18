# Netz Terminal Parity — `/portfolio/live`

**Date:** 2026-04-18
**Owner:** Andrei
**Scope decision locked:** Terminal.html parity for `(terminal)/portfolio/live` ONLY. Macro / Builder / Screener are follow-up sprints.
**Execution model:** 3–5 independently-mergeable sub-PRs sized for a single Opus session each (Andrei runs parallel Gemini + Opus sessions; do not cross-touch).

---

## 0. Ground truth & assumptions

- Figma bundle (`Terminal.html`, `terminal.css`, `terminal-app.jsx`, `terminal-chart.jsx`, `terminal-panels.jsx`, `terminal-data.jsx`) is NOT checked into this repo. Opus must treat the Figma file as the visual oracle; tokens listed in §B are the canonical extraction. If the bundle is later committed under `docs/design/terminal-bundle/`, Opus should diff against it at visual-QA time only.
- Existing infra to KEEP: `TerminalShell` + `TerminalTopNav` + `TerminalContextRail` + `TerminalStatusBar` + `LayoutCage` + `CommandPalette` in `packages/investintell-ui`-adjacent `frontends/wealth/src/lib/components/terminal/shell/`. `MarketDataStore` (`market-data.svelte.ts`) already wires Tiingo WS via `/api/v1/market-data/live/ws`. **Do not rewrite the shell.**
- Existing token file `packages/investintell-ui/src/lib/tokens/terminal.css` uses the `--terminal-*` namespace. The Figma bundle uses `--term-void`, `--fg-primary`, etc. **Decision:** keep the `--terminal-*` namespace as canonical; add `--term-*` as aliases ONLY if the Figma bundle's JS touches them at runtime (it doesn't — tokens are CSS-only). No aliases needed.
- Tweaks panel state = **in-memory `$state` only, session-scoped**. No localStorage, no URL param (keeps shell clean). Andrei to confirm at PR-1 review. If he pushes back, switch to `?density=compact&accent=cyan&theme=light` URL param (still zero storage).
- `terminal-screener` is canonical; `(app)/research` and `(terminal)/research` flagged for deprecation in a later sprint — **out of scope here**.

---

## A. Diff-style audit per existing file

Each row: **Current** → **Gap** → **Patch**.

### A.1 `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte`

| # | Current | Gap vs Figma | Patch |
|---|---|---|---|
| 1 | Line 495: `(absDrift * 100).toFixed(1)` for drift alert title. | Violates frontend formatter discipline. | Replace with `formatPpDrift(drift)` from new `@netz/ui` formatter (signed, "+2.3pp" / "−1.1pp", tabular). |
| 2 | Hard-coded grid `grid-template-columns: 280px 1fr 280px` + `flex: 60/25/15` rails. | Figma widths are 280/1fr/320 with denser typography at density=compact. | Widths stay; rail sizes must react to `[data-density="compact"]` (row heights shrink 22px→18px, fonts 11px→10px). Expose via data-attrs set by Tweaks panel. |
| 3 | `lw-shell { height: calc(100vh - 88px); }` inline. | Should consume `var(--terminal-shell-cage-height)` already defined. | Replace literal calc with token. |
| 4 | `data-live-root` attribute is only used by `:global(.lc-cage--standard:has([data-live-root])) { padding: 0 !important; }`. | OK but brittle `:has()`. | Leave — this is a known pattern from `feedback_layout_cage_pattern.md`; do NOT replace with flex/grid. |
| 5 | Portfolio dropdown is re-implemented inline (lw-portfolio-trigger). | Figma uses same control on Builder + Macro (need reuse). | Extract `<PortfolioPicker />` into `frontends/wealth/src/lib/components/terminal/live/` (keep wealth-local for now; promote to `@netz/ui` only when second consumer appears — see `feedback_tokens_vs_components.md`). |
| 6 | No Tweaks panel mount. | Figma has a floating gear (bottom-right) + side drawer with density/accent/theme toggles. | Mount `<TerminalTweaksPanel />` at page root, trigger via `Shift+T` + floating button. |
| 7 | Right rail: `NewsFeed` (55) + `MacroRegimePanel` (45). | Figma right rail has News + Alert Stream (not Macro). Macro lives in center drift panel. | **DECISION:** keep current layout — Andrei locked this in Phase 5 (`feedback_live_workbench_vision.md`). Figma → reality delta is acceptable. Flag in §H. |
| 8 | Regime matrix pin drag UX. | Not present — `MacroRegimePanel` currently read-only. | Add drag-drop on regime cells → fires `$state` `simulatedRegime`, propagates to chart overlay + summary only. **No backend write.** Call out in UI "SIMULATION" banner. |
| 9 | Timeframe prop: `"1Y"` coerced to `"3M"` for chart (`timeframe={chartTimeframe === "1Y" ? "3M" : chartTimeframe}`). | Chart should render 1Y properly. | Bug: delete the coercion, fix `TerminalPriceChart` to accept `1Y`. Flag as scope creep — if it requires new REST aggregation, defer to follow-up. |

### A.2 `frontends/wealth/src/lib/components/terminal/shell/TerminalStatusBar.svelte`

| # | Current | Gap | Patch |
|---|---|---|---|
| 1 | Line 91: `new Date().toISOString().substring(11, 19) + " UTC"` | Not using shared formatter. Duplicated logic vs Figma mono clock. | Replace with `formatMonoTime(new Date(), "utc")` from new `@netz/ui/formatters/mono`. Keep the 1s `setInterval` (correct `$effect` cleanup already in place). |
| 2 | `connectionStatus` hardcoded `"connecting"` upstream in `TerminalShell.svelte:81`. | No live aggregation from `MarketDataStore`. | In PR-3, pass `marketStore.status` through context to the shell (map `connected`→`open`, `reconnecting`→`degraded`, etc.). |

### A.3 `frontends/wealth/src/lib/components/terminal/shell/TerminalShell.svelte`

| # | Current | Gap | Patch |
|---|---|---|---|
| 1 | `setInterval(fetchDDQueueCount, 60_000)` in $effect. | Fine — cleanup present. | No-op. |
| 2 | `orgName = "NETZ"`, `userInitials = "AR"` hardcoded. | OK per plan notes — Phase 2+. | No-op for this sprint. |

### A.4 `frontends/wealth/src/lib/components/terminal/shell/TerminalTopNav.svelte`

| # | Current | Gap | Patch |
|---|---|---|---|
| 1 | `setInterval(fetchRegime, 5 * 60 * 1000)` — macro regime poll. | OK. | No-op. |
| 2 | No breadcrumb rendering. | Figma has persistent `Screener → Terminal → Macro → Builder` breadcrumb row. | Mount `<TerminalBreadcrumb />` as a new 28px row BELOW TopNav but ABOVE LayoutCage. Requires updating `TerminalShell` grid from `32px 1fr 28px` to `32px 28px 1fr 28px`. Adjust `--terminal-shell-topbar-height` → 60px OR add `--terminal-shell-breadcrumb-height: 28px` and `--terminal-shell-cage-height: calc(100vh - 116px)`. |

### A.5 `frontends/wealth/src/routes/(terminal)/+layout.svelte`

| # | Current | Gap | Patch |
|---|---|---|---|
| 1 | Plain `TerminalShell` wrapper, sets `MarketDataStore` context. | Needs to also set `TerminalTweaksContext` (density/accent/theme). | Create `terminal-tweaks.svelte.ts` store, instantiate in layout, `setContext(TERMINAL_TWEAKS_KEY, ...)`. Bind `data-density` / `data-accent` / `data-theme` on `<TerminalShell>` root element. |

### A.6 `frontends/wealth/src/lib/components/terminal/live/*.svelte` (scan)

- **No** `.toFixed` / `toLocaleString` / `toLocaleTimeString` found in the `live/` directory per grep. Good.
- **No** localStorage / postMessage found. Good.
- **No** `EventSource` found. Good.
- `MacroRegimePanel.svelte` — read-only; needs drag-drop simulation overlay (§A.1 #8). New prop `onSimulate?: (regime) => void` or emit via `$bindable`.
- `TradeLog`, `AlertStreamPanel`, `NewsFeed` — verify keyed `{#each (item.id)}` (likely OK but must enforce in PR-4 QA sweep).

### A.7 `frontends/wealth/src/lib/components/portfolio/live/charts/TerminalPriceChart.svelte`

| # | Current | Gap | Patch |
|---|---|---|---|
| 1 | Uses `lightweight-charts`, accepts `lastTick` from MarketDataStore. | Confirms Tiingo WS live. | No `setInterval` sim to delete — grep confirmed clean. Just verify visual parity of candle vs line fallback. |
| 2 | Single series type (line today). | Figma chart-type selector exposes Candle + Line in the toolbar. | Widen `TerminalPriceChart` to a dual-series component — see §A.9. Scope-locked in PR-4 (moved out of Open Risks). |

### A.9 `TerminalPriceChart` — dual-mode (Candle / Line) spec

**Prop contract (separate series props, single `mode` driver — avoids union narrowing pain):**

```ts
export interface OHLCPoint {
    time: UTCTimestamp; // lightweight-charts time (s epoch or business day)
    open: number;
    high: number;
    low: number;
    close: number;
}
export interface LinePoint {
    time: UTCTimestamp;
    value: number; // typically close
}

export interface TerminalPriceChartProps {
    mode: "candle" | "line";          // default "candle"
    candleData: OHLCPoint[];          // required when mode==="candle"
    lineData: LinePoint[];            // required when mode==="line"
    lastTick?: { time: UTCTimestamp; open?: number; high?: number; low?: number; close: number };
    timeframe: "1D" | "1W" | "1M" | "3M" | "6M" | "1Y";
    ticker: string;
    height?: number;
}
```

**Rendering contract:**
- Internally maintains ONE `IChartApi` instance (never recreated on `mode` flip).
- On `mode` change: call `chart.removeSeries(currentSeries)`, then `chart.addCandlestickSeries(...)` OR `chart.addLineSeries(...)`, then `series.setData(candleData | lineData)`.
- **Before swap**, capture `chart.timeScale().getVisibleRange()` and `chart.subscribeCrosshairMove` snapshot; **after swap**, restore via `setVisibleRange(...)` and re-subscribe. Prevents viewport reset on toggle.
- Live tick handling:
  - Candle mode: if `lastTick` arrives for current bar's `time`, call `series.update({ time, open, high, low, close })` where high/low are rolled from existing bar. If `lastTick` lacks OHLC (ticks-only backend), synthesize locally: see §D note.
  - Line mode: `series.update({ time, value: lastTick.close })`.
- No flicker: the swap path must NOT unmount the `<div>` container. Do NOT use `{#if mode === "candle"}` on the series layer — bind series lifecycle inside `$effect` that depends on `mode`.

### A.8 `MarketDataStore` (`market-data.svelte.ts`)

- Already Tiingo WS + REST fallback. No `setInterval` simulation. No changes needed for parity. **Confirmed clean** — Andrei's instruction "delete bundle's setInterval sim" is a non-op in our codebase (the sim only ever existed in the Figma bundle's `terminal-data.jsx`; it was never ported).

---

## B. New `@netz/ui` additions

All paths relative to `packages/investintell-ui/src/lib/`.

### B.1 `tokens/terminal.css` — **EXTEND** (existing file; do not replace)

Existing file is the canonical `--terminal-*` namespace. Add:

```css
/* ── Runtime tweak surfaces ─────────────────────────────── */
/* Density: standard (default) vs compact (Bloomberg-tight).
   Switched via [data-density="compact"] on terminal-root.    */
:root[data-density="compact"],
[data-surface="terminal"][data-density="compact"] {
	--terminal-space-1: 2px;
	--terminal-space-2: 6px;
	--terminal-space-3: 10px;
	--terminal-space-4: 12px;
	--terminal-text-10: 9px;
	--terminal-text-11: 10px;
	--terminal-text-12: 11px;
	--terminal-text-14: 12px;
	--terminal-shell-topbar-height: 28px;
	--terminal-shell-breadcrumb-height: 24px;
	--terminal-shell-cage-height: calc(100vh - 80px);
	--t-row-height: 18px;
}

:root,
[data-surface="terminal"] {
	--t-row-height: 22px;
	--t-size-hero: var(--terminal-text-24);
	--t-size-kpi: var(--terminal-text-20);
	--t-size-label: var(--terminal-text-10);
}

/* Accent: user-selectable. Default amber (institutional). */
[data-accent="cyan"] {
	--terminal-accent-amber: var(--terminal-accent-cyan);
	--terminal-accent-amber-dim: var(--terminal-accent-cyan-dim);
}
[data-accent="violet"] {
	--terminal-accent-amber: var(--terminal-accent-violet);
	--terminal-accent-amber-dim: var(--terminal-accent-violet-dim);
}

/* Severity scale for alerts (used by AlertStreamPanel + ticker). */
:root,
[data-surface="terminal"] {
	--sev-info: var(--terminal-accent-cyan);
	--sev-warn: var(--terminal-status-warn);
	--sev-critical: var(--terminal-status-error);
	--up: var(--terminal-status-success);
	--down: var(--terminal-status-error);
}

/* Light theme — institutional white, still mono-first. */
[data-theme="light"],
[data-theme="light"][data-surface="terminal"] {
	--terminal-bg-void: #f5f5f0;
	--terminal-bg-panel: #ffffff;
	--terminal-bg-panel-raised: #fafaf6;
	--terminal-bg-panel-sunken: #ededed;
	--terminal-bg-overlay: #ffffff;
	--terminal-bg-scrim: rgba(245, 245, 240, 0.72);
	--terminal-fg-primary: #0a0a0a;
	--terminal-fg-secondary: #3d3d38;
	--terminal-fg-tertiary: #6b6b63;
	--terminal-fg-muted: #b8b8b0;
	--terminal-fg-disabled: #d8d8d0;
	--terminal-fg-inverted: #ffffff;
}
```

Hex values added here are **the only permitted location** per existing file comment.

### B.2 `formatters/mono.ts` — **NEW**

```ts
// packages/investintell-ui/src/lib/formatters/mono.ts
//
// Mono-friendly formatters for terminal surfaces. All outputs are
// tabular-safe (stable column widths) and locale-independent.

/**
 * UTC clock string "HH:MM:SS UTC" (ISO extraction). Zero allocation
 * beyond the Date itself. `kind` = "utc" (default) or "local".
 */
export function formatMonoTime(d: Date, kind: "utc" | "local" = "utc"): string;

/**
 * Compact currency: $1.23B / $987M / $12.3K. Negative prefix "−".
 * Pass `digits` (default 2). Returns "—" for null/undefined.
 */
export function formatCompactCurrency(
	value: number | null | undefined,
	opts?: { digits?: number; currency?: "USD" | "EUR" | "BRL" }
): string;

/**
 * Percentage-point drift: "+2.3pp", "−1.1pp", "0.0pp". Input is a
 * fraction (0.023 → "+2.3pp"). Uses `digits` (default 1). "—" for
 * null. Sign uses the Unicode minus (U+2212) for column alignment.
 */
export function formatPpDrift(
	fractionDelta: number | null | undefined,
	digits?: number
): string;

/**
 * Terminal percent: "12.34%", "-0.05%". Input is a fraction.
 * Tabular-nums. Digits default 2.
 */
export function formatMonoPercent(
	fraction: number | null | undefined,
	digits?: number
): string;
```

All four re-exported from `packages/investintell-ui/src/lib/index.ts`. No ESLint rule changes needed — existing rule forbids `.toFixed`/`Intl` in frontend code, which steers callers to these.

### B.3 `components/terminal/` primitives — **NEW**

Directory: `packages/investintell-ui/src/lib/components/terminal/`.

Each component has a **single-purpose, read-only** props contract (no `$bindable` unless noted). All are tokenized — **zero hex inline**.

#### `Pill.svelte`
```ts
interface PillProps {
	label: string;
	tone?: "neutral" | "accent" | "success" | "warn" | "error";
	size?: "xs" | "sm";
	as?: "button" | "span"; // default span; button emits onclick
	onclick?: () => void;
}
```

#### `Kbd.svelte`
```ts
interface KbdProps {
	keys: string[]; // e.g. ["Shift", "T"] rendered as [Shift]+[T]
}
```

#### `KpiCard.svelte`
```ts
interface KpiCardProps {
	label: string;             // uppercase caps auto-applied
	value: string;             // pre-formatted (call formatters before pass)
	delta?: string;            // pre-formatted +/- delta (e.g. "+1.2pp")
	deltaTone?: "up" | "down" | "neutral";
	size?: "sm" | "md" | "lg"; // drives --t-size-*
	mono?: boolean;            // default true
	loading?: boolean;
}
```

#### `DensityToggle.svelte`
```ts
interface DensityToggleProps {
	value: "standard" | "compact";
	onChange: (v: "standard" | "compact") => void;
}
```

#### `AccentPicker.svelte`
```ts
interface AccentPickerProps {
	value: "amber" | "cyan" | "violet";
	onChange: (v: "amber" | "cyan" | "violet") => void;
}
```

#### `ThemeToggle.svelte`
```ts
interface ThemeToggleProps {
	value: "dark" | "light";
	onChange: (v: "dark" | "light") => void;
}
```

All primitives exported from `packages/investintell-ui/src/lib/index.ts` under subpath `/terminal`.

### B.4 Fonts — `styles/typography.css` additions

```css
/* Scoped terminal fonts — do NOT leak into (app). */
[data-surface="terminal"] {
	font-family: var(--terminal-font-mono);
}
[data-surface="terminal"] [data-font="sans"] {
	font-family: "IBM Plex Sans", Inter, Urbanist, system-ui, sans-serif;
}
```

Load via `@fontsource-variable/ibm-plex-mono` + `@fontsource-variable/ibm-plex-sans` (pnpm add in `packages/investintell-ui/package.json`). Imported once from the wealth root `+layout.svelte` already; just add the two new font packages.

Urbanist remains the default OUTSIDE `[data-surface="terminal"]` per `feedback_design_direction.md`.

---

## C. Terminal-scoped wiring

### C.1 `TerminalBreadcrumb.svelte` (new, in `frontends/wealth/src/lib/components/terminal/shell/`)

- 28px persistent row mounted by `TerminalShell` BETWEEN `TerminalTopNav` and `LayoutCage`.
- Content: `Screener → Terminal → Macro → Builder`, each a `<a>` with `data-sveltekit-preload-data`, href mapped:
  - Screener → `/terminal-screener`
  - Terminal → `/portfolio/live`
  - Macro → `/macro`
  - Builder → `/portfolio/builder`
- Active segment: matches current `page.route.id`; styled with `color: var(--terminal-accent-amber)` + underline.
- Keyboard: `Alt+1..4` jumps to each. Ignored when focus is inside an input/textarea/contenteditable (reuse existing detection from `TerminalShell`).
- Shell grid update: `grid-template-rows: var(--terminal-shell-topbar-height) var(--terminal-shell-breadcrumb-height) 1fr var(--terminal-shell-statusbar-height)`. Update `--terminal-shell-cage-height` to `calc(100vh - 116px)` (32 + 28 + 28 + padding residue absorbed by LayoutCage). Verify `lw-shell` height literal removed per §A.1 #3.

### C.2 `TerminalTweaksPanel.svelte` (new, `frontends/wealth/src/lib/components/terminal/shell/`)

- Floating gear button (bottom-right, `z: var(--terminal-z-toast)`).
- Opens as a right-side drawer (320px, full cage height).
- Contents: `<DensityToggle>`, `<AccentPicker>`, `<ThemeToggle>`, `<Pill label="LIVE SIM OFF" tone="neutral">` (no-op placeholder; Andrei gated Live Sim as always-off per scope decision).
- State: reads/writes `terminal-tweaks.svelte.ts` store (see C.4). **Zero storage.** Resets on full page reload — confirmed-and-accepted trade-off per Andrei's scope-decision #3.
- Shortcut: `Shift+T` toggles. Ignores inputs.

### C.3 `TerminalStatusBar` clock

- Replace `new Date().toISOString().substring(11, 19) + " UTC"` with `formatMonoTime(new Date(), "utc")`.
- Keep the `setInterval(tick, 1000)` + cleanup. Do NOT switch to `requestAnimationFrame` — 1Hz is correct.

### C.4 `terminal-tweaks.svelte.ts` (new, `frontends/wealth/src/lib/stores/`)

```ts
export const TERMINAL_TWEAKS_KEY = Symbol("netz:terminal-tweaks");

export interface TerminalTweaks {
	density: "standard" | "compact";
	accent: "amber" | "cyan" | "violet";
	theme: "dark" | "light";
	setDensity(v: "standard" | "compact"): void;
	setAccent(v: "amber" | "cyan" | "violet"): void;
	setTheme(v: "dark" | "light"): void;
}

export function createTerminalTweaks(): TerminalTweaks {
	let density = $state<"standard" | "compact">("standard");
	let accent = $state<"amber" | "cyan" | "violet">("amber");
	let theme = $state<"dark" | "light">("dark");
	return {
		get density() { return density; },
		get accent() { return accent; },
		get theme() { return theme; },
		setDensity(v) { density = v; },
		setAccent(v) { accent = v; },
		setTheme(v) { theme = v; },
	};
}
```

Layout wires `data-density`, `data-accent`, `data-theme` attributes on the `TerminalShell` root.

### C.5 Live data confirmation

- `MarketDataStore` → `TerminalPriceChart` (via `lastTick`) — **verified wired**.
- `MarketDataStore` → `Watchlist` (via `marketStore.priceMap`) — verify in PR-1 smoke (likely OK — `handleWatchlistSelect` already consumes).
- `MarketDataStore` → `PortfolioSummary` (`marketStore.totalAum`, `marketStore.totalReturnPct`) — **verified wired**.
- No `setInterval` simulation to delete in-repo. If Opus greps `setInterval` in live components, they may touch only cleanup-safe timers in shell (already audited, keep).

---

## D. Data contracts per panel

| Panel | Component | Endpoint / Stream | Status | Notes |
|---|---|---|---|---|
| Portfolio picker | inline dropdown | `data.portfolios` (load function) | OK | Move to server load only (already done). |
| Watchlist | `Watchlist.svelte` | REST `/instruments` + WS `/api/v1/market-data/live/ws` (via MarketDataStore) | OK | Tiingo-backed. |
| Chart | `TerminalPriceChart.svelte` | REST `/market-data/historical/:ticker` + WS tick | **VERIFY OHLC** | Drop the 1Y→3M coercion (§A.1 #9). **Dual-mode (candle/line) spec §A.9.** Verify in PR-4: `/market-data/historical/:ticker` MUST return `{time, open, high, low, close}` rows — if it returns `{time, value}` only, backend gap. WS `lastTick` from Tiingo delivers last price only (no OHLC per tick); client aggregates ticks into the current bar (roll high = max(high, px), low = min(low, px), close = px) as interim until a dedicated 1m-bars stream is wired. Flag as backend follow-up if candle fidelity insufficient. |
| Portfolio summary | `PortfolioSummary.svelte` | MarketDataStore derived + `/model-portfolios/:id/actual-holdings` | OK | |
| Holdings table | `HoldingsTable.svelte` | `/model-portfolios/:id/actual-holdings` | OK | |
| Trade log | `TradeLog.svelte` | `/model-portfolios/:id/trades` (assume — verify in PR-2) | **VERIFY** | If the endpoint doesn't exist, flag as backend dependency. Likely exists — Phase 5 completed. |
| Alert stream | `AlertStreamPanel.svelte` | `/alerts/stream` SSE? REST poll? | **VERIFY** | Currently fed by `driftAlerts` synthetic in-page + `injectedAlerts` prop. Real live feed may be missing. **Flag as backend gap if not found.** |
| News feed | `NewsFeed.svelte` | `/market-data/news?tickers=` | OK | Poll-based. |
| Macro regime panel | `MacroRegimePanel.svelte` | `/macro/regime/latest` (used by TopNav already) | OK | Add drag-drop simulation client-only. |
| Rebalance focus mode | `RebalanceFocusMode.svelte` | `/model-portfolios/:id/rebalance/*` | OK | |

**Flagged backend gaps** (handoff to backend consultant, NOT this frontend sprint):
- **AlertStream live feed** — confirm SSE endpoint exists with `X-DEV-ACTOR` / Clerk JWT + single-flight.
- **Trade log endpoint** — confirm shape matches `TradeLog.svelte` props.

If either is missing, PR-4 (QA) flags + blocks, and we ship without a real stream (in-page synthesis only for alerts, fine per existing code).

---

## E. Violations cleanup checklist

Grep targets. Each must return 0 matches in `frontends/wealth/src/routes/(terminal)/**` + `frontends/wealth/src/lib/components/terminal/**` (excluding shell clock `formatMonoTime` callsite).

1. `.toFixed(` — current: **1 hit** (`+page.svelte:495`). Fix: `formatPpDrift`.
2. `.toLocaleString(` — current: 0. Hold line.
3. `.toLocaleTimeString(` — current: 0 (shell uses `toISOString().substring(...)` — still a violation, replace per §C.3).
4. `toISOString().substring` — current: 1 (`TerminalStatusBar.svelte:91`). Fix: `formatMonoTime`.
5. `localStorage` / `sessionStorage` — current: 0. Hold line.
6. `postMessage(` inside terminal namespace — current: 0. Hold line.
7. `new EventSource` — current: 0 in terminal. Hold line.
8. Hex literals (`#[0-9a-fA-F]{3,6}`) in `.svelte` / `.ts` under `frontends/wealth/src/lib/components/terminal/` and `(terminal)/` — must be 0. Audit: ESLint rule (add if missing — see ESLint §E.9).
9. `{#each ... as item}` without `(item.id)` key — 0 in live panels (verify at QA).
10. Emojis — 0. (Andrei has `feedback_no_emojis.md`.)
11. `new Intl.NumberFormat` / `new Intl.DateTimeFormat` — 0 inline. Hold line.

### E.9 ESLint rule

Verify `frontends/eslint.config.js` forbids hex in `.svelte` files under terminal paths. If not present, add in PR-1:
- Rule: `no-restricted-syntax` targeting `Literal[value=/#[0-9a-fA-F]{3,6}/]` scoped to `**/terminal/**` + `**/(terminal)/**`.

---

## F. Acceptance criteria

### F.1 Visual
- Screenshot parity with Figma at 1440×900 dark default, `data-density="standard"`.
- Density toggle → compact: every row shrinks to `--t-row-height: 18px`, fonts drop 1px, no reflow overflow.
- Accent picker → cyan → all amber surfaces (portfolio name, active breadcrumb, focus borders) switch in ≤1 frame.
- Theme toggle → light → full palette inversion without hex leaks.

### F.2 Lint
- `pnpm -F wealth lint` exits 0.
- `pnpm -F wealth check` exits 0 (type check).
- Grep checklist §E returns 0 matches (CI job `scripts/check-terminal-tokens-sync.mjs` extended with these patterns).

### F.3 Runtime
- Tiingo WS connects on live page mount (network tab: `wss://` upgrade with 101 Switching Protocols within 2s).
- First live tick propagates to chart + watchlist row ≤ 300ms after arrival.
- Theme / density / accent toggles work in-session, revert on hard reload (expected — no persistence).
- Zero console errors / warnings on clean mount.
- `Alt+1..4` breadcrumb nav works; `Shift+T` opens Tweaks; `C`/`L` flip chart type when chart is focused; none fire when typing in an input.
- **Chart type toggle:** clicking CANDLE / LINE (or pressing C / L) swaps the series instantly with no chart flicker, no container remount; visible time range is preserved across the swap; crosshair position is preserved if it was active. Default on mount is `candle`. Hard reload reverts to `candle` (no persistence, by design).

### F.4 Tests
- `packages/investintell-ui` unit tests for `formatMonoTime`, `formatCompactCurrency`, `formatPpDrift`, `formatMonoPercent` (edge cases: null, 0, ±sign, very large, very small).
- Svelte component tests (vitest + `@testing-library/svelte`) for:
  - `TerminalTweaksPanel` — shortcut toggles, callbacks fire, no DOM side effects outside drawer.
  - `TerminalBreadcrumb` — active segment derived from `page.route.id`, keyboard nav.
  - `KpiCard` — loading state, delta tone classes, size variants.
  - **ChartToolbar chart-type toggle** — default `candle`; click LINE → callback fires with `"line"` and `aria-pressed` flips; `C` key → `"candle"`, `L` key → `"line"`; keys ignored when a text input is focused; toggle is a `role="radiogroup"` with two `aria-pressed` buttons.
- Integration: `(terminal)/portfolio/live/+page.svelte` renders with empty `data.portfolios` → shows empty state; with 1 portfolio → shows full shell.

---

## G. Sequencing — 4 sub-PRs

Each PR is **independently mergeable** (no stacked deps). Each sized for one Opus session.

### PR-1 — **feat/terminal-ui-formatters-and-tokens**
Scope:
- `packages/investintell-ui/src/lib/formatters/mono.ts` + exports + tests.
- `packages/investintell-ui/src/lib/tokens/terminal.css` extensions (density / accent / theme / severity).
- Fonts: IBM Plex Mono + Sans package additions.
- ESLint rule for hex-in-terminal (§E.9).
Size: ~4 files new, 2 files edited. ~150 LoC + tests.

### PR-2 — **feat/terminal-ui-primitives**
Scope:
- `packages/investintell-ui/src/lib/components/terminal/{Pill,Kbd,KpiCard,DensityToggle,AccentPicker,ThemeToggle}.svelte`.
- Exports from `index.ts`.
- Vitest component tests for `KpiCard` + 2 snapshot tests.
Size: 6 components + index edit + tests. Depends on PR-1 tokens — **merge PR-1 first** but PR-2 can be opened in parallel once PR-1 is in review.

### PR-3 — **feat/terminal-shell-tweaks-and-breadcrumb**
Scope:
- `terminal-tweaks.svelte.ts` store.
- `TerminalTweaksPanel.svelte` + `Shift+T` shortcut.
- `TerminalBreadcrumb.svelte` + `Alt+1..4` shortcuts.
- `TerminalShell.svelte` grid update (+28px breadcrumb row, cage height recalc).
- `TerminalStatusBar.svelte` clock → `formatMonoTime`.
- `(terminal)/+layout.svelte` wires tweaks context + data attributes.
Size: 3 new components + 4 edits. ~400 LoC + tests.

### PR-4 — **feat/terminal-live-parity-and-cleanup**
Scope:
- `(terminal)/portfolio/live/+page.svelte`: `.toFixed` → `formatPpDrift`, `calc(100vh-88px)` → token, 1Y→3M coercion removal.
- `MacroRegimePanel.svelte` drag-drop simulation (client-only).
- `MarketDataStore` status → shell connection status wiring.
- **TerminalPriceChart dual-mode (Candle/Line)** per §A.9 — widen props, in-place series swap with visible-range + crosshair preservation, local tick aggregation for candle mode until bars stream ships.
- **ChartToolbar chart-type toggle (Candle | Line)** — segmented control rendered via the `Pill`/segmented primitive from PR-2 (use the `as="button"` variant, `aria-pressed`, grouped with `role="radiogroup"` and `aria-label="Chart type"`). Default `candle`. Parent page owns state as `let chartType = $state<"candle" | "line">("candle")` — **in-memory only, no localStorage, no URL param** (matches Tweaks panel policy). Keyboard shortcuts `C` / `L` when the chart container has focus (guard: ignore when a text input, textarea, or contenteditable has focus; reuse existing detection util). Visible label text `CANDLE` / `LINE` in mono caps, matching Figma chart-type selector.
- Visual QA against Figma at 1440×900 + 1920×1080.
- Playwright smoke (`test-browser` skill) for shortcut + WS handshake + density toggle + chart-type toggle.
Size: 5 files edited. ~280 LoC + smoke test + component test.

**Optional PR-5 (if scope bleeds)** — Hard-deprecate `(terminal)/research` (add `<meta http-equiv="refresh">` to `/terminal-screener` + banner). Separate sprint per Andrei's decision #6.

---

## H. Open risks

1. **RebalanceFocusMode already diverges from Figma.** It's a FocusMode overlay, Figma has it inline in the center column. Phase 5 decision (Andrei) was overlay. **Do NOT "fix" in this sprint** — if Opus reads Figma and flags it, point at `project_phase5_live_workbench_complete.md` and `feedback_live_workbench_vision.md`.
2. ~~`lightweight-charts` candle data shape mismatch.~~ **RESOLVED — scoped into PR-4 §A.9.** Dual-mode (Candle + Line) with in-place series swap is a confirmed feature, not a risk. Residual sub-risk: if `/market-data/historical/:ticker` does not return full OHLC (only close series), backend must add an OHLC response shape OR the client must aggregate raw ticks into 1m bars — flagged in §D as `VERIFY OHLC`.
3. **Font loading flicker.** IBM Plex additions may trigger FOUT on first cold load. Mitigate: `font-display: optional` on the Plex faces so the system mono renders immediately, Plex swaps in on next reload. Verify in PR-1.
4. **Tweaks drawer + LayoutCage `:has()` selector.** The `:global(.lc-cage--standard:has([data-live-root])) { padding: 0 !important; }` may conflict with the drawer if the drawer is mounted INSIDE the cage. Mount the drawer at the shell root (outside LayoutCage), NOT inside the page component. Andrei flagged this pattern in `feedback_layout_cage_pattern.md`.
5. **AlertStreamPanel has no real live feed today** (the in-page `driftAlerts` is synthetic). If backend SSE isn't ready, PR-4 flags it; we do NOT ship a fake live stream. Escalate to backend consultant.
6. **Breadcrumb collision with existing CommandPalette `g + s/l/r/m/a/p/n/d`** — `Alt+1..4` uses Alt namespace; no conflict. Confirmed.
7. **`--terminal-*` vs Figma `--term-*` naming.** If Opus tries to "harmonize" to `--term-*`, block it. The `--terminal-*` namespace is the established contract (already consumed by 40+ files per git log on `terminal-unification` branches).

---

## Appendix — Post-merge follow-up backlog (not this sprint)

- Terminal Macro parity (separate plan).
- Terminal Builder parity (separate plan).
- `terminal-screener` vs `(app)/research` consolidation + deprecation redirect.
- Rebalance FocusMode — decide if Figma's inline layout is worth returning to (requires re-litigating Phase 5 decision).
- AlertStream SSE backend contract (if flagged in D).
- Dedicated 1m-bars stream (if client-side tick aggregation in candle mode proves insufficient for fidelity).
