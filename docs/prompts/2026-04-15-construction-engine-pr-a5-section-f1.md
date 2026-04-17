# Construction Engine PR-A5 — Section F.1 Sub-Spec

**Date:** 2026-04-15
**Executor:** Opus 4.6 (1M context)
**Branch:** continue on `feat/construction-engine-pr-a5-frontend-migration` (current HEAD: `8478fad6`)
**Scope:** REPLACEMENT for Section F (the original "audit + commit 124 uncommitted lines" was a no-op because the lines were destroyed by an upstream session reset; reimplement the feature from scratch).

## Why this exists

When the user's previous Gemini session was running in parallel, the working tree contained 124 uncommitted lines adding an `originalValue` overlay to `CalibrationPanel.svelte` and its 4 child components. During PR-A4 verification, the verifying session ran `git reset --hard origin/main` to resolve a divergent post-squash-merge state, silently discarding the working tree without `git stash -u`. `git fsck --lost-found` confirms zero recoverable blobs. Reimplement.

## Feature semantics

The Builder right-rail `CalibrationPanel` holds a local `draft` of the calibration that the PM is editing. Today, only `dirty` (boolean) tells the PM that something changed. After F.1, every individual field shows **what its persisted value was at the time of the most recent construction run**, so the PM can see the delta inline without comparing against a separate Compare-with-Last-Run view.

UX phrasing in the field: a small chip next to the field label that reads e.g. `Anteriormente: 5,00%` (institutional formatter) when `draft.X !== snapshot.X`. When equal (or snapshot absent), no chip. No tooltip required.

Source of truth for "previous": `workspace.constructionRun.calibration_snapshot` — the JSONB column persisted by `execute_construction_run` for every successful run. Type today is `Record<string, unknown> | null` (`portfolio-workspace.svelte.ts:60`). Loose typing is intentional (snapshot evolves with calibration schema); F.1 reads only known keys with safe casts.

This is **non-blocking UX polish**. It does not gate Apply. It does not change persistence. It does not call the backend.

---

## Section A — Mandates (non-negotiable)

1. **Read-only consumption of `constructionRun.calibration_snapshot`** — never mutate.
2. **Formatter discipline** (DL16) — every value rendered in the chip uses `@investintell/ui` formatters (`formatPercent`, `formatNumber`, `formatBps`, etc.), matching the field's `displayFormat`. Zero `.toFixed()`, zero `Intl.*` inline.
3. **Smart-backend / dumb-frontend** — the chip label is verbatim Portuguese institutional copy (`Anteriormente: …`); never expose JSON keys (`stress_scenarios_active`, `cvar_limit`) as labels.
4. **Svelte 5 runes only** — `$props`, `$derived`, `$state`. No `$:`, no stores beyond what already exists.
5. **No new dependencies.**
6. **No CSS file moves** — extend the existing `<style>` blocks of each child component with one new class (`*-original-chip`); do not introduce a separate CSS module.
7. **Preserve `value` + `onChange` API** of the 4 child components — add `originalValue` as **optional** prop (`originalValue?: T`). Default `undefined` → no chip, no behavioural change. Backward compatible with every other consumer.
8. **No Tailwind classes inside child components** — they use scoped `<style>` (`.cs[fglt]-*` BEM-ish prefixes); the chip class follows the same prefix.
9. **No localStorage / sessionStorage** (DL15) — chip state is purely derived from `workspace.constructionRun`.
10. **Do not touch `CalibrationPanel.svelte` script section beyond adding the `snapshot` derived** — every other change is in the markup (passing `originalValue={snapshot?.X}` per field).

---

## Section B — Patches (granular, file:line)

### B.1 — `CalibrationSelectField.svelte`

File: `frontends/wealth/src/lib/components/portfolio/CalibrationSelectField.svelte`

In the `Props` interface (currently lines 17-25), add:

```ts
originalValue?: string;
```

In the `let { ... }: Props = $props();` destructuring (currently lines 27-36), add `originalValue` to the list (no default).

In the script, add a `$derived`:

```ts
const showOriginal = $derived(
  originalValue !== undefined && originalValue !== value
);
const originalLabel = $derived(
  showOriginal
    ? options.find((o) => o.value === originalValue)?.label ?? originalValue
    : null
);
```

In the markup, immediately AFTER the existing `<label class="csf-label" for={id}>{label}</label>` line inside `<div class="csf-header">`, add:

```svelte
{#if showOriginal && originalLabel !== null}
  <span class="csf-original-chip" title="Valor da última construção">
    Anteriormente: {originalLabel}
  </span>
{/if}
```

In the `<style>` block, add at the end:

```css
.csf-original-chip {
  margin-left: 8px;
  padding: 2px 6px;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--terminal-fg-muted);
  background: var(--terminal-bg-subtle);
  border: 1px solid var(--terminal-border-subtle);
  border-radius: 2px;
  font-family: var(--terminal-font-mono);
  white-space: nowrap;
}
```

### B.2 — `CalibrationSliderField.svelte`

File: `frontends/wealth/src/lib/components/portfolio/CalibrationSliderField.svelte`

In `Props` (currently lines 23-37), add:

```ts
originalValue?: number;
```

In destructuring (currently lines 39-51), add `originalValue` (no default).

In the script, add a derived chip-formatter that mirrors the field's own `displayFormat`. The component already imports `formatPercent`, `formatNumber`, `formatBps` from `@investintell/ui` (line 20). Add:

```ts
const showOriginal = $derived(
  originalValue !== undefined && originalValue !== value
);
const originalDisplay = $derived.by(() => {
  if (!showOriginal || originalValue === undefined) return null;
  switch (displayFormat) {
    case "percent":
      return formatPercent(originalValue, digits ?? 2);
    case "bps":
      return formatBps(originalValue);
    case "x":
      return `${formatNumber(originalValue, digits ?? 2)}x`;
    case "raw":
    default:
      return formatNumber(originalValue, digits ?? 0);
  }
});
```

The slider's existing inline value chip is rendered in the header next to `{label}`. Find that header (search for `class="csl-header"` or equivalent — confirm exact class via Read before editing). Append the `csl-original-chip` AFTER the existing inline value chip:

```svelte
{#if showOriginal && originalDisplay !== null}
  <span class="csl-original-chip" title="Valor da última construção">
    Anteriormente: {originalDisplay}
  </span>
{/if}
```

CSS at end of `<style>` (use the actual prefix the file uses — likely `.csl-`):

```css
.csl-original-chip {
  margin-left: 8px;
  padding: 2px 6px;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--terminal-fg-muted);
  background: var(--terminal-bg-subtle);
  border: 1px solid var(--terminal-border-subtle);
  border-radius: 2px;
  font-family: var(--terminal-font-mono);
  white-space: nowrap;
}
```

### B.3 — `CalibrationToggleField.svelte`

File: `frontends/wealth/src/lib/components/portfolio/CalibrationToggleField.svelte`

In `Props` (currently lines 8-15), add:

```ts
originalValue?: boolean;
```

Add `originalValue` to destructuring.

Script:

```ts
const showOriginal = $derived(
  originalValue !== undefined && originalValue !== value
);
const originalLabel = $derived(
  showOriginal ? (originalValue ? "Ativado" : "Desativado") : null
);
```

In markup, append AFTER the existing `<label class="ctf-label" for={id}>{label}</label>` inside `<div class="ctf-header">`:

```svelte
{#if showOriginal && originalLabel !== null}
  <span class="ctf-original-chip" title="Valor da última construção">
    Anteriormente: {originalLabel}
  </span>
{/if}
```

CSS — same body, prefix `.ctf-original-chip`.

### B.4 — `CalibrationScenarioGroup.svelte`

File: `frontends/wealth/src/lib/components/portfolio/CalibrationScenarioGroup.svelte`

This is the only field that holds an array (`StressScenarioId[]`). The diff is **set-based**, not order-sensitive.

In `Props` (currently lines 17-23), add:

```ts
originalValue?: readonly StressScenarioId[];
```

Add `originalValue` to destructuring.

Script:

```ts
const originalSet = $derived(originalValue ? new Set(originalValue) : null);
const draftSet = $derived(new Set(value));

const added = $derived.by(() =>
  originalSet
    ? value.filter((v) => !originalSet.has(v))
    : []
);
const removed = $derived.by(() =>
  originalSet
    ? [...originalSet].filter((v) => !draftSet.has(v))
    : []
);
const showOriginal = $derived(
  originalValue !== undefined && (added.length > 0 || removed.length > 0)
);
```

In markup, render TWO chips when `showOriginal` (one for additions in green-ish neutral, one for removals in muted red — both still subtle). Find `<div class="csg-header">` (currently around line 45) and insert AFTER the existing `<span class="csg-count">{value.length}/{options.length}</span>`:

```svelte
{#if showOriginal}
  {#if added.length > 0}
    <span class="csg-original-chip csg-original-chip--added" title="Cenários adicionados desde a última construção">
      +{added.length} {added.length === 1 ? "cenário" : "cenários"}
    </span>
  {/if}
  {#if removed.length > 0}
    <span class="csg-original-chip csg-original-chip--removed" title="Cenários removidos desde a última construção">
      −{removed.length} {removed.length === 1 ? "cenário" : "cenários"}
    </span>
  {/if}
{/if}
```

CSS:

```css
.csg-original-chip {
  margin-left: 8px;
  padding: 2px 6px;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border: 1px solid var(--terminal-border-subtle);
  border-radius: 2px;
  font-family: var(--terminal-font-mono);
  white-space: nowrap;
}
.csg-original-chip--added {
  color: var(--terminal-status-success);
  background: var(--terminal-bg-subtle);
}
.csg-original-chip--removed {
  color: var(--terminal-status-warning);
  background: var(--terminal-bg-subtle);
}
```

If `--terminal-status-warning` does not exist in the design tokens, fall back to `--terminal-fg-muted` and document the substitution in the commit message. Do not introduce new tokens.

### B.5 — `CalibrationPanel.svelte` script (single addition)

File: `frontends/wealth/src/lib/components/portfolio/CalibrationPanel.svelte`

After line 47 (`const applying = $derived(workspace.isApplyingCalibration);`), add:

```ts
// PR-A5 F.1 — snapshot of the calibration as of the most recent
// construction run. Drives the per-field "Anteriormente" overlay
// in every CalibrationField. Loose typing is intentional — the
// snapshot JSONB schema evolves with calibration; readers cast
// per known key with safe fallbacks.
const snapshot = $derived(
  (workspace.constructionRun?.calibration_snapshot ?? null) as
    | (Partial<PortfolioCalibration> & Record<string, unknown>)
    | null
);
```

`PortfolioCalibration` is already imported in this file. No new imports.

### B.6 — `CalibrationPanel.svelte` markup — wire `originalValue` per field

Pass `originalValue={snapshot?.<key>}` to each Slider/Select/Toggle/ScenarioGroup. Use `as` casts only when the snapshot type widens beyond the field's strict prop type. Be exhaustive — every field gets an `originalValue` if the snapshot key exists.

#### Basic tier (lines 286-352):

| File line | Component | Add prop |
|---|---|---|
| ~291 (mandate) | `CalibrationSelectField` | `originalValue={snapshot?.mandate as string \| undefined}` |
| ~300 (cvar_limit) | `CalibrationSliderField` | `originalValue={snapshot?.cvar_limit as number \| undefined}` |
| ~315 (max_single_fund_weight) | `CalibrationSliderField` | `originalValue={snapshot?.max_single_fund_weight as number \| undefined}` |
| ~328 (turnover_cap) | `CalibrationSliderField` | `originalValue={snapshot?.turnover_cap == null ? TURNOVER_CAP_SENTINEL : (snapshot.turnover_cap as number)}` (mirror the same `?? sentinel` transform the `value` prop uses) |
| ~341 (stress_scenarios_active) | `CalibrationScenarioGroup` | `originalValue={snapshot?.stress_scenarios_active as readonly StressScenarioId[] \| undefined}` |

#### Advanced tier (lines 352-462):

For every field in the Advanced tier (`regime_override`, `bl_enabled`, `bl_strength`, `garch_enabled`, `turnover_lambda`, `stress_severity`, `advisor_enabled`, `cvar_level`, `risk_aversion`, `shrinkage`), pass the corresponding `originalValue={snapshot?.<key> as <type> \| undefined}`. Read the existing `value=` line per field to determine the exact key and any sentinel transforms.

For `regime_override` (Select) where `value={draft.regime_override ?? "auto"}`, mirror with `originalValue={snapshot?.regime_override ?? (snapshot ? "auto" : undefined)}`. The conditional preserves "no snapshot" → no chip, while "snapshot has explicit null" → chip showing "Auto" if draft differs.

#### Expert tier

Skip. The Expert tier (`expert_overrides` JSONB accordion) is dynamic key/value; out of scope for F.1. Document in the commit message.

### B.7 — Type safety guard

Add to the top of `CalibrationPanel.svelte` script (right after the existing imports):

```ts
import type { StressScenarioId } from "$lib/types/portfolio-calibration";
```

(if not already imported — verify with grep before adding)

Do **not** introduce a runtime guard library. The casts above are intentional and limited to known snapshot keys.

### B.8 — Empty state contract

When `workspace.constructionRun === null` (portfolio that has never been built), `snapshot` is `null`, every `originalValue` evaluates to `undefined`, every chip stays hidden. No special-casing needed in components.

When the snapshot key exists but is structurally the same as the draft, the chip stays hidden via the `originalValue !== value` guard. The exact comparison rules per type:

- **string / number / boolean** — strict `!==`.
- **array (ScenarioGroup)** — set-based diff per B.4.
- **null vs undefined** — `originalValue === undefined` short-circuits before any comparison.

### B.9 — Reset-on-portfolio-switch behaviour

The existing `$effect` (lines 64-71) clones `calibration` into `draft` when the portfolio changes. F.1 does NOT need to react — `snapshot` is `$derived` from `workspace.constructionRun`, which `workspace.selectPortfolio()` resets to `null` (verify in `portfolio-workspace.svelte.ts:618`). The chip auto-hides without F.1 wiring anything.

### B.10 — Removed entirely

(Reserved — no item.)

---

## Section C — Verification

Before declaring done:

```bash
cd frontends/wealth
pnpm exec svelte-check --tsconfig ./tsconfig.json
# Expect: 0 errors. Pre-existing 21 a11y warnings unchanged.

pnpm exec eslint src/lib/components/portfolio/Calibration*.svelte
# Expect: clean.

# Build the UI package (no changes there, but confirm nothing breaks)
pnpm --filter @investintell/ui build
```

**Manual visual smoke test** (mandatory per `feedback_visual_validation.md`):

1. `make up && make serve` (backend) and `pnpm --filter wealth dev` (frontend).
2. Login. Open a portfolio that has at least one prior `portfolio_construction_runs` row.
3. Open Builder → CalibrationPanel.
4. Confirm that **every** Basic-tier field renders WITHOUT a chip (draft equals snapshot on load).
5. Edit the `Mandate` from `Balanced` to `Growth` — confirm chip appears reading `ANTERIORMENTE: BALANCED` (uppercase via CSS).
6. Edit `Tail loss budget` from 5.0% to 7.5% — chip reads `ANTERIORMENTE: 5,00%`.
7. Edit `Max single-fund weight` from 10% to 15% — chip reads `ANTERIORMENTE: 10,0%`.
8. Edit `Turnover cap` from 100% to 50% — chip reads `ANTERIORMENTE: 100%`.
9. Toggle one stress scenario off — chip reads `−1 CENÁRIO`. Toggle one back ON that wasn't there — chip reads `+1 CENÁRIO`. Both chips can co-exist.
10. Click `RESET` button (existing). Confirm draft returns to snapshot value AND every chip disappears.
11. Switch portfolio to a NEVER-BUILT one. Confirm: zero chips even after editing (snapshot is null).

Screenshot every chip in step 5-9 (5 PNGs) and attach to PR description.

---

## Section D — What NOT to do

- Do NOT change the `value` / `onChange` API of any field component. `originalValue` is purely additive.
- Do NOT add a "Restore" / "Apply previous" button next to the chip. Click semantics on the chip itself: none. Pure information.
- Do NOT add CSS animations, transitions, or hover states beyond what the existing field has.
- Do NOT touch the Expert tier accordion. Out of scope.
- Do NOT introduce a Tooltip component just for the chip — the native `title` attribute is sufficient and matches existing patterns in the file.
- Do NOT compute `snapshot` inside any child component. It is owned by `CalibrationPanel.svelte` and passed down as prop.
- Do NOT re-fetch the construction run from inside CalibrationPanel. `workspace.constructionRun` is the single source of truth, populated by the existing `runBuildJob` / `loadConstructionRun` flow.
- Do NOT add unit tests. Visual smoke is sufficient; the semantics are pure-derive and well-typed.
- Do NOT bump dependency versions.
- Do NOT break the existing `tier === "expert"` accordion code path — it currently iterates `Object.entries(draft.expert_overrides ?? {})` and is unchanged.

---

## Section E — Commit structure

Single commit:

```
feat(wealth): per-field "Anteriormente" overlay on CalibrationPanel (PR-A5 F.1)

PR-A5 Section F.1 (replacement for the destroyed working-tree feature):

- Adds optional ``originalValue`` prop to CalibrationSelectField,
  CalibrationSliderField, CalibrationToggleField, CalibrationScenarioGroup.
  Backward compatible — no consumer outside CalibrationPanel needs changes.
- ScenarioGroup uses set-based diff (added / removed counts).
- CalibrationPanel derives ``snapshot`` from
  ``workspace.constructionRun.calibration_snapshot`` and wires every
  Basic + Advanced tier field. Expert tier is out of scope.
- Chip styling uses existing terminal tokens
  (``--terminal-fg-muted``, ``--terminal-bg-subtle``, ``--terminal-border-subtle``,
  ``--terminal-status-success``). No new tokens introduced.
- DL15 (no localStorage) and DL16 (formatter discipline) preserved.
- svelte-check: 0 errors. eslint: clean.
- Visual smoke: 5 screenshots attached to PR.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## Section F — Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| `--terminal-status-warning` token missing | Medium | Fall back to `--terminal-fg-muted`, document in commit |
| `csl-` prefix wrong (verify SliderField uses different namespace) | Low | Read the file before editing; copy actual prefix |
| Snapshot keys drift from `PortfolioCalibration` shape (older runs) | Medium | All casts are `as T \| undefined`; missing keys silently produce no chip |
| `turnover_cap` sentinel transform mismatch | Low-Medium | Mirror the exact `value` prop expression including the `?? TURNOVER_CAP_SENTINEL` |
| `regime_override` null/auto duality | Low | Conditional `originalValue={snapshot?.regime_override ?? (snapshot ? "auto" : undefined)}` is exhaustive |
| Pre-existing CalibrationPanel CSS conflicts with new chip class | Low | Use unique `*-original-chip` class per file; no overlap |

---

## Section G — Reference files (absolute paths)

- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\portfolio\CalibrationPanel.svelte` (script ~46-48, basic tier 286-352, advanced tier 352-462)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\portfolio\CalibrationSelectField.svelte` (Props 17-25, destructuring 27-36, header markup, style block)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\portfolio\CalibrationSliderField.svelte` (Props 23-37, destructuring 39-51, displayFormat enum, header markup with inline value chip)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\portfolio\CalibrationToggleField.svelte` (Props 8-15, destructuring 17-24, header markup)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\portfolio\CalibrationScenarioGroup.svelte` (Props 17-23, destructuring 25-32, header markup ~45)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\state\portfolio-workspace.svelte.ts:60` (`calibration_snapshot: Record<string, unknown> | null`)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\state\portfolio-workspace.svelte.ts:418` (`constructionRun = $state.raw<ConstructionRunPayload | null>(null)`)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\state\portfolio-workspace.svelte.ts:618` (selectPortfolio resets `constructionRun`)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\types\portfolio-calibration.ts` (PortfolioCalibration + StressScenarioId types)

---

**End of F.1 sub-spec. Single commit. Report back with `git show --stat HEAD`, svelte-check output, and the 5 visual screenshots.**
