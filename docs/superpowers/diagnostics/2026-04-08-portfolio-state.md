# Portfolio MOCK/REAL State Diagnostic — 2026-04-08

> **Source:** Phase 0 Task 0.1 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.
> **Purpose:** Verify the architectural smells documented in `docs/superpowers/plans/drafts/portfolio-enterprise-components.md` Part A.2 against the live branch (`feat/discovery-fcl`) before Phase 4 consumes them. Each item is classified `CONFIRMED`, `DRIFTED`, or `RESOLVED`.

## Summary

| # | Verification | Status | Phase that consumes |
|---|---|---|---|
| 1 | `PolicyPanel.svelte` is a literal no-op | **CONFIRMED (drifted line numbers)** | Phase 4 Task 4.2, Phase 5 Task 5.4 |
| 2 | "New Portfolio" button has no `onclick` | **CONFIRMED** | Phase 5 Task 5.3 |
| 3 | `StressTestPanel` always sends `scenario_name: "custom"` | **CONFIRMED** | Phase 4 Task 4.4 |
| 4 | `construction_advisor.py` exists at 789 lines, wired to `/construction-advice` | **CONFIRMED** | Phase 3 Task 3.3 |
| 5 | `PRESET_SCENARIOS` contains the 4 canonical keys | **CONFIRMED** | Phase 3 Task 3.5 |
| 6 | `/construct` returns 8 numeric fields with zero narrative | **CONFIRMED** | Phase 3 Tasks 3.1–3.7 |
| 7 | Frontend formatter violations baseline | **CONFIRMED + 1 NEW** | Phase 10 Task 10.2 |

---

## 1. PolicyPanel no-op — CONFIRMED (line numbers drifted)

**Original claim (components draft A.2):** `portfolio-workspace.svelte.ts:684-688` — `updatePolicy()` body just spreads `this.portfolio` with no fetch or mutation.

**Actual state at HEAD:**

`frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts:684-687`:

```ts
updatePolicy(key: "cvar_limit" | "max_single_fund_weight", value: number) {
    if (!this.portfolio) return;
    // Policy updates are local UI state — the backend reads policy from StrategicAllocation table
    this.portfolio = { ...this.portfolio };
}
```

The function:

1. Receives the slider value but never assigns it to `this.portfolio[key]`.
2. Spreads the existing object — guaranteeing `$state` reactivity fires once but the value never propagates.
3. Has zero `fetch`, `apiCall`, or `await` — no backend mutation.
4. The inline comment ("backend reads from StrategicAllocation table") is the smoking gun: it documents the no-op.

The PolicyPanel binds the slider change handlers at lines 15 and 22:

```svelte
function handleCvarChange(e: Event) {
    workspace.updatePolicy("cvar_limit", val);
}
// ... similar for max_single_fund_weight
```

**Drift note:** the components draft cited lines 684-688; actual file has the body at 684-687 (one line shorter). Phase 4 Task 4.2 and Phase 5 Task 5.4 should re-grep before patching.

**Resolution path:** Phase 4 Task 4.1/4.2 (`CalibrationPanel`) replaces the slider entirely; Phase 5 Task 5.4 deletes `PolicyPanel.svelte` and the `updatePolicy` method together.

---

## 2. "New Portfolio" button stub — CONFIRMED

**Original claim:** `frontends/wealth/src/routes/(app)/portfolio/+page.svelte:115-118` button has no `onclick`.

**Actual state at HEAD** (lines 114-118):

```svelte
<div class="bld-left-header">
    <button type="button" class="bld-pill bld-pill--new">
        <Plus size={16} />
        <span>New Portfolio</span>
    </button>
</div>
```

No `onclick`, no `on:click`, no `bind:`, no event delegation upstream. Pure dead UI element. The supporting CSS at lines 204+ confirms it's a properly-styled pill — the dead state was the first behavior shipped.

**Resolution path:** Phase 5 Task 5.3 (`NewPortfolioDialog.svelte`) attaches the click handler that opens the dialog.

---

## 3. StressTestPanel always sends `scenario_name: "custom"` — CONFIRMED

**Original claim:** `portfolio-workspace.svelte.ts` `runStressTest` always dispatches `scenario_name: "custom"`.

**Actual state at HEAD** (`portfolio-workspace.svelte.ts:842-846`):

```ts
const body: ParametricStressRequest = {
    scenario_name: "custom",
    shocks: blockShocks,
};
```

The string literal `"custom"` is hardcoded — no parameter, no preset selector, no enum. The panel UI in `StressTestPanel.svelte:23` calls `workspace.runStressTest({...})` with shock inputs only. The 4 backend presets (`gfc_2008`, `covid_2020`, `taper_2013`, `rate_shock_200bps`) are unreachable from the UI.

The result handler at line 856 reads `result.scenario_name` back, but since the request was always `custom`, the response will always echo `custom`.

**Resolution path:** Phase 3 Task 3.5 ships `GET /portfolio/stress-test/scenarios` (catalog endpoint). Phase 4 Task 4.4 builds `StressScenarioPanel.svelte` with two tabs (Matrix + Custom — OD-8 locked). The Matrix tab dispatches one of the 4 preset names; Custom keeps the inline shock body.

---

## 4. `construction_advisor.py` — CONFIRMED

**Original claim:** `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py` exists at 789 lines, wired to `POST /model-portfolios/{id}/construction-advice` at approximately line 563.

**Actual state at HEAD:**

```
$ wc -l backend/vertical_engines/wealth/model_portfolio/construction_advisor.py
789 backend/vertical_engines/wealth/model_portfolio/construction_advisor.py
```

Exactly 789 lines — matches. The route is mounted at `backend/app/domains/wealth/routes/model_portfolios.py:567` (`"/{portfolio_id}/construction-advice"`) — 4 lines off from the draft's "approximately 563" estimate, well within tolerance.

**Resolution path:** Phase 3 Task 3.3 keeps the standalone endpoint alive (per quant draft §C.2 — needed for what-if re-runs with different scoring weights) AND folds the same advisor call into `_run_construction_async`, embedding the result as `response.advisor`.

---

## 5. `PRESET_SCENARIOS` catalog — CONFIRMED

**Original claim:** `backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py` contains a `PRESET_SCENARIOS` dict with the 4 canonical keys.

**Actual state at HEAD** — the dict is declared at line 129:

```python
PRESET_SCENARIOS: dict[str, dict[str, float]] = {
    "gfc_2008": {        # line 130
        "na_equity_large": -0.38,
        ...
    },
    "covid_2020": {      # line 141
        ...
    },
    "taper_2013": {      # line 152
        ...
    },
    "rate_shock_200bps": # line 163
        ...
    },
}
```

All 4 keys present at lines 130, 141, 152, 163. File is 319 lines total. Backend is fully ready — the gap is purely frontend (Task 0.1 verification #3).

**Resolution path:** Phase 3 Task 3.5 exposes this dict via `GET /portfolio/stress-test/scenarios` returning a `StressScenarioCatalog` schema.

---

## 6. `/construct` response shape — CONFIRMED (8 fields, zero narrative)

**Original claim:** `model_portfolios.py:1553-1562` embeds `result["optimization"]` with 8 numeric fields and no narrative.

**Actual state at HEAD** (`backend/app/domains/wealth/routes/model_portfolios.py:1556-1565`):

```python
if composition.optimization:
    result["optimization"] = {
        "expected_return": composition.optimization.expected_return,
        "portfolio_volatility": composition.optimization.portfolio_volatility,
        "sharpe_ratio": composition.optimization.sharpe_ratio,
        "solver": composition.optimization.solver,
        "status": composition.optimization.status,
        "cvar_95": composition.optimization.cvar_95,
        "cvar_limit": composition.optimization.cvar_limit,
        "cvar_within_limit": composition.optimization.cvar_within_limit,
    }
```

Exactly 8 fields. Lines 1574-1576 *do* attach `factor_exposures` best-effort under `result["optimization"]["factor_exposures"]` — that's a partial enrichment beyond the draft claim, but still numeric, still no narrative, still no advisor.

**Drift note:** components draft cited 1553-1562; actual is 1556-1565. Phase 3 Task 3.7 (E2E smoke) should re-anchor against `result["optimization"] = {`.

**Resolution path:** Phase 3 Task 3.1 (`validation_gate.py`), 3.2 (Jinja2 templater), 3.3 (advisor fold-in), 3.4 (`construction_run_executor` worker writing `portfolio_construction_runs`) collectively replace this dict with the full `ConstructionRunResponse` per quant draft §B.2.

---

## 7. Formatter violations — CONFIRMED + 1 NEW

**Original baseline (components draft Part F.1):**
- `RebalanceSimulationPanel.svelte:259, 265, 290`
- `BuilderTable.svelte:233`
- `portfolio/analytics/+page.svelte:60-61`

**Actual state at HEAD:**

| File | Line | Pattern | Status |
|---|---|---|---|
| `frontends/wealth/src/lib/components/portfolio/RebalanceSimulationPanel.svelte` | 259 | `(trade.delta_weight * 100).toFixed(1)` | CONFIRMED |
| `frontends/wealth/src/lib/components/portfolio/RebalanceSimulationPanel.svelte` | 265 | `trade.estimated_quantity.toFixed(2)` | CONFIRMED |
| `frontends/wealth/src/lib/components/portfolio/RebalanceSimulationPanel.svelte` | 290 | `wc.delta_pp.toFixed(1)` | CONFIRMED |
| `frontends/wealth/src/lib/components/portfolio/BuilderTable.svelte` | 233 | `value.toFixed(0)` | CONFIRMED |
| `frontends/wealth/src/routes/(app)/portfolio/analytics/+page.svelte` | 60 | `+(s.allocation_effect * 10000).toFixed(1)` | CONFIRMED |
| `frontends/wealth/src/routes/(app)/portfolio/analytics/+page.svelte` | 61 | `+(s.selection_effect * 10000).toFixed(1)` | CONFIRMED |
| `frontends/wealth/src/routes/(app)/portfolio/analytics/+page.svelte` | 155 | `${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}` | **NEW — not in baseline** |

**`toLocaleString` / `Intl.*` scan:** zero matches under `frontends/wealth/src/**/portfolio/**`. Clean.

**Drift impact:** Phase 10 Task 10.2 must add `portfolio/analytics/+page.svelte:155` to its sweep list. Total violations to fix: **7 lines across 3 files** (was 6 across 3 files in the draft).

**Resolution path:** Phase 10 Task 10.2 replaces every `.toFixed()` call with the appropriate `@netz/ui` formatter (`formatPercent`, `formatBps`, `formatNumber`) — the line 155 case is an ECharts tooltip formatter and will need the `formatBps` helper specifically since the multiplied-by-10000 pattern at lines 60-61 confirms this is a basis-point chart.

---

## Verification commands (re-runnable)

For Phase 4 / Phase 5 / Phase 10 to re-verify if too much time has passed:

```bash
rg -n "updatePolicy" frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts
rg -n "handleCvarChange|updatePolicy" frontends/wealth/src/lib/components/portfolio/PolicyPanel.svelte
rg -n "New Portfolio" "frontends/wealth/src/routes/(app)/portfolio/+page.svelte"
rg -n "scenario_name" frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts
rg -n "runStressTest" frontends/wealth/src/lib/components/portfolio/StressTestPanel.svelte
rg -n "PRESET_SCENARIOS" backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py
wc -l backend/vertical_engines/wealth/model_portfolio/construction_advisor.py
rg -n "construction-advice" backend/app/domains/wealth/routes/model_portfolios.py
rg -n "result\[.optimization.\]" backend/app/domains/wealth/routes/model_portfolios.py
rg -n "\.toFixed\(" "frontends/wealth/src/lib/components/portfolio" "frontends/wealth/src/routes/(app)/portfolio"
rg -n "toLocaleString\(|Intl\." "frontends/wealth/src/lib/components/portfolio"
```

## Disposition

All 7 verifications complete. Phase 0 Task 0.1 gate cleared. The plan is anchored against reality — Phase 4 and Phase 10 should re-grep for line numbers but the architectural assertions hold.
