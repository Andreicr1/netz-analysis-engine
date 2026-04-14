# Phase 8 — Research: Kill Mocks + Wire Real Data

**Date:** 2026-04-14
**Branch:** `feat/terminal-research-real-data`
**Sessions:** 2 (Session A: Kill mocks + tokenize, Session B: Library + Content tabs)
**Depends on:** main (Phases 1-7 + regime unification merged)

---

## Strategic Rationale

The Research surface (`(terminal)/research`) is ACTIVE in the TopNav and renders a 3-column layout (asset tree | chart | KPIs). The asset tree and chart fetch real API data. But the right-side KPI panel (`TerminalRiskKpis.svelte`) uses **deterministic mock data** generated from a hash of the node ID. Additionally, all research components use hex colors and Urbanist font instead of terminal tokens. This violates `feedback_infra_before_visual.md`: no surface can be declared done while reporting fake data.

---

## Session A — Kill Mocks + Tokenize Research Components

### CONTEXT

The research components live in `frontends/wealth/src/lib/components/research/terminal/`. There are 5 components:
- `TerminalResearchShell.svelte` — 3-column layout orchestrator
- `TerminalAssetTree.svelte` — fund browser (REAL data from `/screener/catalog`)
- `TerminalResearchChart.svelte` — risk timeseries (REAL data from `/risk/timeseries/{id}`)
- `TerminalRiskKpis.svelte` — risk KPIs (**MOCK data** from `mockRisk()` function)
- `TerminalHoldingsGrid.svelte` — holdings (REAL data from `/discovery/funds/{ticker}/analysis/holdings/top`)
- `ScoreBreakdownPopover.svelte` — score breakdown (**MOCK data** derived from mock `managerScore`)

The mock function `mockRisk(node)` at `TerminalRiskKpis.svelte` generates fake metrics (annReturn, annVolatility, sharpe, sortino, maxDrawdown, beta, trackingError, infoRatio, managerScore) from a deterministic hash of node.id. The score breakdown popover also uses mock data.

**Real endpoint available:** `GET /api/wealth/instruments/{instrument_id}/risk-metrics` returns `InstrumentRiskMetricsRead`:
```typescript
{
    instrument_id: string;
    score_components: Record<string, number> | null;  // 6 scoring components with weights
    manager_score: number | null;                     // 0-100 composite
    sharpe_1y: number | null;
    volatility_1y: number | null;
    max_drawdown_1y: number | null;
    cvar_95_1m: number | null;
}
```

The `fund_risk_metrics` table also has: `sortino_1y`, `beta_1y`, `information_ratio_1y`, `tracking_error_1y`, `return_1y`, `return_3y_ann`, `alpha_1y`, `max_drawdown_3y`, `rsi_14`, `bb_position`, `blended_momentum_score`, `volatility_garch`, `dtw_drift_score`. These are pre-computed by the `global_risk_metrics` worker daily — real data, not computed on request.

**Problem:** The `InstrumentRiskMetricsRead` schema only exposes 5 fields. To show the full KPI set, either:
- Option A: Expand `InstrumentRiskMetricsRead` to include more fields from `FundRiskMetrics` model
- Option B: Create a new endpoint/schema that returns the full KPI set

**Choose Option A** — add the missing fields to `InstrumentRiskMetricsRead` at `backend/app/domains/wealth/schemas/instrument.py:63`. The schema already has `from_attributes=True` + `extra="ignore"`, so just add the fields and the ORM will populate them. Fields to add:

```python
# Return metrics
return_1y: float | None = None
return_3y_ann: float | None = None

# Risk metrics (additional)
sortino_1y: float | None = None
max_drawdown_3y: float | None = None

# Relative metrics
alpha_1y: float | None = None
beta_1y: float | None = None
information_ratio_1y: float | None = None
tracking_error_1y: float | None = None

# Momentum
blended_momentum_score: float | None = None

# GARCH
volatility_garch: float | None = None
```

### OBJECTIVE

1. Expand `InstrumentRiskMetricsRead` schema with additional fields from `FundRiskMetrics`.
2. Replace `mockRisk()` in `TerminalRiskKpis.svelte` with real API call to `GET /instruments/{instrumentId}/risk-metrics`.
3. Replace mock score breakdown with real `score_components` from the API response.
4. Migrate all 5 research components from hex colors to `--terminal-*` tokens.
5. Migrate all fonts from Urbanist to `var(--terminal-font-mono)`.

### CONSTRAINTS

- All colors via `--terminal-*` CSS custom properties. No hex values anywhere.
- Font: `var(--terminal-font-mono)` only. No Urbanist, no sans-serif.
- Border radius: `var(--terminal-radius-none)` (0). No rounding.
- Formatters from `@netz/ui` exclusively (`formatPercent`, `formatNumber`, `formatCurrency`).
- No localStorage. State is in-memory via `$state` runes.
- Svelte 5 runes: `$state`, `$derived`, `$effect`.
- Smart backend / dumb frontend: show "Annual Return: 12.3%" not "return_1y: 0.123". Show "Netz Score: 82" not "manager_score: 82.00".
- The tree node provides `instrumentId` (UUID) for the risk-metrics endpoint. Some tree nodes may have `instrumentId = null` (no NAV data). Handle gracefully: show "No risk data available" instead of crashing.
- API calls use `createClientApiClient` from `$lib/api/client` with auth.

### DELIVERABLES

#### 1. Expand `InstrumentRiskMetricsRead` schema

File: `backend/app/domains/wealth/schemas/instrument.py`

Add the 10 fields listed above to `InstrumentRiskMetricsRead`. No other backend changes needed — the endpoint already does `model_validate(row)` from the ORM model which has all columns.

#### 2. Rewrite `TerminalRiskKpis.svelte`

File: `frontends/wealth/src/lib/components/research/terminal/TerminalRiskKpis.svelte`

Changes:
- **Delete** the entire `mockRisk()` function and `mockScoreData` generation.
- **Add** a prop: `instrumentId: string | null` (passed from parent when tree selection changes).
- **Add** `$effect` that fetches `GET /api/wealth/instruments/{instrumentId}/risk-metrics` when `instrumentId` changes. Include cleanup for stale requests.
- **Handle** 404 (no risk metrics) gracefully — show "No risk data available" message.
- **Map** API response fields to display KPIs. Human-readable labels (smart backend/dumb frontend):

| API field | Display label | Format |
|---|---|---|
| `return_1y` | Annual Return | formatPercent |
| `volatility_1y` | Annual Volatility | formatPercent |
| `sharpe_1y` | Sharpe Ratio | formatNumber (2 decimals) |
| `sortino_1y` | Sortino Ratio | formatNumber (2 decimals) |
| `max_drawdown_1y` | Max Drawdown (1Y) | formatPercent |
| `max_drawdown_3y` | Max Drawdown (3Y) | formatPercent |
| `cvar_95_1m` | Risk Budget (1M) | formatPercent |
| `beta_1y` | Beta | formatNumber (2 decimals) |
| `tracking_error_1y` | Tracking Error | formatPercent |
| `information_ratio_1y` | Information Ratio | formatNumber (2 decimals) |
| `alpha_1y` | Alpha | formatPercent |
| `blended_momentum_score` | Momentum | formatNumber (0 decimals) + "/100" |
| `manager_score` | Netz Score | formatNumber (0 decimals) + "/100" |

- **Score display** (bottom of KPI panel): Show `manager_score` with the same ELITE/EVICTION logic but using terminal tokens:
  - `>= 75`: `[ ELITE ]` in `--terminal-accent-cyan`
  - `< 40`: `[ EVICTION ]` in `--terminal-accent-amber`
  - Otherwise: numeric in `--terminal-fg-primary`
- **Tear Sheet button**: Keep the existing real API call (`POST /wealth/funds/{externalId}/reports/tear-sheet`). Already works.
- **Replace all hex colors** with `--terminal-*` tokens.
- **Replace all Urbanist** with `var(--terminal-font-mono)`.

#### 3. Rewrite `ScoreBreakdownPopover.svelte`

File: `frontends/wealth/src/lib/components/research/terminal/ScoreBreakdownPopover.svelte`

Changes:
- **Delete** mock score computation.
- **Accept** `scoreComponents: Record<string, number> | null` and `managerScore: number | null` as props (from API response).
- **Render** real `score_components` dict. Keys are component names (e.g., "return_consistency", "risk_adjusted_return", etc.). Map to human labels:
  - "return_consistency" → "Return Consistency"
  - "risk_adjusted_return" → "Risk-Adjusted Return"
  - "drawdown_control" → "Drawdown Control"
  - "information_ratio" → "Information Ratio"
  - "flows_momentum" → "Flows Momentum"
  - "fee_efficiency" → "Fee Efficiency"
  - Fallback: title-case the key
- **Replace all hex colors** with `--terminal-*` tokens.

#### 4. Tokenize `TerminalResearchShell.svelte`

File: `frontends/wealth/src/lib/components/research/terminal/TerminalResearchShell.svelte`

Changes:
- Replace `background: #000000` with `var(--terminal-bg-root)`.
- Replace `#0c1018` with `var(--terminal-bg-surface)`.
- Replace `#05080f` with `var(--terminal-bg-base)`.
- Replace `font-family: "Urbanist"` with `var(--terminal-font-mono)`.
- Replace all `rgba(255, 255, 255, 0.0X)` borders with `var(--terminal-border-hairline)`.
- Replace `#2d7ef7` (active tab) with `var(--terminal-accent-cyan)`.
- Replace `#64748b` (inactive text) with `var(--terminal-fg-secondary)`.
- Replace `#e2e8f0` (primary text) with `var(--terminal-fg-primary)`.
- Pass `instrumentId` from tree selection down to `TerminalRiskKpis`.

#### 5. Tokenize `TerminalAssetTree.svelte`

File: `frontends/wealth/src/lib/components/research/terminal/TerminalAssetTree.svelte`

Changes:
- Replace all hex colors with `--terminal-*` tokens (same mapping as shell).
- Replace Urbanist with `var(--terminal-font-mono)`.

#### 6. Tokenize `TerminalHoldingsGrid.svelte`

File: `frontends/wealth/src/lib/components/research/terminal/TerminalHoldingsGrid.svelte`

Changes:
- Replace all hex colors with `--terminal-*` tokens.
- Replace Urbanist and JetBrains Mono references with `var(--terminal-font-mono)`.

#### 7. Tokenize `TerminalResearchChart.svelte`

File: `frontends/wealth/src/lib/components/research/terminal/TerminalResearchChart.svelte`

This component already uses `createTerminalLightweightChartOptions()` and `terminalLWSeriesColors()` from `@investintell/ui`. Check if any hex values remain and replace. Font should be `var(--terminal-font-mono)`.

### VERIFICATION

1. `make test` passes (schema expansion is additive, no breaking changes).
2. `make typecheck` passes.
3. `pnpm --filter @investintell/wealth check` passes.
4. Select a fund in the asset tree → KPI panel shows REAL risk metrics from API.
5. Select a fund with no risk data → panel shows "No risk data available".
6. Score breakdown popover shows real component weights.
7. Tear sheet export still works.
8. `grep -r "#[0-9a-fA-F]\{3,8\}" frontends/wealth/src/lib/components/research/terminal/` returns zero matches.
9. `grep -r "Urbanist" frontends/wealth/src/lib/components/research/terminal/` returns zero matches.

### ANTI-PATTERNS

- Do NOT keep `mockRisk()` as a fallback. Delete it entirely. If the API returns 404, show "No risk data".
- Do NOT import shadcn components. Use terminal-native HTML with `--terminal-*` tokens.
- Do NOT use `.toFixed()` or `.toLocaleString()`. Use formatters from `@netz/ui`.
- Do NOT create `+page.server.ts` load functions. Fetch client-side with auth.
- Do NOT add new dependencies or libraries.

---

## Session B — Library + Content Tabs

### CONTEXT

Session A delivered real data in the Research ANALYTICS view. Now we add two more views: LIBRARY (document browser) and REPORTS (content generation).

The existing library system lives in `frontends/wealth/src/routes/(app)/library/` with 12+ components in `$lib/components/library/`. The content system lives in `frontends/wealth/src/routes/(app)/content/` with inline SSE + polling.

**Key architectural decision:** Do NOT rewrite library components. Wrap them in the terminal shell and port tokens progressively. The library system is complex (tree loader, preview pane, pins, bundles, context menus, filter bar) and rewriting would take 3+ sessions with high regression risk.

### OBJECTIVE

1. Add a tab bar to `TerminalResearchShell`: `ANALYTICS | LIBRARY | REPORTS`.
2. ANALYTICS tab renders the existing 3-column research layout.
3. LIBRARY tab embeds `LibraryShell` with a terminal-compatible wrapper.
4. REPORTS tab shows content list with generation buttons and SSE streaming.

### DELIVERABLES

#### 1. Modify `TerminalResearchShell.svelte`

Add a top-level tab switcher above the current content:

```
┌─────────────────────────────────────────────┐
│  [ ANALYTICS ]  [ LIBRARY ]  [ REPORTS ]    │
├─────────────────────────────────────────────┤
│  (content changes based on active tab)      │
└─────────────────────────────────────────────┘
```

- Tab bar styled as inline text tabs (not pills — avoid confusion with TopNav).
- Active tab: `--terminal-accent-cyan` with bottom border.
- Inactive tab: `--terminal-fg-secondary`.
- Default tab: ANALYTICS.
- Use `$state` for active tab. No URL mutation (tabs are ephemeral within Research).

When ANALYTICS is active: render existing 3-column layout (tree | chart/holdings | KPIs).
When LIBRARY is active: render `LibraryWrapper` component (see below).
When REPORTS is active: render `ReportsPanel` component (see below).

#### 2. Create `frontends/wealth/src/lib/components/terminal/research/LibraryWrapper.svelte`

A wrapper that embeds the existing `LibraryShell` with terminal styling overrides.

Implementation:
- Import `LibraryShell` from `$lib/components/library/LibraryShell.svelte`.
- Wrap in a `<div class="library-terminal-wrapper">` that applies terminal token overrides via CSS cascade:
  ```css
  .library-terminal-wrapper {
    --ii-bg-surface: var(--terminal-bg-surface);
    --ii-bg-base: var(--terminal-bg-base);
    --ii-fg-primary: var(--terminal-fg-primary);
    --ii-fg-secondary: var(--terminal-fg-secondary);
    --ii-border: var(--terminal-border-hairline);
    --ii-accent: var(--terminal-accent-cyan);
    font-family: var(--terminal-font-mono);
    border-radius: 0;
  }
  ```
- This CSS variable remapping trick makes the library components use terminal colors without rewriting them. The library components reference `--ii-*` tokens internally; by overriding those custom properties in a parent wrapper, we retheme them.
- Check which `--ii-*` tokens the library components actually use (grep `$lib/components/library/` for `--ii-`) and map each one to the appropriate `--terminal-*` equivalent.
- If some library components use raw hex values instead of `--ii-*` tokens, those will need targeted `:global()` overrides in the wrapper.

Data fetching:
- Library needs the tree data. The `(app)/library/+page.server.ts` fetches it via server-side load. Since Research is client-side only, fetch the tree data client-side:
  ```typescript
  const treeRes = await api.get('/library/tree');
  ```
- Pass the tree data to `LibraryShell` as a prop (check what props it expects).

#### 3. Create `frontends/wealth/src/lib/components/terminal/research/ReportsPanel.svelte`

A panel for content generation (Investment Outlooks, Flash Reports, Manager Spotlights).

Data fetching:
- Fetch `GET /api/wealth/content` on mount for list of existing reports.
- Poll every 30s for status updates on generating reports.

Layout:
```
┌──────────────────────────────────────────────┐
│  GENERATE: [ OUTLOOK ] [ FLASH ] [ SPOTLIGHT ]│
├──────────────────────────────────────────────┤
│  Report list (scrollable)                    │
│  ┌────────────────────────────────────────┐  │
│  │ Quarterly Outlook — Apr 2026           │  │
│  │ Status: PUBLISHED  [DOWNLOAD PDF]      │  │
│  ├────────────────────────────────────────┤  │
│  │ Flash Report — Apr 10 2026             │  │
│  │ Status: GENERATING... (LiveDot)        │  │
│  ├────────────────────────────────────────┤  │
│  │ Manager Spotlight — Bridgewater        │  │
│  │ Status: READY  [DOWNLOAD PDF]          │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

Generation buttons:
- `[ OUTLOOK ]` → `POST /api/wealth/content/outlooks` (returns 202 + jobId)
- `[ FLASH ]` → `POST /api/wealth/content/flash-reports` (returns 202 + jobId)
- `[ SPOTLIGHT ]` → opens a mini fund picker dialog, then `POST /api/wealth/content/spotlights?instrument_id={id}`

SSE streaming for generating reports:
- Use `createTerminalStream` from `$lib/components/terminal/runtime/stream.ts`
- Connect to `GET /api/wealth/content/{contentId}/stream/{jobId}`
- On completion: refresh report list
- Fallback: if SSE fails, poll `GET /api/wealth/content` every 5s until status changes

Report cards:
- Status badges: `generating` (LiveDot + amber), `ready`/`published` (green), `failed` (red), `draft` (secondary)
- Download button: `GET /api/wealth/content/{id}/download` → PDF blob → browser download
- All styled with `--terminal-*` tokens

Fund picker dialog for Spotlight:
- Simple terminal-native dialog (same pattern as DDApprovalDialog)
- Search input that filters funds from the asset tree data or fetches `/api/wealth/funds`
- Select fund → POST → close dialog

### VERIFICATION

1. `pnpm --filter @investintell/wealth check` passes.
2. Tab switcher renders 3 tabs. Default is ANALYTICS.
3. ANALYTICS tab shows the existing research layout with real KPI data (Session A).
4. LIBRARY tab shows the library tree and document readers.
5. REPORTS tab shows existing reports with status badges.
6. Generating a report shows LiveDot and SSE progress.
7. Download PDF works from Reports tab.
8. No hex colors in new files.
9. Library components render with terminal-compatible colors via CSS variable remapping.

### ANTI-PATTERNS

- Do NOT rewrite library components. Wrap them with CSS variable remapping.
- Do NOT create server-side load functions. Fetch client-side with auth.
- Do NOT use `EventSource`. Use `createTerminalStream` or `fetch` + `ReadableStream`.
- Do NOT add `localStorage`.
- Do NOT create complex state management for the tab switcher. Simple `$state` string.
- Do NOT show raw content type enums ("investment_outlook"). Map to "Investment Outlook".
