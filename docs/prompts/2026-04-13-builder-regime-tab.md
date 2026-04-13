# Builder REGIME Tab — Regime History Overlay + Signal Breakdown

**Date:** 2026-04-13
**Branch:** `feat/builder-regime-tab` (off `main`)
**Scope:** Backend (1 new endpoint + 1 schema) + Frontend (1 new component + page wiring)
**Risk:** LOW — additive only, no schema/migration changes
**Priority:** MEDIUM — analytical value, proves regime model's predictive power

---

## Problem Statement

The Builder's right column has 6 tabs (WEIGHTS, RISK, STRESS, BACKTEST, MONTE CARLO, ADVISOR) but lacks a dedicated space for regime analysis. The left column's `RegimeContextStrip` shows current regime + band ranges in 120px — too compressed for the chart and signal breakdown that would prove the model anticipates market drops.

A REGIME tab on the right column provides:
1. Regime history chart — S&P500 price with background bands colored by regime classification, visually proving regime switches to Defensive/Stress BEFORE S&P drops
2. Signal breakdown — which of the 10 macro signals are driving the current classification
3. Allocation band summary — the Equity/FI/Alt/Cash min→target→max ranges with regime context

---

## CONTEXT

### Architecture

- **Backend:** FastAPI async-first, `AsyncSession`, `get_db_with_rls`, `response_model=` on all routes, `model_validate()` returns
- **Frontend:** SvelteKit, Svelte 5 runes (`$state`, `$derived`, `$effect`), `svelte-echarts` via `TerminalChart.svelte` gateway, all chart options via `createTerminalChartOptions()` from `@investintell/ui`
- **Data sources:**
  - `macro_regime_snapshot` — GLOBAL table (no RLS), one row per `as_of_date`, columns: `raw_regime` (RISK_ON/RISK_OFF/CRISIS/INFLATION), `stress_score`, `signal_details` (JSONB)
  - `benchmark_nav` — GLOBAL table (no RLS), keyed by `(block_id, nav_date)`, has `nav` (price), `return_1d`
  - `allocation_blocks` — GLOBAL table, has `benchmark_ticker` (e.g. "SPY"), `block_id` (e.g. "na_equity_large")
  - `GET /allocation/regime` — existing endpoint, returns current regime snapshot with `signal_details`
  - `GET /allocation/{profile}/regime-bands` — existing endpoint, returns current effective bands

### Key Files

| File | Role |
|---|---|
| `backend/app/domains/wealth/routes/allocation.py` | Allocation routes (regime, taa-history, regime-bands) |
| `backend/app/domains/wealth/schemas/allocation.py` | Pydantic schemas for allocation |
| `backend/app/domains/wealth/models/allocation.py` | `MacroRegimeSnapshot`, `TaaRegimeState` ORM models |
| `backend/app/domains/wealth/models/benchmark_nav.py` | `BenchmarkNav` model (block_id, nav_date, nav) |
| `backend/app/domains/wealth/models/block.py` | `AllocationBlock` model (block_id, benchmark_ticker) |
| `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte` | Builder page with TABS array and tab rendering |
| `frontends/wealth/src/lib/components/terminal/builder/WeightsTab.svelte` | Reference tab component pattern |
| `frontends/wealth/src/lib/components/terminal/builder/RegimeContextStrip.svelte` | Left-column regime badge + bands |
| `frontends/wealth/src/lib/components/terminal/charts/TerminalChart.svelte` | ECharts gateway (THE ONLY component that imports echarts) |
| `packages/investintell-ui/src/lib/charts/terminal-options.ts` | `createTerminalChartOptions()` factory |
| `frontends/wealth/src/lib/types/taa.ts` | TAA frontend types, `taaRegimeLabel()`, `taaRegimeColor()` helpers |
| `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` | Workspace state with `regimeBands` |

### signal_details Structure

The `signal_details` JSONB from `MacroRegimeSnapshot` is a `dict[str, str]` with keys like:
- `vix` → `"VIX=18.3 < 20 (benign)"`
- `yield_curve_spread` → `"Spread=0.45% — normal shape"`
- `cpi_yoy` → `"CPI_YoY=3.2% < 4.0% (below threshold)"`
- `sahm_rule` → `"Sahm=0.23 < 0.50 (below threshold)"`
- `hy_oas` → `"OAS=380bp < 500bp (benign)"`
- `baa_spread` → `"Baa=1.85% < 2.50% (benign)"`
- `fed_funds_delta_6m` → `"FF_delta=0bp — no change"`
- `dxy_zscore` → `"DXY_Z=0.8 < 1.5 (normal)"`
- `energy_shock` → `"Energy=0.2 < 0.5 (benign)"`
- `cfnai` → `"CFNAI=-0.15 > -0.70 (benign)"`
- `composite_stress` → `"42/100 (10 signals)"`
- `decision` → `"RISK_ON: composite stress 42/100 — benign conditions"`

---

## OBJECTIVE

### Backend: New endpoint `GET /allocation/regime-overlay`

Add to `backend/app/domains/wealth/routes/allocation.py`.

**Path:** `GET /allocation/regime-overlay`
**Query params:** `period` (str, default "3Y", allowed: "1Y", "2Y", "3Y", "5Y")
**Auth:** `get_current_user` (any authenticated user — this is global data)
**Response model:** `RegimeOverlayRead` (new schema)

**Logic:**

1. Compute `start_date` from period param:
   - `1Y` → `date.today() - timedelta(days=365)`
   - `2Y` → `date.today() - timedelta(days=730)`
   - `3Y` → `date.today() - timedelta(days=1095)`
   - `5Y` → `date.today() - timedelta(days=1825)`

2. Resolve SPY block_id dynamically:
   ```python
   spy_block_stmt = (
       select(AllocationBlock.block_id)
       .where(AllocationBlock.benchmark_ticker == "SPY")
       .limit(1)
   )
   spy_block_result = await db.execute(spy_block_stmt)
   spy_block_id = spy_block_result.scalar_one_or_none()
   ```
   If `spy_block_id` is None, return empty `spy_nav` array (do NOT raise 404).

3. Fetch SPY NAV from `benchmark_nav`:
   ```python
   nav_stmt = (
       select(BenchmarkNav.nav_date, BenchmarkNav.nav)
       .where(
           BenchmarkNav.block_id == spy_block_id,
           BenchmarkNav.nav_date >= start_date,
       )
       .order_by(BenchmarkNav.nav_date.asc())
   )
   ```
   Map results to `dates: list[str]` and `spy_values: list[float]`.

4. Fetch regime history from `macro_regime_snapshot`:
   ```python
   regime_stmt = (
       select(MacroRegimeSnapshot.as_of_date, MacroRegimeSnapshot.raw_regime)
       .where(MacroRegimeSnapshot.as_of_date >= start_date)
       .order_by(MacroRegimeSnapshot.as_of_date.asc())
   )
   ```

5. **Collapse consecutive same-regime rows into contiguous bands server-side.** Do NOT return 1250 individual rows. Walk the sorted regime rows and merge consecutive dates with the same `raw_regime` into `{start: str, end: str, regime: str}` objects. Example:
   ```python
   regime_bands: list[dict] = []
   current_band = None
   for row in regime_rows:
       d = row.as_of_date.isoformat()
       r = row.raw_regime
       if current_band is None or current_band["regime"] != r:
           if current_band:
               regime_bands.append(current_band)
           current_band = {"start": d, "end": d, "regime": r}
       else:
           current_band["end"] = d
   if current_band:
       regime_bands.append(current_band)
   ```

6. Return `RegimeOverlayRead`.

**New schema** in `backend/app/domains/wealth/schemas/allocation.py`:

```python
class RegimeBandRange(BaseModel):
    """Contiguous date range where the same regime was active."""
    start: date
    end: date
    regime: str


class RegimeOverlayRead(BaseModel):
    """Regime history overlaid on S&P500 NAV for chart rendering."""
    dates: list[date] = []
    spy_values: list[float] = []
    regime_bands: list[RegimeBandRange] = []
    period: str
```

**Import additions in allocation.py routes:**
- `from app.domains.wealth.models.benchmark_nav import BenchmarkNav`
- `from app.domains.wealth.models.block import AllocationBlock`
- Add `RegimeBandRange`, `RegimeOverlayRead` to the schema imports

---

### Frontend: RegimeTab.svelte

**File:** `frontends/wealth/src/lib/components/terminal/builder/RegimeTab.svelte`

**Structure (3 sections, vertical stack):**

#### Section 1: Regime History Chart (~300px)

- Period selector row: 4 buttons (1Y, 2Y, 3Y, 5Y), default 3Y, terminal-style button group
- `TerminalChart` component with options from `createTerminalChartOptions()`
- **ECharts config:**

```typescript
import { createTerminalChartOptions, readTerminalTokens } from "@investintell/ui";
import type { EChartsOption } from "echarts";

// Regime → color mapping (use CSS vars via readTerminalTokens)
const REGIME_COLORS: Record<string, { color: string; label: string }> = {
    RISK_ON:    { color: tokens.statusSuccess, label: "Expansion" },
    RISK_OFF:   { color: tokens.statusWarn,    label: "Defensive" },
    CRISIS:     { color: tokens.statusError,   label: "Stress" },
    INFLATION:  { color: tokens.accentViolet,  label: "Inflation" },
};
```

- **Series:** Single line series for S&P500:
  ```typescript
  {
      type: "line",
      name: "S&P 500",
      data: overlay.dates.map((d, i) => [d, overlay.spy_values[i]]),
      lineStyle: { width: 1.5, color: tokens.accentAmber },
      itemStyle: { color: tokens.accentAmber },
      symbol: "none",
      smooth: false,
  }
  ```

- **markArea** on the series — one entry per regime band:
  ```typescript
  markArea: {
      silent: true,
      data: overlay.regime_bands.map(band => [
          {
              xAxis: band.start,
              itemStyle: {
                  color: REGIME_COLORS[band.regime]?.color ?? tokens.fgMuted,
                  opacity: 0.12,
              },
          },
          { xAxis: band.end },
      ]),
  }
  ```

- **xAxis:** `{ type: "time" }` (factory default)
- **yAxis:** `{ type: "value", axisLabel: { formatter: (v) => formatNumber(v, 0) } }`
- Pass `showLegend: false` (the regime colors are self-evident from the metadata panel below)

- **Data fetching:** Use `createClientApiClient()` from `$lib/api/client`:
  ```typescript
  const api = createClientApiClient(getToken);
  
  let period = $state<"1Y" | "2Y" | "3Y" | "5Y">("3Y");
  let overlay = $state<RegimeOverlay | null>(null);
  let loading = $state(true);
  
  interface RegimeOverlay {
      dates: string[];
      spy_values: number[];
      regime_bands: Array<{ start: string; end: string; regime: string }>;
      period: string;
  }
  
  async function fetchOverlay() {
      loading = true;
      try {
          const res = await api.get(`/allocation/regime-overlay?period=${period}`);
          overlay = res;
      } catch (e) {
          console.error("Failed to fetch regime overlay", e);
          overlay = null;
      } finally {
          loading = false;
      }
  }
  
  // Refetch on period change
  $effect(() => {
      void fetchOverlay();
  });
  ```

  **IMPORTANT:** The `$effect` must track `period` reactively. The function reads `period` inside the effect body, which creates the dependency. Avoid using `$effect.pre` — use `$effect`.

#### Section 2: Regime Metadata Panel

- Fetch current regime from existing `GET /allocation/regime` endpoint (already wired — reuse `workspace.regimeBands` if available, or make a standalone call)
- Display:
  - **Regime badge** (reuse `taaRegimeLabel()` / `taaRegimeColor()` from `$lib/types/taa`)
  - **Stress score** as a horizontal bar (same pattern as `RegimeContextStrip`)
  - **Regime duration** — compute from the last `regime_bands` entry: `Math.ceil((new Date(lastBand.end) - new Date(lastBand.start)) / 86400000)` days
  - **Signal breakdown table** — parse `signal_details` from `GET /allocation/regime` response:
    ```
    SIGNAL          VALUE           STATUS
    VIX             18.3            Benign
    Yield Curve     0.45%           Normal
    CPI YoY         3.2%            Below threshold
    ...
    ```
    Parse the string values by extracting the numeric part and the parenthetical status. If parsing fails, show the raw string.
  - Signal labels mapping:
    ```typescript
    const SIGNAL_LABELS: Record<string, string> = {
        vix: "VIX",
        yield_curve_spread: "Yield Curve",
        cpi_yoy: "CPI YoY",
        sahm_rule: "Sahm Rule",
        hy_oas: "HY OAS",
        baa_spread: "Baa Spread",
        fed_funds_delta_6m: "Fed Funds Delta",
        dxy_zscore: "DXY Z-Score",
        energy_shock: "Energy Shock",
        cfnai: "CFNAI",
    };
    ```
    Skip the `composite_stress` and `decision` keys from the table (show `decision` as a footnote below the table instead).

#### Section 3: Allocation Bands Summary

- Same layout as `RegimeContextStrip` bands section but with more horizontal space
- Reuse `regimeBands` from workspace (same derived value used by RegimeContextStrip)
- Show the 4 asset class rows: Equity, Fixed Income, Alternatives, Cash
- Each row: `Label | min → center → max` using `formatPercent` from `@investintell/ui`
- Add the regime posture one-liner below (`taaRegimePosture()`)

**Styling:** Follow the terminal aesthetic from `WeightsTab.svelte`:
- `font-family: var(--terminal-font-mono)`
- `font-size: var(--terminal-text-11)` for body, `var(--terminal-text-10)` for labels
- `color: var(--terminal-fg-secondary)` for body text
- `text-transform: uppercase; letter-spacing: var(--terminal-tracking-caps)` for headers
- `border-bottom: var(--terminal-border-hairline)` for section separators
- Period selector buttons: same pattern as tab buttons (active = `var(--terminal-accent-amber)`)

---

### Builder +page.svelte Changes

**File:** `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte`

**Change 1 — Import RegimeTab (line ~25):**
```typescript
import RegimeTab from "$lib/components/terminal/builder/RegimeTab.svelte";
```

**Change 2 — TABS array (line 68):**
Change from:
```typescript
const TABS = ["WEIGHTS", "RISK", "STRESS", "BACKTEST", "MONTE CARLO", "ADVISOR"] as const;
```
To:
```typescript
const TABS = ["REGIME", "WEIGHTS", "RISK", "STRESS", "BACKTEST", "MONTE CARLO", "ADVISOR"] as const;
```
REGIME is FIRST (before WEIGHTS).

**Change 3 — Default active tab (line 71):**
Change from:
```typescript
let activeTab = $state<TabId>("WEIGHTS");
```
To:
```typescript
let activeTab = $state<TabId>("REGIME");
```

**Change 4 — CRITICAL: Tab visit gate (line 79):**
The current code on line 79 reads:
```typescript
const allTabsVisited = $derived(visitedTabs.size === 6);
```
This MUST change to:
```typescript
const allTabsVisited = $derived(visitedTabs.size === TABS.length);
```
If you hardcode 6, the activation bar will NEVER unlock because there are now 7 tabs. Using `TABS.length` is correct and future-proof.

**Change 5 — Tab content rendering (line ~164):**
Add before the WEIGHTS case:
```svelte
{#if activeTab === "REGIME"}
    <RegimeTab />
{:else if activeTab === "WEIGHTS"}
```

**Change 6 — Pass getToken context to RegimeTab:**
The `getToken` context is already available in the page via `getContext`. RegimeTab will call `createClientApiClient(getToken)` internally, same pattern as other tabs. The `getToken` must be passed as a prop OR RegimeTab must use `getContext("netz:getToken")` to retrieve it. Use `getContext` (consistent with `WeightsTab` which reads workspace global state).

---

## CONSTRAINTS

1. **Async-first:** All route handlers use `async def` + `AsyncSession`
2. **Pydantic schemas:** Use `response_model=` on the new endpoint, return via schema constructor
3. **Global tables:** `macro_regime_snapshot`, `benchmark_nav`, `allocation_blocks` have NO RLS — do NOT use `get_db_with_rls` tenant filtering for these queries. However, the endpoint still requires `get_db_with_rls` for the session (the RLS context is set but simply not used by these global tables)
4. **TerminalChart is THE ONLY echarts consumer.** RegimeTab must use `TerminalChart` + `createTerminalChartOptions()`. Never import echarts directly
5. **No hex literals in chart config.** Use `readTerminalTokens()` for all colors
6. **Formatters from @investintell/ui only.** Use `formatPercent`, `formatNumber`, `formatDate` — never `.toFixed()` or `Intl.NumberFormat`
7. **Do NOT modify RegimeContextStrip.** The left-column Zone A stays as-is. The REGIME tab duplicates the band summary with more space — this is intentional
8. **Do NOT add migrations.** All data already exists in `macro_regime_snapshot` + `benchmark_nav`
9. **lazy="raise"** — do not access relationships without explicit loading
10. **expire_on_commit=False** — already set on session factory
11. **No module-level asyncio primitives** — no `Semaphore`, `Lock`, etc. at module level

---

## DELIVERABLES

| File | Action |
|---|---|
| `backend/app/domains/wealth/schemas/allocation.py` | ADD `RegimeBandRange`, `RegimeOverlayRead` schemas |
| `backend/app/domains/wealth/routes/allocation.py` | ADD `get_regime_overlay()` endpoint, ADD imports for `BenchmarkNav`, `AllocationBlock`, `RegimeBandRange`, `RegimeOverlayRead` |
| `frontends/wealth/src/lib/components/terminal/builder/RegimeTab.svelte` | CREATE — full component with chart + metadata + bands |
| `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte` | MODIFY — add REGIME to TABS, import RegimeTab, add tab content, fix visit gate |

---

## VERIFICATION

```bash
# 1. Backend tests
make test ARGS="-k allocation"

# 2. Typecheck
make typecheck

# 3. Lint
make lint

# 4. Architecture contracts
make architecture

# 5. Full gate
make check

# 6. Manual verification — start backend + frontend
make serve  # in one terminal
make dev-wealth  # in another terminal
# Navigate to /portfolio/builder
# Verify:
#   - REGIME tab appears FIRST in tab bar
#   - Chart renders with S&P500 line and colored regime bands
#   - Period selector (1Y/2Y/3Y/5Y) switches data
#   - Signal breakdown table shows 10 signals
#   - Allocation bands summary shows Equity/FI/Alt/Cash ranges
#   - Visit all 7 tabs → activation bar unlocks
```

---

## ANTI-PATTERNS

1. **Do NOT import echarts directly** in RegimeTab — use `TerminalChart` component
2. **Do NOT hardcode SPY block_id** (e.g. "na_equity_large") — resolve dynamically via `AllocationBlock.benchmark_ticker == "SPY"`
3. **Do NOT return per-date regime rows** to the frontend — collapse into contiguous bands server-side
4. **Do NOT use `$state` for the `lastOption` pattern** in any chart component — see the documented warning in `TerminalChart.svelte` lines 118-140
5. **Do NOT hardcode tab count** in the visit gate — use `TABS.length`
6. **Do NOT remove or modify RegimeContextStrip** — it remains in the left column
7. **Do NOT use hex color literals** — use `readTerminalTokens()` or CSS variable references
8. **Do NOT call external APIs** in the endpoint — read from DB only (DB-first pattern)
9. **Do NOT use `EventSource`** for any data fetching — use `fetch()` (auth headers needed)
10. **Do NOT use `.toFixed()` or `Intl.NumberFormat`** — use formatters from `@investintell/ui`

---

## COMMIT

```
feat(builder): add REGIME tab with regime history overlay + signal breakdown

New tab in the Builder right column (position 1, before WEIGHTS) showing:
- S&P500 price chart with colored markArea bands per regime classification
- Signal breakdown table parsing macro_regime_snapshot signal_details
- Allocation bands summary (Equity/FI/Alt/Cash min→center→max)

Backend: GET /allocation/regime-overlay endpoint returning collapsed
regime bands + SPY NAV from benchmark_nav (global, DB-only).

Frontend: RegimeTab.svelte using TerminalChart + createTerminalChartOptions.
Tab visit gate updated to use TABS.length (7 tabs total).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```
