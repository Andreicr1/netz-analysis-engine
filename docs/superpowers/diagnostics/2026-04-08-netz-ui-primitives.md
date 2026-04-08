# `@investintell/ui` FCL Primitives Availability — 2026-04-08

> **Source:** Phase 0 Task 0.3 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.
> **Purpose:** Confirm the Discovery FCL primitives are available in the design-system package before Phase 4 (Builder UI), Phase 6 (Analytics), Phase 8 (Live shell), and Phase 9 (Live data) consume them. Adjust the plan's package name where it drifted.
> **Headline:** the package the plan called `@netz/ui` is actually **`@investintell/ui`**. Globally renamed across the plan (27 references). 4 of 7 primitives are available, 2 are wealth-local needing promotion, 1 does not exist anywhere.

---

## Two-package world

The repository has TWO design-system packages — both legitimate, both used today:

| Package | Path | Role | Aliased as |
|---|---|---|---|
| `@netz/ui` | `packages/ui/` | Older "Tailwind tokens, shadcn-svelte, layouts" set per CLAUDE.md line 90. Has `Button`, `Card`, `DataTable`, `AppShell`, etc. — but **not** the FCL/runtime primitives. | `@netz/ui` |
| `@investintell/ui` | `packages/investintell-ui/` | Newer "InvestIntell Design System — shadcn-svelte + Urbanist + analytical components" per `package.json`. **All FCL primitives, runtime guardrails, EnterpriseTable, charts setup, and formatters live here.** | `@investintell/ui` (with subpaths `/runtime`, `/charts`, `/charts/echarts-setup`, `/components/ui/*`, `/utils`) |

The portfolio plan drafts called the package `@netz/ui` (matching CLAUDE.md line 90 and 174). Reality at HEAD is that **all wealth code imports from `@investintell/ui`** — verified by grep across `frontends/wealth/src/lib/components/portfolio/`:

```
BuilderColumn.svelte:25:    import { PanelErrorState } from "@investintell/ui/runtime";
BuilderColumn.svelte:26:    import { formatPercent } from "@investintell/ui";
AnalyticsColumn.svelte:25:  import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
RebalanceSimulationPanel.svelte:9:  import { Button } from "@investintell/ui/components/ui/button";
RebalanceSimulationPanel.svelte:11: import { EmptyState, formatCurrency, formatPercent } from "@investintell/ui";
MainPortfolioChart.svelte:7:    import { ChartContainer } from "@investintell/ui/charts";
MainPortfolioChart.svelte:8:    import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
StressTestPanel.svelte:8:    import { Button } from "@investintell/ui/components/ui/button";
StressTestPanel.svelte:10:   import { ChartContainer } from "@investintell/ui/charts";
```

**Action taken:** The portfolio plan was patched globally — `@netz/ui` → `@investintell/ui` (27 replacements). The plan now matches the import surface of the wealth code.

CLAUDE.md (line 90, 162, 174) still references `@netz/ui` for formatters and shared imports. **NOT touched in this diagnostic** (out of scope) — flag for a future CLAUDE.md cleanup PR.

---

## Per-primitive verification

| # | Primitive | Plan said | Actual location | Status |
|---|---|---|---|---|
| 1 | `FlexibleColumnLayout` | `@netz/ui` (promoted from Discovery 2.2) | `packages/investintell-ui/src/lib/layouts/FlexibleColumnLayout.svelte` (with `.test.ts`) | **AVAILABLE** at `@investintell/ui` |
| 2 | `EnterpriseTable` | `@netz/ui` (extracted from `UniverseTable.svelte` in Discovery 2.3) | `packages/investintell-ui/src/lib/table/EnterpriseTable.svelte` (with `.test.ts`) | **AVAILABLE** at `@investintell/ui` |
| 3 | `FilterRail` | `@netz/ui` | `packages/investintell-ui/src/lib/layouts/FilterRail.svelte` | **AVAILABLE** at `@investintell/ui` |
| 4 | `PanelErrorState` | `@netz/ui/runtime` | `packages/investintell-ui/src/lib/components/analytical/PanelErrorState.svelte`, re-exported via `packages/investintell-ui/src/lib/runtime/index.ts:45` | **AVAILABLE** at `@investintell/ui/runtime` |
| 5 | `ChartCard` | `@netz/ui` | `frontends/wealth/src/lib/components/discovery/analysis/ChartCard.svelte` | **WEALTH-LOCAL — needs promotion** |
| 6 | `AnalysisGrid` | `@netz/ui` | `frontends/wealth/src/lib/components/discovery/analysis/AnalysisGrid.svelte` | **WEALTH-LOCAL — needs promotion** |
| 7 | `BottomTabDock` | `@netz/ui` | (does not exist anywhere) | **MISSING — must be created** |
| 8 | `WorkbenchLayout` | `@netz/ui` (NEW — created in Phase 8) | (does not exist anywhere) | **MISSING — Phase 8 Task 8.1 creates it (matches plan expectation)** |

### Bonus discovery — `createTickBuffer` is already available

Phase 9 Task 9.2 was specced as "create `createTickBuffer<T>` helper". Reality:

```
packages/investintell-ui/src/lib/runtime/index.ts:22-26
export {
    createTickBuffer,
    type TickBuffer,
    type TickBufferConfig,
} from "./tick-buffer.svelte";
```

`createTickBuffer` already exists at `@investintell/ui/runtime/tick-buffer.svelte.ts`, fully tested under `runtime/__tests__/tick-buffer.test.ts`. **Phase 9 Task 9.2 should `import` it, not create it.** This collapses the task to just wiring the SSE → buffer → state path.

Same applies to `MountedGuard` / `createMountedGuard` (listener-safety primitive used in DL10 SVG sparklines and DL15 SSE bridges) — already at `@investintell/ui/runtime`.

---

## Verification commands (re-runnable)

```bash
# Are the 4 expected primitives at @investintell/ui?
find packages/investintell-ui/src/lib -iname "*flexible*" -o -iname "*enterprisetable*" \
    -o -iname "*filterrail*" -o -iname "*panelerrorstate*"

# Is the runtime barrel exporting tick buffer + panel error state?
cat packages/investintell-ui/src/lib/runtime/index.ts

# Is BottomTabDock or WorkbenchLayout anywhere?
find packages frontends -iname "*tabdock*" -o -iname "*workbench*"

# Where is ChartCard / AnalysisGrid?
find packages frontends -iname "ChartCard.svelte" -o -iname "AnalysisGrid.svelte"
```

---

## Gaps that block downstream phases

### Gap 1 — `BottomTabDock` does not exist

**Blocks:** Phase 6 Task 6.5 (`Mount BottomTabDock from @investintell/ui` for Analytics) and Phase 8 Task 8.3 (Live workbench secondary nav).

**Required action before Phase 6 starts:** Create `packages/investintell-ui/src/lib/layouts/BottomTabDock.svelte` with the contract from portfolio-enterprise-ux-flow.md §8.2:
- Bind to URL hash (`#tabs=<base64>`) — never `localStorage` (DL15)
- Persists open tabs as `[{id, label, route, scope}]` arrays
- Supports drag-to-reorder, close button per tab, "+" button to open new tab
- Scope-aware: tabs from `/portfolio/*` don't appear in `/discovery/*` and vice versa

**Recommendation:** Add this as a new pre-Phase-6 task (Task 6.0 — `BottomTabDock primitive`) or fold it into Phase 4 Task 4.0 as part of "primitive prep". A Phase 0 patch is NOT recommended — Phase 0 is read-only diagnostic and should not gain new code-writing tasks.

### Gap 2 — `ChartCard` and `AnalysisGrid` are wealth-local, not promoted

**Blocks:** Phase 6 Task 6.3 (`portfolio-specific charts in 3×2 grid using ChartCard + AnalysisGrid`).

**Required action before Phase 6 starts:** Promote both files from `frontends/wealth/src/lib/components/discovery/analysis/` to `packages/investintell-ui/src/lib/components/analytical/` (or `layouts/` for `AnalysisGrid`), update Discovery's imports to consume them from the package, and add them to the `@investintell/ui` barrel `index.ts`. This is a small refactor — both files are pure presentational components and have no wealth-specific business logic.

**Recommendation:** Add as Phase 6 Task 6.0 (or Phase 4 Task 4.0 if Phase 4 also consumes them — verify by re-reading Phase 4 task references). Same caveat as Gap 1: Phase 0 is read-only.

### Gap 3 — `@netz/ui` references in plan

**Blocks:** nothing functionally — the plan was already patched globally `@netz/ui` → `@investintell/ui` (27 replacements). Future executors will read the corrected plan.

**Note for CLAUDE.md cleanup PR:** Lines 90, 162, and 174 still cite `@netz/ui` — they should be updated to reflect that wealth + portfolio + discovery code uses `@investintell/ui`. Out of scope for this diagnostic.

---

## Disposition

**Phase 4 / Phase 6 / Phase 8 are NOT yet safe to start** until Gaps 1 and 2 are closed. They require ~1-2 hours of frontend refactor each.

**Phase 1 / Phase 2 / Phase 3 ARE safe to start** — they are pure backend (DB schema, validation gate, narrative templater, advisor fold-in, worker creation). Zero frontend dependency.

**Phase 0 gate:** GREEN, with the explicit caveat that Phase 4 / 6 / 8 inherit two prerequisite primitive tasks (BottomTabDock creation, ChartCard/AnalysisGrid promotion) that must complete before they begin. The diagnostic flags this; the executor should add the prerequisite tasks at the head of the appropriate phase before consuming downstream tasks.

The plan globally now uses `@investintell/ui` everywhere — no manual translation needed by future executors.
