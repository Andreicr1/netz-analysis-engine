# Harmonization H0 — Missing Primitives + LW Factory + SSE Sanitization

**Date:** 2026-04-13
**Branch:** `feat/harmonization-h0-primitives` (off `main`)
**Scope:** Frontend new files + backend 3-file wiring + 1 new test file
**Risk:** LOW — extracting existing patterns, not inventing new ones
**Priority:** HIGH — H1-H5 sessions depend on these primitives

---

## Problem Statement

Phases 4-5 (Builder + Live Workbench) were implemented before Layer 2/3 terminal primitives were extracted. Result: each panel reimplements its own panel chrome, header, stat display, and status dots with inline CSS. The two lightweight-charts components (`TerminalPriceChart.svelte` and `TerminalResearchChart.svelte`) contain ~45 hardcoded hex values with zero terminal token consumption. Three backend serialization functions emit raw jargon without routing through `sanitize_payload()`.

---

## CONTEXT

### Directory Structure

```
frontends/wealth/src/lib/components/terminal/
  builder/         -- Builder tab panels (StressTab, RiskTab, etc.)
  charts/          -- ECharts gateway (TerminalChart.svelte) + pattern wrappers
  live/            -- Live Workbench panels (PortfolioSummary, DriftMonitorPanel, etc.)
  shell/           -- TerminalShell, TerminalTopNav, TerminalStatusBar, TerminalContextRail
  focus-mode/      -- FocusMode overlay
  layout/          -- TO BE CREATED (H0-A)
  data/            -- TO BE CREATED (H0-B)

packages/investintell-ui/src/lib/
  charts/
    terminal-options.ts     -- ECharts factory (createTerminalChartOptions)
    terminal-lw-options.ts  -- TO BE CREATED (H0-C)
    choreo.ts               -- Motion grammar (choreo slots, durations, easings)
    index.ts                -- Barrel exports
  tokens/
    terminal.css            -- ALL hex definitions (source of truth)

backend/
  app/domains/wealth/schemas/sanitized.py          -- sanitize_payload(), METRIC_LABELS, REGIME_LABELS
  vertical_engines/wealth/monitoring/drift_monitor.py   -- drift_alerts_to_json()
  vertical_engines/wealth/monitoring/alert_engine.py    -- alerts_to_json()
  vertical_engines/wealth/rebalancing/preview_service.py -- compute_rebalance_preview()
```

### Key Patterns to Follow

**Panel pattern** (from PortfolioSummary.svelte, DriftMonitorPanel.svelte):
- Root: `display:flex; flex-direction:column; background:var(--terminal-bg-panel); font-family:var(--terminal-font-mono);`
- Header: 28px height, `border-bottom:var(--terminal-border-hairline)`, label is `font-size:var(--terminal-text-10); font-weight:700; letter-spacing:var(--terminal-tracking-caps); color:var(--terminal-fg-tertiary); text-transform:uppercase;`
- Body: `flex:1; min-height:0; padding:var(--terminal-space-3);`

**StatSlab pattern** (from PortfolioSummary.svelte lines 61-113):
- `.ps-key` = 10px mono caps tertiary
- `.ps-val` = 11px mono 600 weight primary, tabular-nums

**LiveDot pattern** (from TerminalStatusBar.svelte lines 262-306):
- 6px square/circle, color maps to `--terminal-status-*` tokens
- Pulse animation via `sb-pulse` keyframes

**ECharts factory pattern** (from `terminal-options.ts`):
- `readTerminalTokens()` reads CSS custom properties, returns typed token object
- SSR-safe with hex fallback defaults matching `terminal.css`
- Factory function takes minimal input, returns full option object

**Lightweight-charts config** (from TerminalPriceChart.svelte lines 74-109 and TerminalResearchChart.svelte lines 118-132):
- Hardcoded layout: `background: {color: "transparent"}, textColor: "#5a6577", fontFamily: "'JetBrains Mono'..."`
- Hardcoded grid: `color: "rgba(255,255,255,0.04)"`
- Hardcoded crosshair: `color: "rgba(45,126,247,0.3)"`, `labelBackgroundColor: "#2d7ef7"`
- Hardcoded timeScale: `borderColor: "rgba(255,255,255,0.08)"`

---

## OBJECTIVE

### H0-A: Layer 2 Layout Primitives

Create 4 new files in `frontends/wealth/src/lib/components/terminal/layout/`:

#### 1. `Panel.svelte`

```svelte
<!--
  Panel — Layer 2 layout primitive for terminal panels.

  Slot-based composition: header, default (body), footer.
  Uses terminal tokens exclusively. Zero hex. Zero radius.
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    /** Remove body padding (for tables/charts that bleed to edges). */
    flush?: boolean;
    /** Enable vertical scrolling in the body slot. */
    scrollable?: boolean;
    /** Optional header snippet. When provided, renders 28px chrome strip. */
    header?: Snippet;
    /** Optional footer snippet. When provided, renders border-top strip. */
    footer?: Snippet;
    /** Default body content. */
    children: Snippet;
  }

  let {
    flush = false,
    scrollable = false,
    header,
    footer,
    children,
  }: Props = $props();
</script>

<div class="tp-root">
  {#if header}
    <div class="tp-header">
      {@render header()}
    </div>
  {/if}

  <div
    class="tp-body"
    class:tp-body--flush={flush}
    class:tp-body--scrollable={scrollable}
  >
    {@render children()}
  </div>

  {#if footer}
    <div class="tp-footer">
      {@render footer()}
    </div>
  {/if}
</div>

<style>
  .tp-root {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    background: var(--terminal-bg-panel);
    font-family: var(--terminal-font-mono);
    border-radius: var(--terminal-radius-none);
  }

  .tp-header {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    height: 28px;
    padding: 0 var(--terminal-space-3);
    border-bottom: var(--terminal-border-hairline);
  }

  .tp-body {
    flex: 1;
    min-height: 0;
    padding: var(--terminal-space-3);
  }

  .tp-body--flush {
    padding: 0;
  }

  .tp-body--scrollable {
    overflow-y: auto;
  }

  .tp-footer {
    flex-shrink: 0;
    padding: var(--terminal-space-2) var(--terminal-space-3);
    border-top: var(--terminal-border-hairline);
  }
</style>
```

#### 2. `PanelHeader.svelte`

```svelte
<!--
  PanelHeader — 28px terminal panel header with monospace uppercase label.

  Optional right-slot for action buttons. Extracted from the repeated
  pattern in PortfolioSummary, DriftMonitorPanel, and Builder tabs.
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    label: string;
    /** Optional right-aligned actions slot. */
    actions?: Snippet;
  }

  let { label, actions }: Props = $props();
</script>

<div class="ph-root">
  <span class="ph-label">{label}</span>
  {#if actions}
    <div class="ph-actions">
      {@render actions()}
    </div>
  {/if}
</div>

<style>
  .ph-root {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    height: 28px;
    font-family: var(--terminal-font-mono);
  }

  .ph-label {
    font-size: var(--terminal-text-10);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    color: var(--terminal-fg-tertiary);
    text-transform: uppercase;
  }

  .ph-actions {
    display: flex;
    align-items: center;
    gap: var(--terminal-space-2);
  }
</style>
```

#### 3. `SplitPane.svelte`

```svelte
<!--
  SplitPane — CSS grid wrapper with named template columns.

  Used for Builder 2-column (40/60) and Live 3-column layouts.
  The `columns` prop is a raw CSS grid-template-columns string.
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    /** CSS grid-template-columns value (e.g. "2fr 3fr", "1fr 1fr 1fr"). */
    columns: string;
    /** Gap between grid children. Default: 1px (hairline). */
    gap?: string;
    children: Snippet;
  }

  let {
    columns,
    gap = "1px",
    children,
  }: Props = $props();
</script>

<div
  class="sp-root"
  style:grid-template-columns={columns}
  style:gap={gap}
>
  {@render children()}
</div>

<style>
  .sp-root {
    display: grid;
    width: 100%;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    background: var(--terminal-bg-void);
  }
</style>
```

#### 4. `StackedPanels.svelte`

```svelte
<!--
  StackedPanels — vertical stack with hairline dividers between children.

  Used for Live bottom row (PortfolioSummary + DriftMonitorPanel stacked).
  Children are flexed vertically with equal weight by default.
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    children: Snippet;
  }

  let { children }: Props = $props();
</script>

<div class="sk-root">
  {@render children()}
</div>

<style>
  .sk-root {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    background: var(--terminal-bg-void);
  }

  .sk-root > :global(*) {
    flex: 1;
    min-height: 0;
  }

  .sk-root > :global(* + *) {
    border-top: var(--terminal-border-hairline);
  }
</style>
```

---

### H0-B: Layer 3 Data Primitives

Create 3 new files in `frontends/wealth/src/lib/components/terminal/data/`:

#### 1. `StatSlab.svelte`

```svelte
<!--
  StatSlab — label + value + optional delta indicator.

  Extracted from PortfolioSummary KPI rows and BacktestTab metrics.
  Monospace typography, tabular-nums, terminal tokens only.
-->
<script lang="ts">
  interface Props {
    label: string;
    value: string;
    /** Optional delta string (e.g. "+2.4%"). */
    delta?: string | null;
    /** Color for the delta text. Maps to terminal status/accent tokens. */
    deltaColor?: "success" | "warn" | "error" | "muted" | "cyan" | "amber";
  }

  let {
    label,
    value,
    delta = null,
    deltaColor = "muted",
  }: Props = $props();

  const colorMap: Record<string, string> = {
    success: "var(--terminal-status-success)",
    warn: "var(--terminal-status-warn)",
    error: "var(--terminal-status-error)",
    muted: "var(--terminal-fg-muted)",
    cyan: "var(--terminal-accent-cyan)",
    amber: "var(--terminal-accent-amber)",
  };

  const resolvedColor = $derived(colorMap[deltaColor] ?? colorMap.muted);
</script>

<div class="ss-root">
  <span class="ss-label">{label}</span>
  <div class="ss-value-row">
    <span class="ss-value">{value}</span>
    {#if delta}
      <span class="ss-delta" style:color={resolvedColor}>{delta}</span>
    {/if}
  </div>
</div>

<style>
  .ss-root {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-family: var(--terminal-font-mono);
  }

  .ss-label {
    font-size: var(--terminal-text-10);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-tertiary);
  }

  .ss-value-row {
    display: flex;
    align-items: baseline;
    gap: var(--terminal-space-2);
  }

  .ss-value {
    font-size: var(--terminal-text-14);
    font-weight: 600;
    color: var(--terminal-fg-primary);
    font-variant-numeric: tabular-nums;
  }

  .ss-delta {
    font-size: var(--terminal-text-11);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
</style>
```

#### 2. `KeyValueStrip.svelte`

```svelte
<!--
  KeyValueStrip — horizontal strip of key-value pairs.

  Extracted from MacroRegimePanel rows and AdvisorTab metrics.
  Consistent spacing, monospace, tabular-nums.
-->
<script lang="ts">
  interface KVItem {
    key: string;
    value: string;
    /** Optional color override for the value text. */
    valueColor?: string;
  }

  interface Props {
    items: KVItem[];
    /** Direction of the strip. Default: horizontal row. */
    direction?: "row" | "column";
  }

  let {
    items,
    direction = "row",
  }: Props = $props();
</script>

<div class="kv-root" class:kv-root--column={direction === "column"}>
  {#each items as item (item.key)}
    <div class="kv-pair">
      <span class="kv-key">{item.key}</span>
      <span
        class="kv-value"
        style:color={item.valueColor ?? "var(--terminal-fg-primary)"}
      >
        {item.value}
      </span>
    </div>
  {/each}
</div>

<style>
  .kv-root {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--terminal-space-3);
    font-family: var(--terminal-font-mono);
  }

  .kv-root--column {
    flex-direction: column;
    align-items: stretch;
  }

  .kv-pair {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--terminal-space-2);
  }

  .kv-key {
    font-size: var(--terminal-text-10);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-tertiary);
    white-space: nowrap;
  }

  .kv-value {
    font-size: var(--terminal-text-11);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
</style>
```

#### 3. `LiveDot.svelte`

```svelte
<!--
  LiveDot — 6px status indicator dot.

  Extracted from TerminalStatusBar inline dots and DriftMonitorPanel
  drift state indicators. Four status states mapping to terminal tokens.
  Optional pulse animation for live/streaming contexts.
-->
<script lang="ts">
  type DotStatus = "success" | "warn" | "error" | "muted";

  interface Props {
    status?: DotStatus;
    /** Enable pulse animation (for live streaming indicators). */
    pulse?: boolean;
    /** Optional accessible label. */
    label?: string;
  }

  let {
    status = "muted",
    pulse = false,
    label,
  }: Props = $props();

  const colorMap: Record<DotStatus, string> = {
    success: "var(--terminal-status-success)",
    warn: "var(--terminal-status-warn)",
    error: "var(--terminal-status-error)",
    muted: "var(--terminal-fg-muted)",
  };

  const resolvedColor = $derived(colorMap[status]);
</script>

<span
  class="ld-dot"
  class:ld-dot--pulse={pulse}
  style:background={resolvedColor}
  style:box-shadow={status !== "muted" ? `0 0 8px ${resolvedColor}` : "none"}
  role={label ? "status" : undefined}
  aria-label={label}
></span>

<style>
  .ld-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    flex-shrink: 0;
    vertical-align: middle;
  }

  .ld-dot--pulse {
    animation: ld-pulse 1.8s ease-in-out infinite;
  }

  @keyframes ld-pulse {
    0%, 100% { opacity: 0.45; }
    50% { opacity: 1; }
  }

  @media (prefers-reduced-motion: reduce) {
    .ld-dot--pulse {
      animation: none;
    }
  }
</style>
```

---

### H0-C: Lightweight-Charts Factory

Create `packages/investintell-ui/src/lib/charts/terminal-lw-options.ts`:

```typescript
/**
 * Netz Wealth OS -- createTerminalLightweightChartOptions()
 * =========================================================
 *
 * Mirrors `createTerminalChartOptions()` but for lightweight-charts v5
 * API. Reads CSS custom properties from `tokens/terminal.css` via
 * `readTerminalTokens()` (already exists in terminal-options.ts).
 *
 * Replaces ~45 hardcoded hex values across TerminalPriceChart and
 * TerminalResearchChart with a single factory call.
 *
 * Contract:
 *   - ZERO hex literals (only SSR fallbacks in readTerminalTokens).
 *   - Returns DeepPartial<ChartOptions> from lightweight-charts.
 *   - Callers spread the result into createChart() options.
 */

import { readTerminalTokens, type TerminalChartTokens } from "./terminal-options.js";

/**
 * Structural subset of lightweight-charts ChartOptions.
 *
 * Defined inline to avoid a dependency on `lightweight-charts` from
 * `@investintell/ui` — that package lives only in `frontends/wealth/`.
 * TypeScript structural typing ensures callers in the wealth frontend
 * can spread this directly into `createChart()` without casts.
 */
export interface TerminalLWChartOptions {
  layout?: {
    background?: { color?: string };
    textColor?: string;
    fontFamily?: string;
    fontSize?: number;
  };
  grid?: {
    vertLines?: { color?: string };
    horzLines?: { color?: string };
  };
  crosshair?: {
    vertLine?: { color?: string; labelBackgroundColor?: string };
    horzLine?: { color?: string; labelBackgroundColor?: string };
  };
  rightPriceScale?: {
    borderVisible?: boolean;
    scaleMargins?: { top: number; bottom: number };
    mode?: number;
  };
  timeScale?: {
    borderColor?: string;
    timeVisible?: boolean;
    secondsVisible?: boolean;
    rightOffset?: number;
  };
  handleScroll?: boolean;
  handleScale?: boolean;
}

export interface TerminalLWChartOptionsInput {
  /**
   * Whether to show time labels on the time scale.
   * Default: false (most panes suppress time labels; only bottom pane shows).
   */
  timeVisible?: boolean;
  /**
   * Whether to show seconds on the time scale. Default: false.
   */
  secondsVisible?: boolean;
  /**
   * Right offset for the time scale (bar count). Default: 5.
   */
  rightOffset?: number;
  /**
   * Price scale mode. Pass lc.PriceScaleMode.Percentage for overlay charts.
   * Default: undefined (normal mode).
   */
  priceScaleMode?: number;
  /**
   * Scale margins for the right price scale.
   * Default: { top: 0.08, bottom: 0.08 }.
   */
  scaleMargins?: { top: number; bottom: number };
  /**
   * Crosshair color. Defaults to terminal accent amber.
   * Pass a specific token color for per-pane crosshair theming.
   */
  crosshairColor?: string;
  /**
   * Font size override. Default: 10 (matches terminal-text-10).
   */
  fontSize?: number;
}

/**
 * Build lightweight-charts ChartOptions from terminal tokens.
 *
 * Usage:
 * ```ts
 * const lc = await import("lightweight-charts");
 * const opts = createTerminalLightweightChartOptions({ timeVisible: true });
 * const chart = lc.createChart(container, { autoSize: true, ...opts });
 * ```
 */
export function createTerminalLightweightChartOptions(
  input: TerminalLWChartOptionsInput = {},
): TerminalLWChartOptions {
  const t: TerminalChartTokens = readTerminalTokens();

  const crosshairColor = input.crosshairColor ?? t.accentAmber;
  const crosshairAlpha = hexToRgba(crosshairColor, 0.3);
  const gridColor = hexToRgba(t.fgMuted, 0.15);
  const borderColor = hexToRgba(t.fgMuted, 0.3);

  return {
    layout: {
      background: { color: "transparent" },
      textColor: t.fgTertiary,
      fontFamily: t.fontMono,
      fontSize: input.fontSize ?? t.text10,
    },
    grid: {
      vertLines: { color: gridColor },
      horzLines: { color: gridColor },
    },
    crosshair: {
      vertLine: {
        color: crosshairAlpha,
        labelBackgroundColor: crosshairColor,
      },
      horzLine: {
        color: crosshairAlpha,
        labelBackgroundColor: crosshairColor,
      },
    },
    rightPriceScale: {
      borderVisible: false,
      scaleMargins: input.scaleMargins ?? { top: 0.08, bottom: 0.08 },
      ...(input.priceScaleMode !== undefined ? { mode: input.priceScaleMode } : {}),
    },
    timeScale: {
      borderColor,
      timeVisible: input.timeVisible ?? false,
      secondsVisible: input.secondsVisible ?? false,
      rightOffset: input.rightOffset ?? 5,
    },
    handleScroll: true,
    handleScale: true,
  };
}

/**
 * Terminal-themed series defaults for lightweight-charts.
 *
 * Callers use these instead of hardcoded hex in addSeries() options.
 */
export function terminalLWSeriesColors(tokens?: TerminalChartTokens) {
  const t = tokens ?? readTerminalTokens();
  return {
    /** Baseline series (instrument price): cyan primary. */
    baseline: {
      topLineColor: t.accentCyan,
      topFillColor1: hexToRgba(t.accentCyan, 0.10),
      topFillColor2: hexToRgba(t.accentCyan, 0.01),
      bottomLineColor: t.statusError,
      bottomFillColor1: hexToRgba(t.statusError, 0.01),
      bottomFillColor2: hexToRgba(t.statusError, 0.06),
      priceLineColor: hexToRgba(t.accentCyan, 0.4),
    },
    /** NAV overlay line: amber/gold. */
    navOverlay: {
      color: t.accentAmber,
    },
    /** Drawdown baseline: error red. */
    drawdown: {
      topLineColor: "rgba(0, 0, 0, 0)",
      topFillColor1: "rgba(0, 0, 0, 0)",
      topFillColor2: "rgba(0, 0, 0, 0)",
      bottomLineColor: t.statusError,
      bottomFillColor1: hexToRgba(t.statusError, 0.20),
      bottomFillColor2: hexToRgba(t.statusError, 0.02),
    },
    /** Volatility line: violet. */
    volatility: {
      color: t.accentViolet,
    },
    /** Regime probability area: amber. */
    regime: {
      topColor: hexToRgba(t.accentAmber, 0.30),
      bottomColor: hexToRgba(t.accentAmber, 0.02),
      lineColor: t.accentAmber,
    },
  };
}

/**
 * Convert a hex color to rgba string. Handles 3, 6, and 8-char hex.
 * Falls back to the raw color string if parsing fails.
 */
function hexToRgba(hex: string, alpha: number): string {
  const cleaned = hex.replace("#", "");
  let r: number, g: number, b: number;

  if (cleaned.length === 3) {
    r = parseInt(cleaned[0]! + cleaned[0], 16);
    g = parseInt(cleaned[1]! + cleaned[1], 16);
    b = parseInt(cleaned[2]! + cleaned[2], 16);
  } else if (cleaned.length >= 6) {
    r = parseInt(cleaned.substring(0, 2), 16);
    g = parseInt(cleaned.substring(2, 4), 16);
    b = parseInt(cleaned.substring(4, 6), 16);
  } else {
    return hex; // fallback
  }

  if (isNaN(r) || isNaN(g) || isNaN(b)) return hex;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
```

**Wire into barrel export.** Add to `packages/investintell-ui/src/lib/charts/index.ts` at the bottom:

```typescript
// Terminal lightweight-charts factory: single source of aesthetic
// truth for every lightweight-charts instance inside (terminal)/.
export {
  createTerminalLightweightChartOptions,
  terminalLWSeriesColors,
} from "./terminal-lw-options.js";
export type {
  TerminalLWChartOptionsInput,
  TerminalLWChartOptions,
} from "./terminal-lw-options.js";
```

**Wire into main barrel export.** Add to `packages/investintell-ui/src/lib/index.ts` in the "Terminal primitives" section:

```typescript
export {
  createTerminalLightweightChartOptions,
  terminalLWSeriesColors,
} from "./charts/index.js";
export type {
  TerminalLWChartOptionsInput,
  TerminalLWChartOptions,
} from "./charts/index.js";
```

---

### H0-D: SSE Sanitization Wiring

Three backend serialization functions emit raw payloads that may contain jargon strings (e.g. "DTW drift score" in the `detail` field). Wrap the output of each through `sanitize_payload()` at the serialization boundary.

#### 1. `backend/vertical_engines/wealth/monitoring/drift_monitor.py`

At the top of the file (after existing imports on line 16), add:

```python
from app.domains.wealth.schemas.sanitized import sanitize_payload
```

Modify `drift_alerts_to_json()` (line 199) — wrap the return value:

**Current** (line 199-213):
```python
def drift_alerts_to_json(result: DriftScanResult) -> list[dict[str, Any]]:
    """Serialize DriftScanResult to JSON-compatible list."""
    return [
        {
            "instrument_id": a.instrument_id,
            ...
        }
        for a in result.alerts
    ]
```

**After:**
```python
def drift_alerts_to_json(result: DriftScanResult) -> list[dict[str, Any]]:
    """Serialize DriftScanResult to JSON-compatible list.

    Payload is walked through sanitize_payload() to translate any
    jargon in free-form detail strings before crossing the wire.
    """
    raw = [
        {
            "instrument_id": a.instrument_id,
            "fund_name": a.fund_name,
            "drift_score": a.drift_score,
            "drift_type": a.drift_type,
            "affected_portfolios": a.affected_portfolios,
            "detail": a.detail,
            "scanned_at": result.scanned_at.isoformat(),
            "organization_id": result.organization_id,
        }
        for a in result.alerts
    ]
    return [sanitize_payload(item) for item in raw]
```

#### 2. `backend/vertical_engines/wealth/monitoring/alert_engine.py`

At the top of the file (after existing imports on line 16), add:

```python
from app.domains.wealth.schemas.sanitized import sanitize_payload
```

Modify `alerts_to_json()` (line 200) — wrap the return value:

**Current** (line 200-214):
```python
def alerts_to_json(batch: AlertBatch) -> list[dict[str, Any]]:
    """Serialize AlertBatch to JSON-compatible list for Redis pub/sub."""
    return [
        {
            "alert_type": a.alert_type,
            ...
        }
        for a in batch.alerts
    ]
```

**After:**
```python
def alerts_to_json(batch: AlertBatch) -> list[dict[str, Any]]:
    """Serialize AlertBatch to JSON-compatible list for Redis pub/sub.

    Payload is walked through sanitize_payload() to translate any
    jargon in free-form detail/title strings before crossing the wire.
    """
    raw = [
        {
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "detail": a.detail,
            "entity_id": a.entity_id,
            "entity_type": a.entity_type,
            "scanned_at": batch.scanned_at.isoformat(),
            "organization_id": batch.organization_id,
        }
        for a in batch.alerts
    ]
    return [sanitize_payload(item) for item in raw]
```

#### 3. `backend/vertical_engines/wealth/rebalancing/preview_service.py`

At the top of the file (after existing imports on line 15), add:

```python
from app.domains.wealth.schemas.sanitized import sanitize_payload
```

Modify `compute_rebalance_preview()` — wrap the return dict (line 205-215):

**Current** (line 205-215):
```python
    return {
        "portfolio_id": str(portfolio_id),
        ...
        "weight_comparison": weight_comparison,
    }
```

**After:**
```python
    result = {
        "portfolio_id": str(portfolio_id),
        "portfolio_name": portfolio_name,
        "profile": profile,
        "total_aum": round(total_aum, 2),
        "cash_available": round(cash_available, 2),
        "total_trades": total_trades,
        "estimated_turnover_pct": round(turnover, 6),
        "trades": trades,
        "weight_comparison": weight_comparison,
    }
    return sanitize_payload(result)
```

Also wrap `_empty_response()` (line 273-291) the same way:

**After:**
```python
def _empty_response(
    portfolio_id: uuid.UUID,
    portfolio_name: str,
    profile: str,
    total_aum: float,
    cash_available: float,
) -> dict[str, Any]:
    """Return empty response when AUM is zero or negative."""
    return sanitize_payload({
        "portfolio_id": str(portfolio_id),
        "portfolio_name": portfolio_name,
        "profile": profile,
        "total_aum": total_aum,
        "cash_available": cash_available,
        "total_trades": 0,
        "estimated_turnover_pct": 0.0,
        "trades": [],
        "weight_comparison": [],
    })
```

---

### H0-E: Tests for SSE Sanitization

Create `backend/tests/wealth/test_sse_sanitization_wiring.py`:

```python
"""Tests verifying sanitize_payload() is wired into SSE serialization functions.

Each emitter's output is checked for zero banned substrings.
"""

from __future__ import annotations

from datetime import UTC, datetime

from vertical_engines.wealth.monitoring.alert_engine import (
    Alert,
    AlertBatch,
    alerts_to_json,
)
from vertical_engines.wealth.monitoring.drift_monitor import (
    DriftAlert,
    DriftScanResult,
    drift_alerts_to_json,
)
from vertical_engines.wealth.rebalancing.preview_service import (
    compute_rebalance_preview,
)

import uuid

# Substrings that must never appear in user-facing output.
# sanitize_payload() translates REGIME_LABELS values.
BANNED_REGIME_STRINGS = {"RISK_ON", "RISK_OFF", "CRISIS"}


def test_drift_alerts_to_json_sanitizes_regime_values() -> None:
    """drift_alerts_to_json wraps through sanitize_payload."""
    result = DriftScanResult(
        alerts=[
            DriftAlert(
                instrument_id="abc-123",
                fund_name="Test Fund",
                drift_score=0.25,
                drift_type="style_drift",
                affected_portfolios=["Portfolio A"],
                detail="DTW drift score 0.250 exceeds threshold 0.150.",
            ),
        ],
        scanned_at=datetime.now(UTC),
        organization_id="org-1",
    )
    serialized = drift_alerts_to_json(result)
    assert len(serialized) == 1
    # The detail field passes through (no regime enum in it),
    # but verify the function runs without error.
    assert "instrument_id" in serialized[0]


def test_alerts_to_json_sanitizes_regime_values() -> None:
    """alerts_to_json wraps through sanitize_payload."""
    batch = AlertBatch(
        alerts=[
            Alert(
                alert_type="dd_expiry",
                severity="warning",
                title="No DD Report for Test Fund",
                detail="Fund Test Fund has no DD Report on file.",
                entity_id="fund-1",
                entity_type="fund",
            ),
        ],
        scanned_at=datetime.now(UTC),
        organization_id="org-1",
    )
    serialized = alerts_to_json(batch)
    assert len(serialized) == 1
    assert "alert_type" in serialized[0]


def test_rebalance_preview_sanitizes_payload() -> None:
    """compute_rebalance_preview wraps through sanitize_payload."""
    result = compute_rebalance_preview(
        portfolio_id=uuid.uuid4(),
        portfolio_name="Test Portfolio",
        profile="balanced",
        fund_selection_schema={
            "funds": [
                {
                    "instrument_id": str(uuid.uuid4()),
                    "fund_name": "Fund A",
                    "block_id": "equity",
                    "weight": 0.6,
                },
                {
                    "instrument_id": str(uuid.uuid4()),
                    "fund_name": "Fund B",
                    "block_id": "fixed_income",
                    "weight": 0.3,
                },
            ],
        },
        current_holdings=[],
        cash_available=1_000_000.0,
    )
    assert "portfolio_id" in result
    assert "trades" in result
    # Verify sanitize_payload was applied (no regime strings in output)
    payload_str = str(result)
    for banned in BANNED_REGIME_STRINGS:
        assert banned not in payload_str, f"Found banned substring '{banned}' in output"


def test_drift_alerts_detail_with_regime_string_is_sanitized() -> None:
    """Proves sanitize_payload actually translates regime strings in detail."""
    result = DriftScanResult(
        alerts=[
            DriftAlert(
                instrument_id="x",
                fund_name="Test Fund",
                drift_score=0.2,
                drift_type="style_drift",
                affected_portfolios=[],
                detail="Regime is RISK_ON currently",
            ),
        ],
        scanned_at=datetime.now(UTC),
        organization_id="org-1",
    )
    serialized = drift_alerts_to_json(result)
    assert "RISK_ON" not in serialized[0]["detail"]
    assert "Expansion" in serialized[0]["detail"]


def test_alerts_title_with_regime_string_is_sanitized() -> None:
    """Proves sanitize_payload translates regime strings in title/detail."""
    batch = AlertBatch(
        alerts=[
            Alert(
                alert_type="regime_change",
                severity="info",
                title="Market shifted to CRISIS",
                detail="Global regime is now CRISIS, review allocations.",
                entity_id=None,
                entity_type=None,
            ),
        ],
        scanned_at=datetime.now(UTC),
        organization_id="org-1",
    )
    serialized = alerts_to_json(batch)
    assert "CRISIS" not in serialized[0]["title"]
    assert "Stress" in serialized[0]["title"]
    assert "CRISIS" not in serialized[0]["detail"]
    assert "Stress" in serialized[0]["detail"]


def test_rebalance_empty_response_sanitizes_payload() -> None:
    """_empty_response also routes through sanitize_payload."""
    result = compute_rebalance_preview(
        portfolio_id=uuid.uuid4(),
        portfolio_name="Empty Portfolio",
        profile="conservative",
        fund_selection_schema={"funds": []},
        current_holdings=[],
        cash_available=0.0,
        total_aum_override=0.0,
    )
    assert result["total_trades"] == 0
    assert result["trades"] == []
```

---

## CONSTRAINTS

1. **ZERO hex literals** in any new `.svelte` file. All colors via `--terminal-*` CSS custom properties.
2. **ZERO hex literals** in `terminal-lw-options.ts` except inside `readTerminalTokens()` SSR fallbacks (which already exist in `terminal-options.ts` and are shared).
3. **ZERO `border-radius`** except `var(--terminal-radius-none)` (which is `0`).
4. **Font:** Always `var(--terminal-font-mono)`. Never inline `"JetBrains Mono"` or `"Urbanist"`.
5. **Imports:** `sanitize_payload` is imported from `app.domains.wealth.schemas.sanitized`, NOT from any other path.
6. **Do NOT modify** any existing component in this session. No refactoring of existing panels to use the new primitives yet -- that is H2/H3 scope.
7. **Do NOT install** any new npm or Python packages.
8. **Svelte 5 only:** Use `$props()`, `$derived()`, `$state()`, `$effect()`. Use `Snippet` type for slots, `{@render}` for rendering snippets.
9. **`lazy="raise"`** rule does not apply here (no ORM work), but `async def` + `AsyncSession` rule does not apply either (these backend changes are in sync services).

---

## DELIVERABLES

| File | Action |
|---|---|
| `frontends/wealth/src/lib/components/terminal/layout/Panel.svelte` | CREATE |
| `frontends/wealth/src/lib/components/terminal/layout/PanelHeader.svelte` | CREATE |
| `frontends/wealth/src/lib/components/terminal/layout/SplitPane.svelte` | CREATE |
| `frontends/wealth/src/lib/components/terminal/layout/StackedPanels.svelte` | CREATE |
| `frontends/wealth/src/lib/components/terminal/data/StatSlab.svelte` | CREATE |
| `frontends/wealth/src/lib/components/terminal/data/KeyValueStrip.svelte` | CREATE |
| `frontends/wealth/src/lib/components/terminal/data/LiveDot.svelte` | CREATE |
| `packages/investintell-ui/src/lib/charts/terminal-lw-options.ts` | CREATE |
| `packages/investintell-ui/src/lib/charts/index.ts` | MODIFY (add 3 exports at bottom) |
| `packages/investintell-ui/src/lib/index.ts` | MODIFY (add 3 exports in Terminal primitives section) |
| `backend/vertical_engines/wealth/monitoring/drift_monitor.py` | MODIFY (import + wrap) |
| `backend/vertical_engines/wealth/monitoring/alert_engine.py` | MODIFY (import + wrap) |
| `backend/vertical_engines/wealth/rebalancing/preview_service.py` | MODIFY (import + wrap x2) |
| `backend/tests/wealth/test_sse_sanitization_wiring.py` | CREATE |

---

## VERIFICATION

```bash
# 1. Frontend type check (catches any Svelte 5 or TS errors in new components)
cd frontends/wealth && pnpm check

# 2. Package type check (catches TS errors in terminal-lw-options.ts)
cd packages/investintell-ui && pnpm check

# 3. Backend type check
make typecheck

# 4. Run new tests
make test ARGS="-k test_sse_sanitization_wiring -v"

# 5. Run existing sanitization tests (regression)
make test ARGS="-k test_sanitized -v"

# 6. Full gate
make check

# 7. Grep: zero hex in new Svelte files
grep -rn "#[0-9a-fA-F]\{3,8\}" \
  frontends/wealth/src/lib/components/terminal/layout/ \
  frontends/wealth/src/lib/components/terminal/data/ \
  --include="*.svelte"
# Expected: zero results

# 8. Grep: zero hex in LW factory (except hexToRgba implementation)
grep -n "#[0-9a-fA-F]\{3,8\}" packages/investintell-ui/src/lib/charts/terminal-lw-options.ts
# Expected: zero results (hexToRgba only processes hex, does not contain hex literals)

# 9. Verify sanitize_payload imports in backend
grep -rn "from app.domains.wealth.schemas.sanitized import" \
  backend/vertical_engines/wealth/monitoring/drift_monitor.py \
  backend/vertical_engines/wealth/monitoring/alert_engine.py \
  backend/vertical_engines/wealth/rebalancing/preview_service.py
# Expected: 3 results, one per file
```

---

## ANTI-PATTERNS

1. **Do NOT use hardcoded hex values** in any new file. The terminal.css token file is the single source of truth.
2. **Do NOT import `echarts`** in any new file. The LW factory is for lightweight-charts only.
3. **Do NOT create index/barrel files** for the layout/ and data/ directories. Svelte components are imported directly by path.
4. **Do NOT use `Urbanist` font** anywhere. Terminal is monospace only.
5. **Do NOT add `border-radius`** to any element. Brutalist aesthetic = zero radius.
6. **Do NOT use `class:` directives for color mapping** when `style:` with CSS custom properties is cleaner. The LiveDot and StatSlab use `style:color` intentionally.
7. **Do NOT modify existing components** to consume the new primitives. That is H2-H5 scope.
8. **Do NOT add `sanitize_payload` to the worker entry points** (e.g. `drift_check` worker in `workers/`). The sanitization goes at the serialization boundary (`*_to_json()` / `compute_*()` return), not at the Redis publish point.

---

## Commit Message

```
feat(terminal): H0 primitives — Layer 2/3 components + LW factory + SSE sanitization

7 new terminal primitives (Panel, PanelHeader, SplitPane, StackedPanels,
StatSlab, KeyValueStrip, LiveDot) extracted from Builder/Live patterns.

createTerminalLightweightChartOptions() factory mirrors the ECharts
factory for lightweight-charts v5, reading terminal.css tokens at
runtime. Replaces ~45 hardcoded hex values in follow-up H2 session.

Wired sanitize_payload() into drift_monitor, alert_engine, and
preview_service serialization boundaries. 4 new tests verify wiring.
```
