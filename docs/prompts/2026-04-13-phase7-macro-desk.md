# Phase 7 — Macro Desk + Allocation Editor

**Date:** 2026-04-13
**Branch:** `feat/terminal-macro-desk`
**Sessions:** 3 (Session A: Macro Desk, Session B: Allocation Editor, Session C: Cross-wiring + Polish)
**Depends on:** Phase 6 merged (DD tab active, TopNav updated)

---

## Strategic Rationale

Macro is the top of the investment funnel. The allocation regime drives everything downstream: which asset classes get screened, how weights are suggested in the Builder, what drift thresholds trigger alerts. Currently, `(app)/macro` exists with a MacroWorkbenchShell using old design tokens (hex colors, Urbanist font, non-terminal layout). Phase 7 builds the terminal-native macro desk and allocation editor, then cross-wires them to the Builder.

The backend is ~85% ready. All macro data endpoints exist. Allocation CRUD exists. The only gap is that the macro desk needs to aggregate multiple endpoints into a cohesive dashboard — no new backend work, just frontend composition.

---

## Backend Endpoints Available

### Macro
| Endpoint | Returns |
|---|---|
| `GET /macro/scores` | Regional scores (US/EU/JP/EM) with dimension breakdown |
| `GET /macro/snapshot` | Latest macro snapshot with freshness metadata |
| `GET /macro/regime` | Hierarchical regime classification (global + regional) |
| `GET /macro/reviews` | List macro committee reviews |
| `POST /macro/reviews/generate` | Trigger async macro review generation (202) |
| `PATCH /macro/reviews/{id}/approve` | Approve review |
| `PATCH /macro/reviews/{id}/reject` | Reject review |
| `GET /macro/fred?series_ids=...&days=N` | FRED time series data |
| `GET /macro/bis?indicator=...&region=...` | BIS statistics |
| `GET /macro/imf?indicator=...&region=...` | IMF WEO forecasts |
| `GET /macro/treasury?series=...&days=N` | US Treasury data |
| `GET /macro/ofr?metric=...&days=N` | OFR hedge fund data |

### Allocation
| Endpoint | Returns |
|---|---|
| `GET /allocation/{profile}/strategic` | IC-approved strategic weights |
| `PUT /allocation/{profile}/strategic` | Update strategic weights |
| `GET /allocation/{profile}/tactical` | Tactical overweight positions |
| `PUT /allocation/{profile}/tactical` | Update tactical positions |
| `GET /allocation/{profile}/effective` | Computed effective allocation |
| `POST /allocation/{profile}/simulate` | CVaR impact simulation |
| `GET /allocation/regime` | Global regime state |
| `GET /allocation/regime-overlay` | S&P500 NAV + regime markArea bands |
| `GET /allocation/{profile}/regime-bands` | Smoothed regime centers + optimizer bands |
| `GET /allocation/{profile}/taa-history` | Tactical allocation history |
| `GET /allocation/{profile}/effective-with-regime` | Effective weights with regime context |

---

## Session A — Macro Desk

### CONTEXT

The terminal layout uses `TerminalShell` + `LayoutCage` (calc(100vh-88px)). TopNav has MACRO and ALLOC tabs currently pending (positioned first and second). The `createTerminalStream` runtime is in `$lib/components/terminal/runtime/stream.ts`. `TerminalChart` is the chart wrapper in `$lib/components/terminal/charts/TerminalChart.svelte`. The `createTerminalChartOptions` factory is in `packages/ui/src/lib/charts/terminal-options.ts`. Existing macro components in `$lib/components/macro/` (MacroWorkbenchShell, MacroSignalsGrid, MacroStressChart, MacroYieldCurve, etc.) use old design tokens and are NOT reusable — rebuild from scratch with terminal primitives.

### OBJECTIVE

1. Create `(terminal)/macro/+page.svelte` — 12-column grid macro dashboard.
2. Activate MACRO tab in TopNav.
3. Build 4 regional regime tiles, sparkline wall, and committee review feed.

### CONSTRAINTS

Same terminal design rules as Phase 6:
- All colors via `--terminal-*` CSS custom properties. No hex.
- Font: `var(--terminal-font-mono)`. No Urbanist.
- Border radius: `var(--terminal-radius-none)` (0).
- Layer 2/3 primitives: Panel, PanelHeader, StatSlab, KeyValueStrip.
- ECharts via `TerminalChart` wrapper only. Never direct `svelte-echarts` import.
- `createTerminalChartOptions()` for all chart option objects.
- Formatters from `@netz/ui` exclusively.
- No localStorage. In-memory state + polling.
- Svelte 5 runes.
- Smart backend, dumb frontend:
  - Regime labels: "Normal" / "Risk On" / "Risk Off" / "Crisis" (not REGIME_NORMAL, REGIME_RISK_OFF etc.)
  - Scores shown as "US: 72/100" not "us_composite_score: 0.72"
  - Dimensions shown as "Growth", "Inflation", "Employment", "Financial Conditions" (not dimension_X)
- LayoutCage pattern for full-height.

### DELIVERABLES

#### 1. `frontends/wealth/src/routes/(terminal)/macro/+page.svelte`

12-column CSS grid layout:

```
+----------+----------+----------+----------+
| US TILE  | EU TILE  | JP TILE  | EM TILE  |
| score    | score    | score    | score    |
| regime   | regime   | regime   | regime   |
| sparkl.  | sparkl.  | sparkl.  | sparkl.  |
+----------+----------+----------+----------+------+
| INDICATOR SPARKLINE WALL                   | FEED |
| 6-8 macro indicators, mini sparklines     |      |
| (GDP, CPI, Unemployment, Fed Funds,       | comm |
|  10Y yield, credit spread, VIX, DXY)      | revs |
+--------------------------------------------+------+
```

Top row: 4 equal columns, each a regional regime tile.
Bottom left (9 cols): sparkline wall with macro indicators.
Bottom right (3 cols): committee review feed.

**Data fetching:** Client-side in `$effect` on mount.
- `GET /api/wealth/macro/scores` — for regional scores + dimensions.
- `GET /api/wealth/macro/regime` — for regime classification.
- `GET /api/wealth/macro/reviews?limit=10` — for committee feed.
- Poll scores + regime every 5 minutes (macro data is daily, no need for high frequency).

**Sparkline wall data:** Fetch key indicators from:
- `GET /api/wealth/macro/fred?series_ids=GDP,CPIAUCSL,UNRATE,FEDFUNDS&days=365`
- `GET /api/wealth/macro/treasury?series=10y_yield&days=365`

These are indicative — the exact series_ids depend on what the backend has in `macro_data`. Start with the most common 6-8 indicators. If the endpoint returns empty for a series, skip that sparkline.

#### 2. `frontends/wealth/src/lib/components/terminal/macro/RegimeTile.svelte`

One regional regime tile. Renders:
- Region label (US / EU / JP / EM) in `--terminal-fg-primary`.
- Composite score as a large number (e.g., "72") in `--terminal-accent-amber`.
- Regime label badge: "Normal" = `--terminal-status-ok`, "Risk On" = `--terminal-accent-cyan`, "Risk Off" = `--terminal-accent-amber`, "Crisis" = `--terminal-status-error`.
- 4 dimension bars (Growth, Inflation, Employment, Financial Conditions) as horizontal progress bars, 0-100.
- Mini sparkline of the composite score over last 90 days (if historical data available from regime endpoint).

Props:
```typescript
interface RegimeTileProps {
    region: string;           // "US" | "EU" | "JP" | "EM"
    compositeScore: number;   // 0-100
    regime: string;           // "Normal" | "Risk On" | "Risk Off" | "Crisis"
    dimensions: Array<{ name: string; score: number }>;
}
```

Regime label mapping from backend enum values:
- "REGIME_NORMAL" or "normal" → "Normal"
- "REGIME_RISK_ON" or "risk_on" → "Risk On"
- "REGIME_RISK_OFF" or "risk_off" → "Risk Off"
- "REGIME_CRISIS" or "crisis" → "Crisis"

#### 3. `frontends/wealth/src/lib/components/terminal/macro/SparklineWall.svelte`

Grid of macro indicator sparklines. Each cell shows:
- Indicator name (human-readable, e.g., "GDP Growth", "CPI YoY", "Unemployment").
- Current value + change direction arrow.
- Mini sparkline chart via `TerminalChart` (line chart, no axis labels, just the line).
- Sparkline color: positive trend = `--terminal-status-ok`, negative = `--terminal-status-error`, flat = `--terminal-fg-secondary`.

Props:
```typescript
interface SparklineWallProps {
    indicators: Array<{
        name: string;
        currentValue: number;
        previousValue: number;
        history: Array<{ date: string; value: number }>;
        unit: string;  // "%", "bps", "idx"
    }>;
}
```

Layout: CSS grid, 4 columns, 2 rows = 8 indicator cells.

#### 4. `frontends/wealth/src/lib/components/terminal/macro/CommitteeReviewFeed.svelte`

Scrollable feed of recent macro committee reviews.

Each review card shows:
- Date (`formatDate`).
- Status badge: "approved" = `--terminal-status-ok`, "pending" = `--terminal-accent-amber`, "rejected" = `--terminal-status-error`.
- Summary text (first 200 chars of review content, truncated).
- Click → opens review in a simple read-only panel or navigates to library.

Props:
```typescript
interface CommitteeReviewFeedProps {
    reviews: Array<{
        id: string;
        status: string;
        createdAt: string;
        summary: string;
    }>;
}
```

#### 5. Modify `TerminalTopNav.svelte`

- Change MACRO tab status from `"pending"` to `"active"`.
- Add `const HREF_MACRO = resolve("/macro");`
- Wire as active `<a>` element.
- Add to `isHrefActive` and `activePathSegment`.
- Keep ALLOC as pending for now (Session B activates it).

### VERIFICATION

1. `pnpm --filter @investintell/wealth check` passes.
2. MACRO tab is active, clickable, navigates to `(terminal)/macro`.
3. Four regime tiles render with scores and dimension bars.
4. Sparkline wall shows macro indicators.
5. Committee review feed scrolls.
6. All data fetched client-side with auth.
7. No hex colors, no Urbanist font, no shadcn imports.
8. Regime labels are human-readable (never raw enums).

### ANTI-PATTERNS

- Do NOT import from `$lib/components/macro/`. Those components use old design tokens. Build fresh.
- Do NOT use Chart.js. Use ECharts via `TerminalChart` only.
- Do NOT show raw FRED series IDs in the UI. Map to human-readable names.
- Do NOT fetch external APIs. All data comes from backend DB-first endpoints.
- Do NOT create complex chart interactions. Sparklines are read-only, no zoom/pan.

---

## Session B — Allocation Editor

### CONTEXT

Session A built `(terminal)/macro`. The allocation backend has full CRUD: strategic weights, tactical positions, effective allocation, simulation, regime bands. The Builder already has a RegimeTab that shows regime history and allocation bands — the allocation editor is the **authoring surface** where IC members set the strategic weights that flow into the Builder.

Profile is always "default" for now (single-profile mode). The backend validates the profile string.

### OBJECTIVE

1. Create `(terminal)/allocation/+page.svelte` — three-column allocation editor.
2. Activate ALLOC tab in TopNav.
3. Wire forward link `[-> BUILDER]` to carry allocation context.

### DELIVERABLES

#### 1. `frontends/wealth/src/routes/(terminal)/allocation/+page.svelte`

Three-column layout:

```
+------------------+----------------------+------------------+
| BLOCK TREE       | WEIGHTS EDITOR       | IMPACT PREVIEW   |
| allocation       | strategic weights    | effective alloc  |
| blocks           | + tactical overlay   | pie/bar chart    |
| (read-only tree) | (editable sliders)   | simulation btn   |
+------------------+----------------------+------------------+
```

Left column (250px): Block tree.
Center column (1fr): Weights editor.
Right column (350px): Impact preview.

**Data fetching:** Client-side `$effect`.
- `GET /api/wealth/allocation/default/strategic` — strategic weights.
- `GET /api/wealth/allocation/default/tactical` — tactical positions.
- `GET /api/wealth/allocation/default/effective` — effective allocation.
- `GET /api/wealth/allocation/regime` — current global regime.

**Block tree** (left column):
- Fetch allocation blocks from the strategic weights response.
- Render as a flat list (blocks are single-level in current schema).
- Each block shows: name, strategic weight %, allocation status.
- Clicking a block scrolls the weights editor to that block's row.

**Weights editor** (center column):
- Table-like layout: one row per allocation block.
- Columns: Block Name | Strategic % | Tactical +/- | Effective % | Regime Suggestion
- Strategic weights are editable (input fields, type=number, step=0.1).
- Tactical positions are editable (+/- overweight in percentage points).
- Effective = strategic + tactical (computed, read-only, `$derived`).
- Total row at bottom: must sum to 100%. Show warning badge if total != 100%.
- Regime suggestion column: if current regime is "Risk Off", show suggested adjustments (backend provides this via `regime-bands` endpoint).
- Save button: `PUT /api/wealth/allocation/default/strategic` + `PUT /api/wealth/allocation/default/tactical`.
- Must be idempotent — disable save button during submission, re-enable on response.

**Impact preview** (right column):
- Effective allocation as a horizontal stacked bar chart (`TerminalChart`).
- Current regime badge.
- `[SIMULATE]` button: calls `POST /api/wealth/allocation/default/simulate` with current effective weights.
- Simulation result shows: expected return, risk estimate, improvement delta.
- `[-> BUILDER]` button: navigates to `(terminal)/portfolio/builder` (carries profile in URL query param `?alloc=default`).

#### 2. `frontends/wealth/src/lib/components/terminal/allocation/WeightsEditor.svelte`

Editable weights table component.

Props:
```typescript
interface WeightsEditorProps {
    blocks: Array<{
        blockId: string;
        name: string;
        strategicWeight: number;
        tacticalOverweight: number;
    }>;
    regimeSuggestions: Array<{
        blockId: string;
        suggestedWeight: number;
    }> | null;
    onSave: (strategic: Array<{blockId: string; weight: number}>, tactical: Array<{blockId: string; overweight: number}>) => void;
    isSaving: boolean;
}
```

Editing rules:
- Input fields styled with `--terminal-*` tokens (mono font, no border radius, hairline border).
- On focus: border becomes `--terminal-accent-amber`.
- Modified values shown in `--terminal-accent-cyan` until saved.
- Total validation: sum of strategic weights must equal 100.0 (tolerance 0.01).
- If total != 100: row shows in `--terminal-status-error`, save button disabled.

#### 3. `frontends/wealth/src/lib/components/terminal/allocation/ImpactPreview.svelte`

Right-side panel showing effective allocation visualization and simulation.

Props:
```typescript
interface ImpactPreviewProps {
    effective: Array<{ name: string; weight: number }>;
    regime: string;
    simulationResult: {
        expectedReturn: number;
        riskEstimate: number;
        improvementDelta: number;
    } | null;
    onSimulate: () => void;
    isSimulating: boolean;
}
```

#### 4. Modify `TerminalTopNav.svelte`

- Change ALLOC tab status from `"pending"` to `"active"`.
- Add `const HREF_ALLOC = resolve("/allocation");`
- Wire as active `<a>`.

### VERIFICATION

1. `pnpm --filter @investintell/wealth check` passes.
2. ALLOC tab active, navigates to `(terminal)/allocation`.
3. Strategic weights load and display correctly.
4. Editing a weight updates the effective column in real-time.
5. Total validation prevents saving when sum != 100%.
6. Simulate button triggers simulation and shows results.
7. `[-> BUILDER]` navigates to builder.
8. No hex colors, no shadcn, no localStorage.

### ANTI-PATTERNS

- Do NOT build a drag-drop interface for allocation blocks. Simple editable table is correct.
- Do NOT show raw simulation output keys. Map to human-readable labels.
- Do NOT allow negative strategic weights (min=0, max=100).
- Do NOT create a separate save endpoint — use the existing PUT endpoints.

---

## Session C — Cross-Wiring + Polish

### CONTEXT

Sessions A and B built macro desk and allocation editor. This session wires cross-surface links and polishes.

### OBJECTIVE

1. Wire `[PIN REGIME]` button on macro desk → writes regime label to TerminalContextRail.
2. Wire regime display on TopNav right cluster (currently shows "MARKET STANDBY") to read from `GET /allocation/regime`.
3. Ensure `[-> BUILDER]` from allocation carries context.
4. Add keyboard shortcuts: `g m` → macro, `g a` → allocation (go-to shortcuts in TerminalShell).
5. Polish pass: verify all new components follow terminal tokens, no hex leaks, no font leaks.

### DELIVERABLES

#### 1. Modify `TerminalShell.svelte`

Add go-to shortcuts in the existing keyboard handler:
- `g` then `m` within 500ms → `goto(resolve("/macro"))`.
- `g` then `a` within 500ms → `goto(resolve("/allocation"))`.
- `g` then `d` within 500ms → `goto(resolve("/dd"))` (from Phase 6).

#### 2. Modify `TerminalTopNav.svelte`

Replace the static "MARKET STANDBY" regime display:
- Fetch `GET /api/wealth/allocation/regime` on mount.
- Display regime label (sanitized: "Normal" / "Risk On" / "Risk Off" / "Crisis").
- Color the regime value:
  - "Normal" → `--terminal-status-ok`
  - "Risk On" → `--terminal-accent-cyan`
  - "Risk Off" → `--terminal-accent-amber`
  - "Crisis" → `--terminal-status-error`
- Poll every 5 minutes (macro regime changes daily at most).

#### 3. Modify `TerminalContextRail.svelte`

Add a "pinned regime" section. When user clicks `[PIN REGIME]` on macro desk:
- Store the pinned regime label in a Svelte context (`setContext`).
- ContextRail reads the context and displays: "REGIME: {label}" with appropriate color.
- This context is available to Builder and other downstream surfaces.

#### 4. Wire Builder to read allocation profile from URL

In `(terminal)/portfolio/builder/+page.svelte`:
- Check for `?alloc=default` query parameter.
- If present, display an "Allocation: default" badge in the builder header.
- This is informational only — the builder already reads allocation data. The badge confirms the navigation link worked.

### VERIFICATION

1. `pnpm --filter @investintell/wealth check` passes.
2. TopNav regime display shows real regime state with color.
3. `g m` keyboard shortcut navigates to macro.
4. `g a` navigates to allocation.
5. `g d` navigates to DD queue.
6. PIN REGIME writes to context rail.
7. No regressions on existing terminal surfaces (screener, builder, live).
