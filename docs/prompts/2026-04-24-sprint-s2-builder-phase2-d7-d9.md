# Sprint S2-Builder Phase 2 — D7 + D9 Execution Prompt

> **Context:** Phase 1 shipped (PRs #270-#273). D3 CascadeTimeline unification done on branch `feat/builder-cascade-timeline-unification`. D6 (previewCvar wiring) was already implemented in `RiskBudgetPanel.svelte` via PRs A13/A13.2 — SKIP. This prompt covers the two remaining Phase 2 deliverables.
>
> **Branch:** create `feat/builder-phase2-d7-d9` from `main` (after D3 merges).
>
> **PR strategy:** single PR combining D7 + D9.

---

## D7 — `translateOperatorSignalBinding()`

### What

Add a new translator function to `metric-translators.ts` that maps the backend's `operator_signal.binding` string to a human-readable label + tone. This is the last missing translator from the Phase 2 plan.

`translateWinnerSignal()` was shipped in PR #270. `translateCascadePhaseName()` was shipped in D3. This completes the translation surface.

### File

`packages/ii-terminal-core/src/lib/utils/metric-translators.ts`

### Backend binding values

Source: `backend/app/domains/wealth/workers/construction_run_executor.py` lines 574-634.

| `binding` value | `operator_signal.kind` | Human label (PT-BR institutional) |
|---|---|---|
| `"tail_risk_floor"` | `cvar_limit_below_universe_floor` | "Piso de risco de cauda" |
| `"universe_coverage"` | `universe_coverage_insufficient` | "Cobertura do universo" |
| `"returns_quality"` | `upstream_data_missing` | "Qualidade dos retornos" |
| `"block_bands"` | `constraint_polytope_empty` | "Bandas por bloco" |
| `null` | `feasible` | (return `null` — no binding to display) |

### Implementation

```typescript
export function translateOperatorSignalBinding(
    value: string | null | undefined,
): TranslatedMetric | null {
    if (!value) return null;
    switch (value) {
        case "tail_risk_floor":
            return { label: "Piso de risco de cauda", tone: "warning" };
        case "universe_coverage":
            return { label: "Cobertura do universo", tone: "warning" };
        case "returns_quality":
            return { label: "Qualidade dos retornos", tone: "warning" };
        case "block_bands":
            return { label: "Bandas por bloco", tone: "danger" };
        default:
            return { label: value.replace(/_/g, " "), tone: "neutral" };
    }
}
```

### Surface in CascadeTimelineCore

In `packages/ii-terminal-core/src/lib/components/allocation/CascadeTimelineCore.svelte`, add a binding badge next to the operator message when `operatorMessage` is rendered and the parent passes a `signalBinding` prop. Keep it optional — the allocation wrapper doesn't pass it (ProposalReviewPanel doesn't have binding data), only ConstructionCascadeTimeline does.

Add to `ConstructionCascadeTimeline.svelte`:
```typescript
const signalBinding = $derived(telemetry?.operator_signal?.binding ?? null);
```
And pass `{signalBinding}` to `CascadeTimelineCore`.

In CascadeTimelineCore, render the binding badge:
```svelte
{#if signalBinding}
    {@const bindingTranslation = translateOperatorSignalBinding(signalBinding)}
    {#if bindingTranslation}
        <span class="ctc__binding-badge" data-tone={bindingTranslation.tone}>
            {bindingTranslation.label}
        </span>
    {/if}
{/if}
```

Place it inside the `ctc__operator-msg` div, after the body paragraph.

---

## D9 — Race Condition Fixes (RC1 + RC2 + RC5)

### RC1 — RegimeTab `fetchOverlay` stale response race

**File:** `packages/ii-terminal-core/src/lib/components/terminal/builder/RegimeTab.svelte`

**Problem (lines 43-64):** `fetchOverlay()` has no fetchId counter and no AbortController. When the user switches period rapidly (1Y → 3Y → 5Y), three requests fire. If the 3Y response arrives after the 5Y response, the overlay shows stale 3Y data.

**Fix:** Add a private fetchId counter + AbortController. Pattern matches the existing `_generation` counter in `portfolio-workspace.svelte.ts` and the `#fetchId` + `#ctrl` pattern in `workspace-approval.svelte.ts`.

```typescript
// Add at module scope (NOT $state — these are non-reactive):
let overlayFetchId = 0;
let overlayCtrl: AbortController | null = null;

async function fetchOverlay() {
    overlayCtrl?.abort();
    const ctrl = new AbortController();
    overlayCtrl = ctrl;
    const id = ++overlayFetchId;
    loading = true;
    try {
        const res = await api.get(
            `/allocation/regime-overlay?period=${period}`,
            { signal: ctrl.signal },
        );
        if (id !== overlayFetchId) return;
        overlay = res as RegimeOverlay;
    } catch (e) {
        if (ctrl.signal.aborted) return;
        console.error("Failed to fetch regime overlay", e);
        if (id !== overlayFetchId) return;
        overlay = null;
    } finally {
        if (id === overlayFetchId) loading = false;
    }
}
```

**Note:** Check if `api.get()` accepts a `{ signal }` option. If not, the AbortController alone suffices for cancellation — the fetchId counter prevents stale writes regardless.

### RC5 — RegimeTab async IIFE without cleanup

**File:** `packages/ii-terminal-core/src/lib/components/terminal/builder/RegimeTab.svelte`

**Problem (lines 77-86):** The `$effect` that fetches `/allocation/regime` uses an async IIFE without any cleanup. If the component unmounts mid-flight, the response writes to `currentRegime` on a dead component (no crash in Svelte 5, but unnecessary work and potential flash on remount).

**Fix:** Add the same fetchId + AbortController pattern:

```typescript
let regimeFetchId = 0;
let regimeCtrl: AbortController | null = null;

$effect(() => {
    regimeCtrl?.abort();
    const ctrl = new AbortController();
    regimeCtrl = ctrl;
    const id = ++regimeFetchId;
    (async () => {
        try {
            const res = await api.get("/allocation/regime", { signal: ctrl.signal });
            if (id !== regimeFetchId) return;
            currentRegime = res as GlobalRegime;
        } catch {
            if (ctrl.signal.aborted) return;
            if (id !== regimeFetchId) return;
            currentRegime = null;
        }
    })();
    return () => ctrl.abort();
});
```

The `return () => ctrl.abort()` is the Svelte 5 `$effect` cleanup — runs when the effect re-fires or when the component unmounts.

### RC2 — `fetchRunDiff` stale response race

**File:** `packages/ii-terminal-core/src/lib/state/portfolio-workspace.svelte.ts`

**Problem (line 2176):** `fetchRunDiff(runId)` uses `_generation` for staleness, which tracks portfolio switches. But two rapid builds on the **same portfolio** (generation unchanged) can produce stale diffs — if run1's diff response arrives after run2's.

**Fix:** Add a dedicated `_diffFetchId` counter (private non-reactive class field):

```typescript
// Add to class fields (near line 535, alongside _generation):
private _diffFetchId = 0;
```

Then in `fetchRunDiff`:

```typescript
async fetchRunDiff(runId: string) {
    if (!this._getToken || !this.portfolioId) return;
    const gen = this._generation;
    const fetchId = ++this._diffFetchId;
    this.isLoadingDiff = true;

    try {
        const api = this.api();
        const result = await api.get<ConstructionRunDiff>(
            `/model-portfolios/${this.portfolioId}/construction/runs/${runId}/diff`,
        );
        if (gen !== this._generation || fetchId !== this._diffFetchId) return;
        this.runDiff = result;
    } catch {
        if (gen !== this._generation || fetchId !== this._diffFetchId) return;
        this.runDiff = null;
    } finally {
        if (gen === this._generation && fetchId === this._diffFetchId) {
            this.isLoadingDiff = false;
        }
    }
}
```

### IMPORTANT: wealth frontend parity

The workspace file exists in TWO locations (known debt from X1-X7 extraction):
1. `packages/ii-terminal-core/src/lib/state/portfolio-workspace.svelte.ts` (primary)
2. `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` (wealth copy)

Apply RC2 to **both** files. The RegimeTab (RC1 + RC5) exists in:
1. `packages/ii-terminal-core/src/lib/components/terminal/builder/RegimeTab.svelte` (primary)
2. `frontends/wealth/src/lib/components/terminal/builder/RegimeTab.svelte` (wealth copy)

Apply RC1 + RC5 to **both** files. Verify both with `npx svelte-check`.

---

## Acceptance Criteria

- [ ] `translateOperatorSignalBinding()` exported from `metric-translators.ts` with 5 binding values mapped
- [ ] CascadeTimelineCore renders binding badge when `signalBinding` prop is provided
- [ ] ConstructionCascadeTimeline passes `signalBinding` from telemetry
- [ ] RegimeTab `fetchOverlay` uses fetchId + AbortController — rapid period switching produces no stale renders
- [ ] RegimeTab `/allocation/regime` IIFE has `$effect` cleanup that aborts on unmount
- [ ] `fetchRunDiff` has dedicated `_diffFetchId` counter — same-portfolio rapid builds don't contaminate
- [ ] Both `ii-terminal-core` AND `frontends/wealth` copies patched for RC1, RC2, RC5
- [ ] `npx svelte-check` passes with 0 errors on: ii-terminal-core, terminal, wealth
- [ ] No new `$state` for fetchId counters (use plain `let` or private class fields — non-reactive)

## Files to modify (complete list)

| File | Changes |
|---|---|
| `packages/ii-terminal-core/src/lib/utils/metric-translators.ts` | Add `translateOperatorSignalBinding()` |
| `packages/ii-terminal-core/src/lib/components/allocation/CascadeTimelineCore.svelte` | Add optional `signalBinding` prop + badge render |
| `packages/ii-terminal-core/src/lib/components/allocation/ConstructionCascadeTimeline.svelte` | Pass `signalBinding` from telemetry |
| `packages/ii-terminal-core/src/lib/components/terminal/builder/RegimeTab.svelte` | RC1 + RC5 |
| `packages/ii-terminal-core/src/lib/state/portfolio-workspace.svelte.ts` | RC2 `_diffFetchId` |
| `frontends/wealth/src/lib/components/terminal/builder/RegimeTab.svelte` | RC1 + RC5 (wealth copy) |
| `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` | RC2 `_diffFetchId` (wealth copy) |
