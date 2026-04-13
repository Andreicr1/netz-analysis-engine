# H2 -- Live Workbench Polish

**Branch:** `feat/harmonization-h2-live-polish` (from `main`)
**Depends on:** PR #141 merged (H0 primitives + LW factory)

---

## CONTEXT

The Live Workbench (Phase 5) was built before H0 extracted terminal primitives and the lightweight-charts factory. Two chart components (`TerminalPriceChart.svelte`, `TerminalResearchChart.svelte`) contain ~45 hardcoded hex values across JS chart configs and CSS `<style>` blocks. Two table components have a border that should use the token shorthand. `PortfolioSummary.svelte` has a status dot that can be replaced by the `LiveDot` primitive.

### Key Files (read ALL before editing)

| File | Role |
|---|---|
| `packages/investintell-ui/src/lib/charts/terminal-lw-options.ts` | `createTerminalLightweightChartOptions()` + `terminalLWSeriesColors()` factory |
| `packages/investintell-ui/src/lib/charts/terminal-options.ts` | `readTerminalTokens()` + `TerminalChartTokens` interface |
| `packages/investintell-ui/src/lib/tokens/terminal.css` | Token definitions (source of truth) |
| `frontends/wealth/src/lib/components/portfolio/live/charts/TerminalPriceChart.svelte` | Target: chart hex migration |
| `frontends/wealth/src/lib/components/research/terminal/TerminalResearchChart.svelte` | Target: chart hex migration + Urbanist removal |
| `frontends/wealth/src/lib/components/terminal/live/HoldingsTable.svelte` | Target: border fix |
| `frontends/wealth/src/lib/components/terminal/live/DriftMonitorPanel.svelte` | Target: border fix |
| `frontends/wealth/src/lib/components/terminal/live/PortfolioSummary.svelte` | Target: LiveDot composition |
| `frontends/wealth/src/lib/components/terminal/data/LiveDot.svelte` | H0 primitive to compose into PortfolioSummary |

### Factory API

```ts
import {
  createTerminalLightweightChartOptions,
  terminalLWSeriesColors,
} from "@investintell/ui";

// Chart options (spreads into createChart):
const opts = createTerminalLightweightChartOptions({
  timeVisible: true,        // default false
  secondsVisible: false,    // default false
  rightOffset: 5,           // default 5
  priceScaleMode: lc.PriceScaleMode.Percentage,  // optional
  scaleMargins: { top: 0.08, bottom: 0.08 },     // default
  crosshairColor: "#custom", // default: terminal-accent-amber
  fontSize: 10,             // default 10
});
const chart = lc.createChart(container, { autoSize: true, ...opts });

// Series colors:
const sc = terminalLWSeriesColors();
// sc.baseline  -- { topLineColor, topFillColor1/2, bottomLineColor, bottomFillColor1/2, priceLineColor }
// sc.navOverlay -- { color }
// sc.drawdown  -- { topLineColor, topFillColor1/2, bottomLineColor, bottomFillColor1/2 }
// sc.volatility -- { color }
// sc.regime    -- { topColor, bottomColor, lineColor }
```

---

## TASK 1: TerminalPriceChart.svelte

Path: `frontends/wealth/src/lib/components/portfolio/live/charts/TerminalPriceChart.svelte`

### 1A. Add imports (top of `<script>`)

After `import { onMount } from "svelte";` add:

```ts
import {
  createTerminalLightweightChartOptions,
  terminalLWSeriesColors,
} from "@investintell/ui";
```

### 1B. Replace JS chart config (lines 74-109)

**BEFORE:**
```ts
const c = lc.createChart(containerEl, {
  autoSize: true,
  layout: {
    background: { color: "transparent" },
    textColor: "#5a6577",
    fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
    fontSize: 10,
  },
  grid: {
    vertLines: { color: "rgba(255, 255, 255, 0.04)" },
    horzLines: { color: "rgba(255, 255, 255, 0.04)" },
  },
  crosshair: {
    vertLine: {
      color: "rgba(45, 126, 247, 0.3)",
      labelBackgroundColor: "#2d7ef7",
    },
    horzLine: {
      color: "rgba(45, 126, 247, 0.3)",
      labelBackgroundColor: "#2d7ef7",
    },
  },
  rightPriceScale: {
    mode: lc.PriceScaleMode.Percentage,
    borderVisible: false,
    scaleMargins: { top: 0.08, bottom: 0.08 },
  },
  timeScale: {
    borderColor: "rgba(255, 255, 255, 0.08)",
    timeVisible: true,
    secondsVisible: false,
    rightOffset: 5,
  },
  handleScroll: true,
  handleScale: true,
});
```

**AFTER:**
```ts
const opts = createTerminalLightweightChartOptions({
  timeVisible: true,
  priceScaleMode: lc.PriceScaleMode.Percentage,
});
const c = lc.createChart(containerEl, { autoSize: true, ...opts });
```

Note: The factory already sets `crosshairColor` to amber (replacing the alien blue `#2d7ef7`), `secondsVisible: false`, `rightOffset: 5`, `scaleMargins: { top: 0.08, bottom: 0.08 }`, `handleScroll: true`, `handleScale: true`.

### 1C. Replace Baseline series hex (lines 112-125)

**BEFORE:**
```ts
const s = c.addSeries(lc.BaselineSeries, {
  baseValue: { type: "price", price: 0 },
  topLineColor: "#2d7ef7",
  topFillColor1: "rgba(45, 126, 247, 0.10)",
  topFillColor2: "rgba(45, 126, 247, 0.01)",
  bottomLineColor: "#e74c3c",
  bottomFillColor1: "rgba(231, 76, 60, 0.01)",
  bottomFillColor2: "rgba(231, 76, 60, 0.06)",
  lineWidth: 2,
  priceLineVisible: true,
  priceLineColor: "rgba(45, 126, 247, 0.4)",
  lastValueVisible: true,
  title: "",
});
```

**AFTER:**
```ts
const sc = terminalLWSeriesColors();
const s = c.addSeries(lc.BaselineSeries, {
  baseValue: { type: "price", price: 0 },
  ...sc.baseline,
  lineWidth: 2,
  priceLineVisible: true,
  lastValueVisible: true,
  title: "",
});
```

Hex mapping (for reference -- these are handled by `sc.baseline`):
| Old hex | Factory field | Terminal token |
|---|---|---|
| `#2d7ef7` | `topLineColor` | `--terminal-accent-cyan` |
| `rgba(45, 126, 247, 0.10)` | `topFillColor1` | cyan @ 10% |
| `rgba(45, 126, 247, 0.01)` | `topFillColor2` | cyan @ 1% |
| `#e74c3c` | `bottomLineColor` | `--terminal-status-error` |
| `rgba(231, 76, 60, 0.01)` | `bottomFillColor1` | error @ 1% |
| `rgba(231, 76, 60, 0.06)` | `bottomFillColor2` | error @ 6% |
| `rgba(45, 126, 247, 0.4)` | `priceLineColor` | cyan @ 40% |

### 1D. Replace NAV line series hex (lines 128-136)

**BEFORE:**
```ts
const nav = c.addSeries(lc.LineSeries, {
  color: "#fbbf24",
  lineWidth: 2,
  title: "NAV",
  crosshairMarkerVisible: true,
  crosshairMarkerRadius: 3,
  priceLineVisible: false,
  lastValueVisible: true,
});
```

**AFTER:**
```ts
const nav = c.addSeries(lc.LineSeries, {
  ...sc.navOverlay,
  lineWidth: 2,
  title: "NAV",
  crosshairMarkerVisible: true,
  crosshairMarkerRadius: 3,
  priceLineVisible: false,
  lastValueVisible: true,
});
```

### 1E. CSS hex migration (`<style>` block)

Replace ALL hex values and hardcoded font-family in the `<style>` section. Every `rgba(255, 255, 255, ...)` border becomes `var(--terminal-border-hairline)` for consistency (intentional visual harmonization -- the old white-alpha borders were inconsistent with the token system).

| Selector | Property | Old value | New value |
|---|---|---|---|
| `.tpc-controls` | `border-bottom` | `1px solid rgba(255, 255, 255, 0.06)` | `var(--terminal-border-hairline)` |
| `.tpc-ticker` | `font-family` | `"JetBrains Mono", "SF Mono", monospace` | `var(--terminal-font-mono)` |
| `.tpc-ticker` | `font-size` | `11px` | `var(--terminal-text-11)` |
| `.tpc-ticker` | `letter-spacing` | `0.06em` | `var(--terminal-tracking-caps)` |
| `.tpc-ticker` | `color` | `#c8d0dc` | `var(--terminal-fg-secondary)` |
| `.tpc-status-badge` | `font-family` | `"JetBrains Mono", "SF Mono", monospace` | `var(--terminal-font-mono)` |
| `.tpc-status-delayed` | `color` | `#f59e0b` | `var(--terminal-status-warn)` |
| `.tpc-status-delayed` | `background` | `rgba(245, 158, 11, 0.12)` | `color-mix(in srgb, var(--terminal-status-warn) 12%, transparent)` |
| `.tpc-status-delayed` | `border` | `1px solid rgba(245, 158, 11, 0.25)` | `1px solid color-mix(in srgb, var(--terminal-status-warn) 25%, transparent)` |
| `.tpc-status-offline` | `color` | `#ef4444` | `var(--terminal-status-error)` |
| `.tpc-status-offline` | `background` | `rgba(239, 68, 68, 0.12)` | `color-mix(in srgb, var(--terminal-status-error) 12%, transparent)` |
| `.tpc-status-offline` | `border` | `1px solid rgba(239, 68, 68, 0.25)` | `1px solid color-mix(in srgb, var(--terminal-status-error) 25%, transparent)` |
| `.tpc-nav-toggle` | `font-family` | `"JetBrains Mono", "SF Mono", monospace` | `var(--terminal-font-mono)` |
| `.tpc-nav-toggle` | `color` | `#5a6577` | `var(--terminal-fg-tertiary)` |
| `.tpc-nav-toggle` | `border` | `1px solid rgba(255, 255, 255, 0.06)` | `var(--terminal-border-hairline)` |
| `.tpc-nav-toggle:hover` | `color` | `#fbbf24` | `var(--terminal-accent-amber)` |
| `.tpc-nav-toggle:hover` | `border-color` | `rgba(251, 191, 36, 0.2)` | `var(--terminal-accent-amber-dim)` |
| `.tpc-nav-toggle--active` | `color` | `#fbbf24` | `var(--terminal-accent-amber)` |
| `.tpc-nav-toggle--active` | `background` | `rgba(251, 191, 36, 0.08)` | `color-mix(in srgb, var(--terminal-accent-amber) 8%, transparent)` |
| `.tpc-nav-toggle--active` | `border-color` | `rgba(251, 191, 36, 0.25)` | `var(--terminal-accent-amber-dim)` |
| `.tpc-nav-toggle:focus-visible` | `outline` | `2px solid #fbbf24` | `var(--terminal-border-focus)` |
| `.tpc-right-controls .tpc-timeframes` | `border-left` | `1px solid rgba(255, 255, 255, 0.06)` | `var(--terminal-border-hairline)` NOTE: token is `border` shorthand; use `border-left: var(--terminal-border-hairline)` |
| `.tpc-tf-btn` | `font-family` | `"JetBrains Mono", "SF Mono", monospace` | `var(--terminal-font-mono)` |
| `.tpc-tf-btn` | `font-size` | `10px` | `var(--terminal-text-10)` |
| `.tpc-tf-btn` | `color` | `#5a6577` | `var(--terminal-fg-tertiary)` |
| `.tpc-tf-btn:hover` | `color` | `#c8d0dc` | `var(--terminal-fg-secondary)` |
| `.tpc-tf-btn:hover` | `background` | `rgba(255, 255, 255, 0.04)` | `var(--terminal-bg-panel-raised)` |
| `.tpc-tf-active` | `color` | `#2d7ef7` | `var(--terminal-accent-cyan)` |
| `.tpc-tf-active` | `border-color` | `rgba(45, 126, 247, 0.3)` | `var(--terminal-accent-cyan-dim)` |
| `.tpc-tf-active` | `background` | `rgba(45, 126, 247, 0.08)` | `color-mix(in srgb, var(--terminal-accent-cyan) 8%, transparent)` |
| `.tpc-tf-btn:focus-visible` | `outline` | `2px solid #2d7ef7` | `2px solid var(--terminal-accent-cyan)` |

**IMPORTANT:** The alien blue `#2d7ef7` in the active timeframe pill becomes `--terminal-accent-cyan` (the terminal's streaming data color), matching the baseline series line color. This is an intentional design correction.

---

## TASK 2: TerminalResearchChart.svelte

Path: `frontends/wealth/src/lib/components/research/terminal/TerminalResearchChart.svelte`

### 2A. Add imports

After `import { formatNumber } from "@investintell/ui";` add:

```ts
import {
  createTerminalLightweightChartOptions,
  terminalLWSeriesColors,
} from "@investintell/ui";
```

### 2B. Replace JS chart configs

The file has 3 chart panes sharing `baseLayout`, `baseGrid`, `baseTimeScale` objects, then individual chart creation. Replace all of them with the factory.

**BEFORE (lines 118-132):**
```ts
const baseLayout = {
  background: { color: "transparent" },
  textColor: "#5a6577",
  fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
  fontSize: 9,
};
const baseGrid = {
  vertLines: { color: "rgba(255, 255, 255, 0.03)" },
  horzLines: { color: "rgba(255, 255, 255, 0.03)" },
};
const baseTimeScale = {
  borderColor: "rgba(255, 255, 255, 0.06)",
  timeVisible: false,
  secondsVisible: false,
};
```

**AFTER:**
```ts
const sc = terminalLWSeriesColors();
```

Delete `baseLayout`, `baseGrid`, `baseTimeScale` entirely. They are replaced by factory calls per pane.

**BEFORE -- Pane 1 Drawdown (lines 135-145):**
```ts
const ddChart = lc.createChart(dd, {
  autoSize: true,
  layout: baseLayout,
  grid: baseGrid,
  rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
  timeScale: baseTimeScale,
  crosshair: {
    vertLine: { color: "rgba(239, 68, 68, 0.3)" },
    horzLine: { color: "rgba(239, 68, 68, 0.3)" },
  },
});
```

**AFTER:**
```ts
const ddOpts = createTerminalLightweightChartOptions({
  fontSize: 9,
  crosshairColor: sc.drawdown.bottomLineColor,
});
const ddChart = lc.createChart(dd, { autoSize: true, ...ddOpts });
```

**BEFORE -- Drawdown series (lines 146-158):**
```ts
const ddSeries = ddChart.addSeries(lc.BaselineSeries, {
  baseValue: { type: "price", price: 0 },
  topLineColor: "rgba(34, 197, 94, 0.0)",
  topFillColor1: "rgba(34, 197, 94, 0.00)",
  topFillColor2: "rgba(34, 197, 94, 0.00)",
  bottomLineColor: "#ef4444",
  bottomFillColor1: "rgba(239, 68, 68, 0.20)",
  bottomFillColor2: "rgba(239, 68, 68, 0.02)",
  lineWidth: 2,
  priceLineVisible: false,
  lastValueVisible: true,
  priceFormat: { type: "price", precision: 2, minMove: 0.01 },
});
```

**AFTER:**
```ts
const ddSeries = ddChart.addSeries(lc.BaselineSeries, {
  baseValue: { type: "price", price: 0 },
  ...sc.drawdown,
  lineWidth: 2,
  priceLineVisible: false,
  lastValueVisible: true,
  priceFormat: { type: "price", precision: 2, minMove: 0.01 },
});
```

**BEFORE -- Pane 2 Volatility (lines 163-173):**
```ts
const vlChart = lc.createChart(vl, {
  autoSize: true,
  layout: baseLayout,
  grid: baseGrid,
  rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.15, bottom: 0.1 } },
  timeScale: baseTimeScale,
  crosshair: {
    vertLine: { color: "rgba(139, 92, 246, 0.3)" },
    horzLine: { color: "rgba(139, 92, 246, 0.3)" },
  },
});
```

**AFTER:**
```ts
const vlOpts = createTerminalLightweightChartOptions({
  fontSize: 9,
  scaleMargins: { top: 0.15, bottom: 0.1 },
  crosshairColor: sc.volatility.color,
});
const vlChart = lc.createChart(vl, { autoSize: true, ...vlOpts });
```

**BEFORE -- Volatility series (lines 174-180):**
```ts
const vlSeries = vlChart.addSeries(lc.LineSeries, {
  color: "#8b5cf6",
  lineWidth: 2,
  priceLineVisible: false,
  lastValueVisible: true,
  priceFormat: { type: "price", precision: 2, minMove: 0.01 },
});
```

**AFTER:**
```ts
const vlSeries = vlChart.addSeries(lc.LineSeries, {
  ...sc.volatility,
  lineWidth: 2,
  priceLineVisible: false,
  lastValueVisible: true,
  priceFormat: { type: "price", precision: 2, minMove: 0.01 },
});
```

**BEFORE -- Pane 3 Regime (lines 187-200):**
```ts
const rgChart = lc.createChart(rg, {
  autoSize: true,
  layout: baseLayout,
  grid: baseGrid,
  rightPriceScale: {
    borderVisible: false,
    scaleMargins: { top: 0.08, bottom: 0.08 },
  },
  timeScale: { ...baseTimeScale, timeVisible: true },
  crosshair: {
    vertLine: { color: "rgba(90, 101, 119, 0.4)" },
    horzLine: { color: "rgba(90, 101, 119, 0.4)" },
  },
});
```

**AFTER:**
```ts
const rgOpts = createTerminalLightweightChartOptions({
  fontSize: 9,
  timeVisible: true,
});
const rgChart = lc.createChart(rg, { autoSize: true, ...rgOpts });
```

Note: The factory uses amber as default crosshair color. Regime pane previously used `#5a6577` (a grey). Amber is the terminal standard -- this is an intentional harmonization.

**BEFORE -- Regime series (lines 201-209):**
```ts
const rgSeries = rgChart.addSeries(lc.AreaSeries, {
  topColor: "rgba(202, 138, 4, 0.30)",
  bottomColor: "rgba(202, 138, 4, 0.02)",
  lineColor: "#ca8a04",
  lineWidth: 1,
  priceLineVisible: false,
  lastValueVisible: true,
  priceFormat: { type: "price", precision: 2, minMove: 0.01 },
});
```

**AFTER:**
```ts
const rgSeries = rgChart.addSeries(lc.AreaSeries, {
  ...sc.regime,
  lineWidth: 1,
  priceLineVisible: false,
  lastValueVisible: true,
  priceFormat: { type: "price", precision: 2, minMove: 0.01 },
});
```

### 2C. CSS hex migration (`<style>` block)

| Selector | Property | Old value | New value |
|---|---|---|---|
| `.rc-root` | `background` | `#05080f` | `var(--terminal-bg-panel)` |
| `.rc-header` | `border-bottom` | `1px solid rgba(255, 255, 255, 0.06)` | `var(--terminal-border-hairline)` |
| `.rc-ticker` | `font-family` | `"JetBrains Mono", "SF Mono", monospace` | `var(--terminal-font-mono)` |
| `.rc-ticker` | `font-size` | `13px` | `var(--terminal-text-14)` (closest standard size) |
| `.rc-ticker` | `color` | `#e2e8f0` | `var(--terminal-fg-primary)` |
| `.rc-label` | `font-family` | `"Urbanist", system-ui, sans-serif` | `var(--terminal-font-sans)` |
| `.rc-label` | `font-size` | `11px` | `var(--terminal-text-11)` |
| `.rc-label` | `color` | `#5a6577` | `var(--terminal-fg-tertiary)` |
| `.rc-summary` | `font-family` | `"JetBrains Mono", "SF Mono", monospace` | `var(--terminal-font-mono)` |
| `.rc-summary` | `color` | `#5a6577` | `var(--terminal-fg-tertiary)` |
| `.rc-summary strong` | `color` | `#e2e8f0` | `var(--terminal-fg-primary)` |
| `.rc-tag` | `font-family` | `"JetBrains Mono", "SF Mono", monospace` | `var(--terminal-font-mono)` |
| `.rc-tag` | `color` | `#3a4455` | `var(--terminal-fg-muted)` |
| `.rc-pane` | `border-bottom` | `1px solid rgba(255, 255, 255, 0.04)` | `var(--terminal-border-hairline)` |
| `.rc-pane-label` | `font-family` | `"JetBrains Mono", "SF Mono", monospace` | `var(--terminal-font-mono)` |
| `.rc-pane-label` | `color` | `#3a4455` | `var(--terminal-fg-muted)` |
| `.rc-placeholder-title` | `font-family` | `"JetBrains Mono", "SF Mono", monospace` | `var(--terminal-font-mono)` |
| `.rc-placeholder-title` | `color` | `#5a6577` | `var(--terminal-fg-tertiary)` |
| `.rc-placeholder-sub` | `font-family` | `"Urbanist", system-ui, sans-serif` | `var(--terminal-font-sans)` |
| `.rc-placeholder-sub` | `color` | `#3a4455` | `var(--terminal-fg-muted)` |

### 2D. Replace utility color classes

**BEFORE (lines 445-447):**
```css
.neg { color: #ef4444; }
.purple { color: #8b5cf6; }
.amber { color: #ca8a04; }
```

**AFTER:**
```css
.neg { color: var(--terminal-status-error); }
.purple { color: var(--terminal-accent-violet); }
.amber { color: var(--terminal-accent-amber); }
```

---

## TASK 3: Border Fixes

### 3A. HoldingsTable.svelte

Path: `frontends/wealth/src/lib/components/terminal/live/HoldingsTable.svelte`

Line 191 in `<style>`:

**old_string:**
```
border-bottom: 1px solid var(--terminal-fg-muted);
```

**new_string:**
```
border-bottom: var(--terminal-border-hairline);
```

This is in the `.ht-td` rule. The token `--terminal-border-hairline` is defined as `1px solid var(--terminal-fg-muted)` -- semantically identical but uses the canonical shorthand.

### 3B. DriftMonitorPanel.svelte

Path: `frontends/wealth/src/lib/components/terminal/live/DriftMonitorPanel.svelte`

Line 247 in `<style>`:

**old_string:**
```
border-bottom: 1px solid var(--terminal-fg-muted);
```

**new_string:**
```
border-bottom: var(--terminal-border-hairline);
```

This is in the `.dm-td` rule. Same rationale as above.

---

## TASK 4: LiveDot Composition in PortfolioSummary

Path: `frontends/wealth/src/lib/components/terminal/live/PortfolioSummary.svelte`

### 4A. Add import

After `import { formatAUM, formatPercent, formatDate } from "@investintell/ui";` add:

```ts
import LiveDot from "$lib/components/terminal/data/LiveDot.svelte";
```

### 4B. Replace template dot

**BEFORE (lines 63-67):**
```svelte
<span
  class="ps-dot"
  class:ps-dot-live={isLive}
  class:ps-dot-paused={isPaused}
></span>
```

**AFTER:**
```svelte
<LiveDot
  status={isLive ? "success" : isPaused ? "warn" : "muted"}
  pulse={isLive}
  label="Portfolio state: {isLive ? 'live' : isPaused ? 'paused' : state}"
/>
```

### 4C. Remove dead CSS

Delete the following CSS rules that are no longer needed (replaced by LiveDot):

```css
.ps-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--terminal-fg-muted);
}

.ps-dot-live {
  background: var(--terminal-status-success);
}

.ps-dot-paused {
  background: var(--terminal-accent-amber);
}
```

These are lines 187-200 in the `<style>` block.

---

## TASKS NOT DONE (assessed and rejected)

### PortfolioSummary -- StatSlab composition: SKIP
PortfolioSummary uses a `justify-content: space-between` key-value row layout (label left, value right). StatSlab uses a vertical `label-above-value` layout. These are structurally different patterns. Refactoring would cause a visual regression. Leave as-is.

### MacroRegimePanel -- KeyValueStrip composition: SKIP
MacroRegimePanel has a 3-column grid (key, value, change-arrow with conditional coloring). KeyValueStrip is 2-column (key, value). The change-arrow column with `changeClass()` logic does not fit KeyValueStrip's interface. Leave as-is.

### DriftMonitorPanel -- LiveDot for drift dots: PARTIAL SKIP
The `.dm-dot--watch` state uses `clip-path: inset(0 50% 0 0)` for a half-circle effect. LiveDot does not support this variant. Replacing `.dm-dot--aligned` and `.dm-dot--breach` with LiveDot while keeping watch inline adds complexity for marginal gain. Leave all three states as-is.

---

## VERIFICATION

### Step 1: Zero hex in modified files

Run from repo root:

```bash
# TerminalPriceChart -- should return ZERO matches
grep -nE '#[0-9a-fA-F]{3,8}\b' frontends/wealth/src/lib/components/portfolio/live/charts/TerminalPriceChart.svelte

# TerminalResearchChart -- should return ZERO matches
grep -nE '#[0-9a-fA-F]{3,8}\b' frontends/wealth/src/lib/components/research/terminal/TerminalResearchChart.svelte
```

Also verify no `rgba(` literals remain in JS sections of both files (CSS `color-mix` is acceptable):

```bash
grep -n 'rgba(' frontends/wealth/src/lib/components/portfolio/live/charts/TerminalPriceChart.svelte
grep -n 'rgba(' frontends/wealth/src/lib/components/research/terminal/TerminalResearchChart.svelte
```

For TerminalPriceChart: zero `rgba(` in JS, only `color-mix(` in CSS.
For TerminalResearchChart: zero `rgba(` anywhere.

### Step 2: No "Urbanist" font declaration

```bash
grep -rn 'Urbanist' frontends/wealth/src/lib/components/research/terminal/TerminalResearchChart.svelte
```

Should return ZERO matches.

### Step 3: Border token usage

```bash
grep -n '1px solid var(--terminal-fg-muted)' frontends/wealth/src/lib/components/terminal/live/HoldingsTable.svelte
grep -n '1px solid var(--terminal-fg-muted)' frontends/wealth/src/lib/components/terminal/live/DriftMonitorPanel.svelte
```

Both should return ZERO matches (replaced by `var(--terminal-border-hairline)`).

### Step 4: Type check

```bash
cd frontends/wealth && pnpm check
```

Must pass with zero errors.

### Step 5: Visual spot-check

Open the Live Workbench in browser. Confirm:
- Price chart renders with cyan baseline (not blue `#2d7ef7`)
- NAV overlay is amber
- Crosshair labels are amber (not blue)
- Active timeframe pill is cyan
- Research chart drawdown/volatility/regime panes render correctly
- Holdings table rows have hairline borders
- Drift monitor rows have hairline borders
- Portfolio summary status dot pulses green when live

---

## COMMIT

```
fix(terminal): harmonize Live Workbench hex to terminal tokens (H2)

Replace ~45 hardcoded hex values in TerminalPriceChart and
TerminalResearchChart with createTerminalLightweightChartOptions()
factory + terminalLWSeriesColors(). Migrate CSS to --terminal-*
custom properties. Remove Urbanist font declarations. Fix border
tokens in HoldingsTable and DriftMonitorPanel. Compose LiveDot
into PortfolioSummary status indicator.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```
