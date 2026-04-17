# PR-A13 — Builder Risk Budget Slider + Achievable Return Band Panel (Static)

**Branch:** `feat/pr-a13-static-band-panel` (cut from `main` post PR-A12.1 + A12.2 merged).
**Estimated effort:** ~4-5h Opus.
**Predecessors:** PR-A11 #190 (cascade_telemetry column), PR-A12 #191 (RU LP cascade), PR-A12.1 #192 (cleanup), PR-A12.2 (profile-differentiated CVaR defaults).
**Successors:** PR-A13.1 (backend `POST /preview-cvar` endpoint), PR-A13.2 (frontend live preview wiring).

---

## Context

Backend ships per-run `portfolio_construction_runs.cascade_telemetry` JSONB with the achievable_return_band and operator_signal. **Frontend currently ignores this field** — `ConstructionRunPayload` in `portfolio-workspace.svelte.ts` doesn't even have the type. Operators today see weights and CVaR delivered but no visual feedback that their CVaR limit choice maps to a return band.

A13 ships the **static** version: panel reads `cascade_telemetry` from the most recent completed run, renders the band chart + signal banner, augments the existing CVaR slider with profile-default affordances. **No live preview** (deferred to A13.2 because the `POST /preview-cvar` backend endpoint doesn't exist yet — that's A13.1).

This is the visible-value-first split: A13 unblocks the band UX immediately against existing backend data; A13.1+A13.2 add live drag-preview later.

---

## Empirical context (verified live, post-A12)

`cascade_telemetry` JSONB shape (from real local DB rows):

```json
{
  "phase_attempts": [...],
  "cascade_summary": "phase_1_succeeded",
  "min_achievable_cvar": 0.00415,
  "achievable_return_band": {
    "lower": 0.09838,
    "upper": 0.30620,
    "lower_at_cvar": 0.00415,
    "upper_at_cvar": 0.01925
  },
  "operator_signal": {
    "kind": "feasible" | "cvar_limit_below_universe_floor" | "upstream_data_missing" | "constraint_polytope_empty",
    "binding": "risk_budget" | null,
    "message_key": "..."
  }
}
```

Conservative example: band [9.84%, 30.62%] at user CVaR=5%. Universe floor 0.42%.

---

## Section A — Backend: minimal type+payload extension (no logic change)

### A.1 Extend the run-record API response

The Builder consumes the construction run via SSE + a final REST GET. Verify which (read `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts:49-74` + `_emit_cascade_phase_events` in `construction_run_executor.py`). The `cascade_telemetry` column already exists; the question is whether the API serializes it.

**Verify by grep:** does the read endpoint for `portfolio_construction_runs` (most likely `GET /api/v1/portfolios/{id}/construction/runs/{run_id}` or similar) include `cascade_telemetry` in its Pydantic response model?

- If YES: skip A.1, move to A.2.
- If NO: add `cascade_telemetry: dict[str, Any] | None = None` to the relevant `PortfolioConstructionRunRead` schema in `backend/app/domains/wealth/schemas/`. ORM model already has the column; SQLAlchemy auto-loads. Just expose in schema.

### A.2 SSE event payload — verify already shipped

PR-A11 added the `cascade_telemetry_completed` SSE event. Verify it carries the complete `achievable_return_band`, `min_achievable_cvar`, and `operator_signal` (per A11/A12 specs it should). If the SSE payload sanitization stripped any of these (per PR-A11 Section D), restore — these are operator-facing payload fields, not raw quant internals.

**No new backend route in A13.** Live preview endpoint is A13.1 scope.

---

## Section B — Frontend: type extensions

### B.1 Define types in `frontends/wealth/src/lib/types/cascade-telemetry.ts` (NEW file)

```typescript
export interface AchievableReturnBand {
  lower: number;
  upper: number;
  lower_at_cvar: number;
  upper_at_cvar: number;
}

export type OperatorSignalKind =
  | "feasible"
  | "cvar_limit_below_universe_floor"
  | "upstream_data_missing"
  | "constraint_polytope_empty";

export interface OperatorSignal {
  kind: OperatorSignalKind;
  binding: string | null;
  message_key: string;
}

export type CascadeSummary =
  | "phase_1_succeeded"
  | "phase_2_robust_succeeded"
  | "phase_3_min_cvar_within_limit"
  | "phase_3_min_cvar_above_limit"
  | "upstream_heuristic";

export interface PhaseAttempt {
  phase: string;
  status: "succeeded" | "infeasible" | "skipped" | "error";
  solver?: string;
  objective_value?: number | null;
  wall_ms?: number;
  infeasibility_reason?: string | null;
  cvar_at_solution?: number | null;
}

export interface CascadeTelemetry {
  phase_attempts: PhaseAttempt[];
  cascade_summary: CascadeSummary;
  min_achievable_cvar: number | null;
  achievable_return_band: AchievableReturnBand | null;
  operator_signal: OperatorSignal | null;
}
```

### B.2 Extend `ConstructionRunPayload` in `portfolio-workspace.svelte.ts:49-74`

Add field:
```typescript
cascade_telemetry: CascadeTelemetry | null;
```

Initialize as `null` in any default-construction site. Update SSE handler (`runConstructJob` / wherever `cascade_telemetry_completed` event is parsed) to hydrate this field on receipt. Use `parseSseStream` pattern from `lib/util/sse-reader.ts:19-40` (canonical fetch+ReadableStream, NOT EventSource).

**Critical state design pitfall** (Svelte agent caught — must be in spec):

The dependency `workspace.constructionRun → cascade_telemetry → band` is 3 levels deep. If `RiskBudgetPanel` initializes `band` via `let band = $state(snapshot?.cascade_telemetry?.achievable_return_band ?? null)`, it will NOT update on subsequent runs. **Required pattern (lock this exactly):**

```ts
const serverBand = $derived(workspace.constructionRun?.cascade_telemetry?.achievable_return_band ?? null);
let previewBand = $state<AchievableReturnBand | null>(null);  // reserved for A13.2 live preview
const band = $derived(previewBand ?? serverBand);
```

A13 doesn't write to `previewBand` (only A13.2 will), but the slot is reserved so A13.2 wires in without rewriting the dependency graph.

---

## Section C — Frontend: components

Three files, single responsibility each. All under `frontends/wealth/src/lib/components/portfolio/`.

### C.1 `AchievableReturnBandChart.svelte` (presentational)

Props:
```typescript
let {
  band,
  cvarLimit,
  minAchievableCvar,
  height = 220,
}: {
  band: AchievableReturnBand | null;
  cvarLimit: number;
  minAchievableCvar: number | null;
  height?: number;
} = $props();
```

Uses `GenericEChart.svelte` from `frontends/wealth/src/lib/components/charts/GenericEChart.svelte` (already wraps echarts-setup + SVG renderer + resize+dispose). Pass option object derived from `band`.

Option object skeleton (verify against `GenericEChart` API; adjust prop name if different):

```typescript
const tokenColors = {
  // Resolve once on mount — ECharts cannot parse var(--...).
  primary: getComputedStyle(document.documentElement).getPropertyValue("--ii-primary").trim(),
  warning: getComputedStyle(document.documentElement).getPropertyValue("--ii-warning").trim(),
  border: getComputedStyle(document.documentElement).getPropertyValue("--ii-border-subtle").trim(),
};

const chartOptions = $derived.by(() => ({
  grid: { left: 56, right: 16, top: 16, bottom: 36, containLabel: true },
  xAxis: {
    type: "value",
    name: "Tail loss (95% CVaR)",
    nameLocation: "middle",
    nameGap: 24,
    axisLabel: { formatter: (v: number) => formatPercent(v, 1) },
    axisLine: { lineStyle: { color: tokenColors.border } },
  },
  yAxis: {
    type: "value",
    name: "Expected return",
    axisLabel: { formatter: (v: number) => formatPercent(v, 1) },
  },
  series: band ? [
    {
      type: "line",
      showSymbol: true,
      symbolSize: 8,
      data: [[band.lower_at_cvar, band.lower], [band.upper_at_cvar, band.upper]],
      lineStyle: { color: tokenColors.primary, width: 2 },
    },
    {
      type: "line",
      data: [],
      markLine: {
        symbol: "none",
        silent: true,
        lineStyle: { color: tokenColors.warning, type: "dashed" },
        data: [{ xAxis: cvarLimit, label: { formatter: formatPercent(cvarLimit, 2) } }],
      },
    },
    minAchievableCvar !== null ? {
      type: "line",
      data: [],
      markArea: {
        silent: true,
        itemStyle: { color: tokenColors.border, opacity: 0.15 },
        data: [[{ xAxis: 0 }, { xAxis: minAchievableCvar }]],
      },
    } : null,
  ].filter(Boolean) : [],
  tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
}));
```

Empty-band fallback: when `band === null`, render a placeholder div ("Awaiting first construction run") at the same height — do NOT render an empty ECharts container (causes resize jank).

### C.2 `RiskBudgetSlider.svelte` (slider augmentation)

Wraps the existing `CalibrationSliderField` from `frontends/wealth/src/lib/components/portfolio/CalibrationSliderField.svelte:18-55`. Same callback-driven contract (no `$bindable`).

Props:
```typescript
let {
  value,
  profileDefault,
  profile,
  onChange,
}: {
  value: number;
  profileDefault: number;
  profile: string;
  onChange: (v: number) => void;
} = $props();
```

Renders the underlying `CalibrationSliderField` with `min=0.005, max=0.20, step=0.0025, displayFormat="percent", digits=2`. Adds:

1. **Profile-default marker:** small notch on the slider track at `profileDefault`. If `CalibrationSliderField` doesn't support a marker prop, this is the ONE small extension to add to `@netz/ui` — accept a `markers?: Array<{value: number, label?: string}>` prop. Tooltip on hover: `t("risk_budget.profile_default_hint", {profile, value: formatPercent(profileDefault, 2)})`.
2. **"Reset to default" link** (text button, secondary color) below the slider, conditional render: only when `Math.abs(value - profileDefault) > 1e-6`. On click: `onChange(profileDefault)`.
3. **"Custom" badge** in the field header, same conditional. The existing `CalibrationSliderField` already shows a "Custom" badge based on `originalValue` drift (per agent verify) — confirm and reuse; do not duplicate the badge.

Vocabulary (per `metric-translators.ts:269-271` convention — "tail loss" for operator surfaces, "CVaR 95%" reserved for advanced/result chips):
- Field label: `t("risk_budget.label")` → "Tail loss budget" / "Limite de perda de cauda"

### C.3 `RiskBudgetPanel.svelte` (state owner + composition)

Owns the state, composes slider + chart + signal banner. Mounted INSIDE `CalibrationPanel.svelte` REPLACING the existing standalone `cvar_limit` `CalibrationSliderField` row at lines 312-326.

Props:
```typescript
let {
  portfolio,        // includes profile
  calibration,      // current draft (from CalibrationPanel)
  onChange,         // (patch: {cvar_limit: number}) => void  -- pushes into draft
}: {
  portfolio: ModelPortfolio;
  calibration: PortfolioCalibration;
  onChange: (patch: Partial<PortfolioCalibration>) => void;
} = $props();
```

State:
```typescript
import { workspace } from "$lib/state/portfolio-workspace.svelte";

const profileDefault = $derived(defaultCvarForProfile(portfolio.profile));
const cvarLimit = $derived(calibration.cvar_limit);  // owned by parent draft

const serverBand = $derived(workspace.constructionRun?.cascade_telemetry?.achievable_return_band ?? null);
const serverSignal = $derived(workspace.constructionRun?.cascade_telemetry?.operator_signal ?? null);
const minAchievableCvar = $derived(workspace.constructionRun?.cascade_telemetry?.min_achievable_cvar ?? null);

let previewBand = $state<AchievableReturnBand | null>(null);  // RESERVED for A13.2
const band = $derived(previewBand ?? serverBand);

const belowFloor = $derived(serverSignal?.kind === "cvar_limit_below_universe_floor");
const dataMissing = $derived(serverSignal?.kind === "upstream_data_missing");
const polytopeEmpty = $derived(serverSignal?.kind === "constraint_polytope_empty");
```

Helper `defaultCvarForProfile` lives in `frontends/wealth/src/lib/util/profile-defaults.ts` (NEW small file mirroring backend `default_cvar_limit_for_profile` from PR-A12.2):

```typescript
export function defaultCvarForProfile(profile: string | null | undefined): number {
  switch ((profile ?? "").toLowerCase()) {
    case "conservative": return 0.025;
    case "moderate": return 0.05;
    case "growth": return 0.08;
    case "aggressive": return 0.10;
    default: return 0.05;
  }
}
```

Layout:
```svelte
<div class="risk-budget-panel">
  <RiskBudgetSlider
    value={cvarLimit}
    profileDefault={profileDefault}
    profile={portfolio.profile}
    onChange={(v) => onChange({cvar_limit: v})}
  />

  {#if dataMissing}
    <div class="signal-banner signal-banner--empty">
      {t("band.empty_no_history")}
      <button onclick={() => goToUniverseColumn()}>{t("band.open_universe")}</button>
    </div>
  {:else if polytopeEmpty}
    <div class="signal-banner signal-banner--blocking">
      {t("band.polytope_empty")}
    </div>
  {:else}
    <AchievableReturnBandChart
      {band}
      {cvarLimit}
      {minAchievableCvar}
      height={220}
    />
    <div class="band-stats">
      {#if band}
        <div class="band-stats__primary">
          {t("band.at_limit", {return: formatPercent(band.upper, 2)})}
        </div>
        <div class="band-stats__range">
          {t("band.range", {lower: formatPercent(band.lower, 2), upper: formatPercent(band.upper, 2)})}
        </div>
      {:else}
        <div class="band-stats__empty">{t("band.awaiting_first_run")}</div>
      {/if}
    </div>
    {#if belowFloor && minAchievableCvar !== null}
      <div class="signal-banner signal-banner--warning">
        {t("band.below_floor_notice", {
          user_cvar: formatPercent(cvarLimit, 2),
          floor: formatPercent(minAchievableCvar, 2),
        })}
      </div>
    {/if}
  {/if}
</div>
```

CSS classes use `@netz/ui` design tokens — NO hex literals. Per `feedback_layout_cage_pattern.md`, the chart container has fixed pixel height (220px) — do NOT use `height: 100%`.

### C.4 Mount in `CalibrationPanel.svelte`

Replace the existing `<CalibrationSliderField {...cvar_limit_props} />` at lines 312-326 with:

```svelte
<RiskBudgetPanel
  portfolio={portfolio}
  calibration={draft}
  onChange={(patch) => updateDraft(patch)}
/>
```

Verify the Apply button in CalibrationPanel still picks up `draft.cvar_limit` and persists via the existing PUT `/calibration` endpoint. No new persistence path.

### C.5 Result view echo (post-build, top of WeightsTab)

Same `AchievableReturnBandChart` instance renders at the top of `frontends/wealth/src/lib/components/terminal/builder/WeightsTab.svelte` (verify path) — receives the same `band`, `cvarLimit` (from the calibration snapshot embedded in the run), `minAchievableCvar`. Reads from `workspace.constructionRun.cascade_telemetry`.

Add a small annotation below the chart:
- `t("band.realized_within", {value: formatPercent(realized_return, 2)})` if delivered return is in band
- `t("band.realized_below", {value: formatPercent(realized_return, 2)})` otherwise

The same component renders TWICE in the Builder lifecycle: once in calibration (preview/last-run band), once post-build (delivered point overlaid on band). Single visual concept, two contexts.

---

## Section D — Translations

Add to `frontends/wealth/src/lib/i18n/` (verify the existing i18n setup; PT and EN locales required):

| Key | EN | PT |
|---|---|---|
| `risk_budget.label` | Tail loss budget | Limite de perda de cauda |
| `risk_budget.description` | Maximum tail loss (95% confidence) the portfolio may carry. | Perda máxima de cauda (95% de confiança) que o portfólio pode carregar. |
| `risk_budget.profile_default_hint` | Default for {profile}: {value} | Padrão para {profile}: {value} |
| `risk_budget.reset_default` | Reset to {profile} default | Restaurar padrão {profile} |
| `risk_budget.custom_badge` | Custom | Customizado |
| `band.title` | Achievable return band | Faixa de retorno alcançável |
| `band.at_limit` | At your tail loss limit: {return} expected | No seu limite de perda: {return} esperado |
| `band.range` | Achievable range across this universe: {lower} – {upper} | Faixa alcançável neste universo: {lower} – {upper} |
| `band.realized_within` | Delivered: {value} — within band | Entregue: {value} — dentro da faixa |
| `band.realized_below` | Delivered: {value} — below modeled band | Entregue: {value} — abaixo da faixa modelada |
| `band.below_floor_notice` | Your tail loss limit ({user_cvar}) sits below the lowest tail risk this universe can deliver ({floor}). We're showing the lowest-tail-risk portfolio achievable. Loosen the limit or expand the universe. | Seu limite de perda ({user_cvar}) está abaixo do menor risco de cauda que este universo entrega ({floor}). Estamos mostrando a alocação de menor risco de cauda possível. Afrouxe o limite ou amplie o universo. |
| `band.empty_no_history` | We don't have enough return history for this universe to model an achievable range. Add instruments with at least 36 months of NAV, or check the Universe column. | Não há histórico de retornos suficiente neste universo para modelar uma faixa alcançável. Adicione instrumentos com pelo menos 36 meses de NAV, ou revise a coluna Universo. |
| `band.polytope_empty` | The current strategic allocation has no feasible portfolio. Adjust block min/max bounds. | A alocação estratégica atual não tem portfólio viável. Ajuste os limites min/max dos blocos. |
| `band.awaiting_first_run` | Run a construction to see the achievable return band. | Execute uma construção para ver a faixa de retorno alcançável. |
| `band.open_universe` | Open Universe | Abrir Universo |

Use existing translator helper. Existing `metric-translators.ts:237-258` already has `translateOperatorSignalKind` — verify it covers all 4 kinds; extend if `feasible` or others missing.

---

## Section E — Tests

### E.1 Vitest unit tests

`frontends/wealth/src/lib/components/portfolio/__tests__/RiskBudgetPanel.test.ts`:

- `test_initial_state_seeds_from_calibration`: mount with `calibration.cvar_limit=0.025` and `profile="conservative"` → slider shows 2.50%, no Custom badge
- `test_drift_from_default_shows_custom_badge_and_reset`: drag to 0.03 → Custom badge visible, Reset link visible
- `test_reset_returns_to_profile_default`: click Reset → onChange called with profileDefault
- `test_band_renders_when_workspace_has_telemetry`: stub `workspace.constructionRun.cascade_telemetry` with realistic Conservative band → chart renders, stats show 9.84% / 30.62%
- `test_band_empty_state_when_no_run`: workspace has no run → "Run a construction to see..." placeholder
- `test_below_floor_signal_renders_warning_banner`: stub signal with `cvar_limit_below_universe_floor` → warning banner visible, build NOT blocked
- `test_data_missing_signal_replaces_chart`: stub signal with `upstream_data_missing` → chart replaced with empty state + Open Universe CTA
- `test_polytope_empty_signal_blocks`: stub with `constraint_polytope_empty` → blocking banner

### E.2 Vitest unit tests for `defaultCvarForProfile` helper

Mirror the backend tests from PR-A12.2:
- conservative → 0.025
- moderate → 0.05
- growth → 0.08
- aggressive → 0.10
- unknown / null → 0.05
- case-insensitive

### E.3 Playwright smoke

`frontends/wealth/e2e/risk-budget-panel.spec.ts`:

1. Navigate to `/portfolios/{conservative_test_id}/build`
2. Wait for CalibrationPanel to render
3. Locate slider by accessible name "Tail loss budget"
4. Assert slider value is 2.50% (post-A12.2 default)
5. Assert "Default for Conservative: 2.50%" hint visible
6. Drag slider to 5.00%
7. Assert "Custom" badge appears, "Reset to Conservative default" link visible
8. Click Reset
9. Assert slider returns to 2.50%
10. Trigger a build (existing flow), wait for completion
11. Assert chart renders with two data points, vertical marker at 2.50%
12. Assert band stats show "At your tail loss limit: X.XX% expected"
13. Visual regression screenshot for the panel

Per `feedback_visual_validation.md`, this Playwright must pass before claiming done.

---

## Section F — Pass criteria

| # | Criterion | How verified |
|---|---|---|
| 1 | `cascade_telemetry` flows from backend → SSE → workspace → panel | manual + Playwright |
| 2 | Slider initial value matches profile default (post-A12.2) | unit test + Playwright |
| 3 | Reset to default works | unit + Playwright |
| 4 | Chart renders with correct band data on completed runs | unit + Playwright screenshot |
| 5 | Edge cases (below_floor, data_missing, polytope_empty) render correct UX | unit |
| 6 | No `localStorage`, no `EventSource`, no `.toFixed`, no hex literals | grep + ESLint |
| 7 | Layout cage holds — chart container fixed 220px height, parent overflow correct | Playwright screenshot at 3 viewport widths |
| 8 | Two-channel state pattern (`previewBand ?? serverBand`) reserves slot for A13.2 | code review |
| 9 | Result view echo renders at top of WeightsTab post-build | Playwright |
| 10 | Vitest + Playwright + lint + typecheck all green | CI + manual |

Per `feedback_dev_first_ci_later.md`: live-DB Playwright is the merge gate. CI green is not gating.

---

## Section G — Out of scope (explicit)

- Live drag preview (PR-A13.2 — requires backend `POST /preview-cvar` from A13.1)
- Backend `POST /preview-cvar` endpoint (PR-A13.1)
- Profile defaults helper SOURCE OF TRUTH unification (frontend duplicates the mapping; future PR could expose via API)
- Org-level admin UI for editing profile defaults (separate config layer)
- New profiles beyond conservative/moderate/growth/aggressive
- Realized-vs-band variance attribution (just text annotation in C.5; deeper analysis is a separate sprint)
- μ prior calibration (`memory/project_mu_prior_calibration_concern.md` — separate sprint)
- Touching the existing `RiskTab` (which already shows `CVaR 95%` in advanced chips — keep)
- localStorage persistence of slider state (server is source of truth)

---

## Section H — Commit & PR

**Branch:** `feat/pr-a13-static-band-panel`

**Commit message:**

```
feat(wealth): risk budget slider + achievable return band panel (PR-A13)

Wire the cascade_telemetry payload (shipped by PR-A11/A12) into the
Builder UI. Operators now see the achievable return band their CVaR
limit produces, with a chart visualization, edge-case signal banners,
and profile-default reset affordance.

This PR ships the static version: panel reads from the most recent
completed run's telemetry. PR-A13.1 will add a backend POST /preview-cvar
endpoint for live drag preview; PR-A13.2 will wire the frontend debounce.

Components:
- RiskBudgetPanel.svelte (state owner, composes slider + chart + banner)
- RiskBudgetSlider.svelte (CalibrationSliderField wrapper + profile default
  marker + Reset link + Custom badge)
- AchievableReturnBandChart.svelte (svelte-echarts mini scatter-line)

Type extensions:
- New cascade-telemetry.ts with AchievableReturnBand, OperatorSignal,
  CascadeTelemetry, PhaseAttempt
- ConstructionRunPayload extended with cascade_telemetry field
- SSE consumer hydrates telemetry on cascade_telemetry_completed

Two-channel state design (previewBand ?? serverBand) reserves the slot
for A13.2 live preview without requiring a rewrite.

Vocabulary discipline: "Tail loss budget" / "Limite de perda de cauda"
in operator-facing surfaces; "CVaR 95%" reserved for advanced/result
chips per existing translator convention.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

**PR title:** `feat(wealth): risk budget slider + achievable return band panel (PR-A13)`

**PR body:** include the smoke screenshot of the panel rendered with Conservative Preservation's real cascade_telemetry data. Confirm SSE consumer hydrates new field. List the 3 components + type file. Test plan = pass criteria table.

---

## Section I — Anti-patterns to avoid (explicit)

- NO `localStorage` / `sessionStorage` — server is source of truth for `cvar_limit`
- NO `EventSource` — fetch+ReadableStream only
- NO `.toFixed()`, `.toLocaleString()`, inline `Intl.NumberFormat` — ESLint enforced
- NO hex literals in ECharts options — resolve from CSS custom properties via `getComputedStyle`
- NO `$bindable` — callback contract matches CalibrationSliderField
- NO `$effect` writing to `$state` that's an input to the same effect (infinite loop)
- NO firing data fetches from `$derived` — derivations must be pure
- NO new SSE channel — reuse existing construct stream payload
- NO icon-only collapsed sidebar variant (`feedback_shell_architecture.md` — not relevant here but watch if you touch shell)
- NO duplicate "CVaR" jargon in operator slider label — use "tail loss"
- NO chart inside `overflow: hidden` flex parent without explicit pixel height (ECharts cannot resolve `height: 100%` in that context)

---

**End of spec. Execute exactly. Brutal honesty: if `cascade_telemetry` is not flowing into `workspace.constructionRun` after the type+SSE wiring, do NOT proceed to the components — fix the data flow first. The chart with no band is worse than no chart.**
