# Session H5 -- Cross-Page Navigation + Final Polish

**Branch:** `feat/harmonization-h5-navigation`
**Base:** `main` (after H0-H4 merged)
**Estimated scope:** ~6 file edits, 0 new files

---

## CONTEXT

This is the FINAL session of the Terminal Harmonization Plan (`docs/plans/2026-04-13-terminal-harmonization-plan.md`). Sessions H0-H4 have already been merged. H0 extracted Layer 2/3 primitives and the lightweight-charts factory. H1 sanitized all 22 quant jargon leaks. H2 polished Live components and migrated hex values. H3 terminal-ized the Builder's CalibrationPanel. H4 migrated all 115 screener hex values to tokens.

The terminal now has three active pages: Screener, Builder, Live. They share a consistent visual language but lack lifecycle navigation links between them and have a few remaining inconsistencies.

Key files and their current state:

1. **TerminalTopNav** (`frontends/wealth/src/lib/components/terminal/shell/TerminalTopNav.svelte`) -- Line 147 uses `window.location.href = HREF_ALERTS` which causes a full page reload instead of SvelteKit client-side navigation.

2. **TerminalScreenerShell** (`frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte`) -- Has keyboard shortcuts at line 292: `/` = focus filters, arrows = navigate, Enter = open FocusMode, `u` = approve to universe, `d` = queue DD, `e` = toggle ELITE. Missing: `b` = open in Builder.

3. **TerminalDataGrid** (`frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte`) -- Action column (line 339-367) shows APPROVE or +DD buttons. No "builder" action exists yet.

4. **Builder +page.svelte** (`frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte`) -- No back-link to screener. Has portfolio selector dropdown at line 90.

5. **WeightsTab** (`frontends/wealth/src/lib/components/terminal/builder/WeightsTab.svelte`) -- Lines 345 and 367 use `border-bottom: 1px solid var(--terminal-bg-panel-raised)` instead of `var(--terminal-border-hairline)`. These are the ONLY remaining border inconsistencies across all terminal tables.

6. **choreo.ts** (`packages/investintell-ui/src/lib/charts/choreo.ts`) -- `svelteTransitionFor()` exists (line 173) and already has 3 consumers: CommandPalette, TerminalContextRail, FocusMode. Needs 2-3 more consumers to establish the pattern across Builder and Live pages.

---

## OBJECTIVE

Four focused changes:

### 1. Fix `window.location.href` in TerminalTopNav (line 147)

**File:** `frontends/wealth/src/lib/components/terminal/shell/TerminalTopNav.svelte`

Add `goto` import from `$app/navigation` and replace the `handleAlertClick` function:

```svelte
<script lang="ts">
  import { resolve } from "$app/paths";
  import { goto } from "$app/navigation";
  // ... rest of imports
```

Replace lines 145-148:
```typescript
// BEFORE:
function handleAlertClick() {
  // Navigate to the alerts inbox route.
  window.location.href = HREF_ALERTS;
}

// AFTER:
function handleAlertClick() {
  // Navigate to the alerts inbox route.
  goto(HREF_ALERTS);
}
```

### 2. Add Screener-to-Builder navigation ("b" shortcut + action)

**File:** `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte`

Add imports:
```typescript
import { goto } from "$app/navigation";
import { resolve } from "$app/paths";
```

Add a resolved constant near the top of the `<script>` block (after existing consts):
```typescript
const HREF_BUILDER = resolve("/portfolio/builder");
```

Add a new keyboard case after the `"e"` case (after line 363):
```typescript
case "b": {
  if (highlightedIndex >= 0 && highlightedIndex < assets.length) {
    const asset = assets[highlightedIndex];
    if (asset && asset.inUniverse) {
      goto(HREF_BUILDER);
    } else {
      showToast("Fund must be approved to universe first", "warn");
    }
  }
  break;
}
```

The "b" shortcut only navigates when the highlighted fund is already in the approved universe (same gate as the lifecycle flow: screen -> approve -> build).

### 3. Add Builder-to-Screener back-link

**File:** `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte`

Add a back-link above the portfolio selector in the left column.

**IMPORTANT:** The codebase enforces a lint rule `svelte/no-navigation-without-resolve` that rejects any `href` not produced by `resolve()` from `$app/paths`. You MUST use the `resolve()` pattern.

Add import and resolved constant in the `<script>` block:
```typescript
import { resolve } from "$app/paths";

const HREF_SCREENER = resolve("/terminal-screener");
```

Insert between the `<div class="builder-left">` opening tag (line 89) and the portfolio selector div (line 90):

```svelte
<!-- Breadcrumb back to screener -->
<a href={HREF_SCREENER} class="builder-backlink" data-sveltekit-preload-data="hover">
  &larr; SCREENER
</a>
```

Add styles inside the existing `<style>` block:
```css
.builder-backlink {
  display: inline-flex;
  align-items: center;
  gap: var(--terminal-space-1);
  padding: var(--terminal-space-1) var(--terminal-space-2);
  font-family: var(--terminal-font-mono);
  font-size: var(--terminal-text-10);
  font-weight: 600;
  letter-spacing: var(--terminal-tracking-caps);
  text-transform: uppercase;
  text-decoration: none;
  color: var(--terminal-fg-tertiary);
  border-bottom: var(--terminal-border-hairline);
  transition: color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
}

.builder-backlink:hover {
  color: var(--terminal-accent-amber);
}
```

### 4. Fix WeightsTab border inconsistency

**File:** `frontends/wealth/src/lib/components/terminal/builder/WeightsTab.svelte`

Replace two border declarations:

Line 345:
```css
/* BEFORE: */
border-bottom: 1px solid var(--terminal-bg-panel-raised);
/* AFTER: */
border-bottom: var(--terminal-border-hairline);
```

Line 367:
```css
/* BEFORE: */
border-bottom: 1px solid var(--terminal-bg-panel-raised);
/* AFTER: */
border-bottom: var(--terminal-border-hairline);
```

### 5. Wire `svelteTransitionFor()` into 2-3 additional consumers

Add choreo-backed transitions to Builder and Live components that currently lack Svelte `in:` / `out:` directives. Target components where panels mount/unmount conditionally:

#### 5a. Builder ActivationBar (`frontends/wealth/src/lib/components/terminal/builder/ActivationBar.svelte`)

The bar appears when `visible` is true (line 42: `{#if visible}`). Add a fly-in transition:

```svelte
<script lang="ts">
  import { fly } from "svelte/transition";
  import { svelteTransitionFor } from "@investintell/ui/charts/choreo";
  // ... existing imports
</script>

{#if visible}
  <div class="ab-bar" in:fly={{ y: 12, ...svelteTransitionFor("tail", { duration: "update" }) }}>
    <!-- existing buttons unchanged -->
  </div>
{/if}
```

#### 5b. Builder CascadeTimeline (`frontends/wealth/src/lib/components/terminal/builder/CascadeTimeline.svelte`)

The timeline appears when `showCascade` is true in the builder page. In the builder page (`+page.svelte`), the `{#if showCascade}` block at line 140 already conditionally renders CascadeTimeline. Wrap the CascadeTimeline mount with a fly transition at the page level:

```svelte
<script lang="ts">
  // Add to existing imports:
  import { fly } from "svelte/transition";
  import { svelteTransitionFor } from "@investintell/ui/charts/choreo";
</script>

<!-- In the template, replace line 140-142: -->
{#if showCascade}
  <div in:fly={{ y: -8, ...svelteTransitionFor("primary", { duration: "update" }) }}>
    <CascadeTimeline phases={cascadePhases} />
  </div>
{/if}
```

#### 5c. Builder tab content panel (`+page.svelte`)

Add a keyed fade transition on tab switch. Wrap the tab content div (line 145) with a key block:

```svelte
<script lang="ts">
  import { fade } from "svelte/transition";
  // svelteTransitionFor already imported from 5b
</script>

<!-- Replace lines 145-158 -->
<div class="builder-tab-content" role="tabpanel">
  {#key activeTab}
    <div in:fade={svelteTransitionFor("chrome", { duration: "tick" })}>
      {#if activeTab === "WEIGHTS"}
        <WeightsTab />
      {:else if activeTab === "RISK"}
        <RiskTab />
      {:else if activeTab === "STRESS"}
        <StressTab />
      {:else if activeTab === "BACKTEST"}
        <BacktestTab />
      {:else if activeTab === "MONTE CARLO"}
        <MonteCarloTab />
      {:else if activeTab === "ADVISOR"}
        <AdvisorTab />
      {/if}
    </div>
  {/key}
</div>
```

Note: The `{#key}` block destroys and recreates content on tab switch. This is acceptable here because workspace state lives in the shared store (`portfolio-workspace.svelte.ts`), not in component-local `$state`. **Before committing, verify that none of the 6 tab components (WeightsTab, RiskTab, StressTab, BacktestTab, MonteCarloTab, AdvisorTab) have local `$state` that would be lost on destroy/recreate (e.g., scroll position, slider values, expanded sections).** If any do, replace the `{#key}` approach with a CSS opacity transition that does NOT destroy the component:

```svelte
<!-- Fallback if any tab has local state: -->
<div class="builder-tab-content" role="tabpanel" style="opacity: 1;">
  <!-- keep all tabs mounted, show/hide with display:none -->
</div>
```

---

## CONSTRAINTS

1. Use SvelteKit `goto()` from `$app/navigation` for ALL programmatic navigation. NEVER `window.location.href`.
2. Use `<a href="...">` with `data-sveltekit-preload-data="hover"` for declarative links.
3. ALL border treatments in terminal tables MUST use `var(--terminal-border-hairline)`.
4. `svelteTransitionFor()` is imported from `@investintell/ui/charts/choreo` (the package export path). It returns `{ duration, delay, easing }` which spreads into Svelte transition params.
5. Do NOT relocate any files or change directory structure.
6. Do NOT touch any backend files.
7. Do NOT add new dependencies.

---

## DELIVERABLES

| File | Change |
|---|---|
| `frontends/wealth/src/lib/components/terminal/shell/TerminalTopNav.svelte` | Add `goto` import, replace `window.location.href` with `goto()` |
| `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte` | Add `goto` import, add `"b"` keyboard shortcut case |
| `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte` | Add screener back-link, add choreo transitions (cascade, tab switch) |
| `frontends/wealth/src/lib/components/terminal/builder/WeightsTab.svelte` | Fix 2 border declarations (lines 345, 367) |
| `frontends/wealth/src/lib/components/terminal/builder/ActivationBar.svelte` | Add fly-in transition with `svelteTransitionFor` |

---

## VERIFICATION

### Immediate checks:
```bash
cd frontends/wealth && pnpm check
```

### Border consistency audit (zero non-hairline borders in table rows):
```bash
grep -rn "border.*1px solid" \
  frontends/wealth/src/lib/components/terminal/builder/WeightsTab.svelte \
  frontends/wealth/src/lib/components/terminal/builder/StressTab.svelte \
  frontends/wealth/src/lib/components/terminal/builder/AdvisorTab.svelte \
  frontends/wealth/src/lib/components/terminal/builder/BacktestTab.svelte \
  frontends/wealth/src/lib/components/terminal/live/HoldingsTable.svelte \
  frontends/wealth/src/lib/components/terminal/live/DriftMonitorPanel.svelte \
  frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte
```

Expected: Zero hits in row/cell border context. Some `1px solid` may exist in badge/button borders (those are fine).

### Navigation audit:
```bash
# Zero window.location.href in terminal components
grep -rn "window\.location\.href" \
  frontends/wealth/src/lib/components/terminal/ \
  frontends/wealth/src/routes/\(terminal\)/
```

Expected: Zero hits.

### Choreo consumer count:
```bash
grep -rn "svelteTransitionFor" \
  frontends/wealth/src/lib/components/ \
  frontends/wealth/src/routes/
```

Expected: At least 6 consumers (3 existing + 3 new from this session).

---

## FINAL VALIDATION CHECKLIST (ALL H0-H5 WORK)

After this session, run the full harmonization validation sequence to confirm all 6 sessions are coherent:

### 1. Frontend type-check
```bash
cd frontends/wealth && pnpm check
```

### 2. Backend gate
```bash
make check
```

### 3. Jargon grep (H1 -- zero hits in user-visible strings)
```bash
grep -riE "cvar|clarabel|garch\b|ledoit|black.litterman|marchenko" \
  frontends/wealth/src/ \
  --include="*.svelte" --include="*.ts" | grep -vE "//|<!--|/\*|\.d\.ts"
```

### 4. Hardcoded hex in terminal components (H2/H3/H4 -- zero hits)
```bash
grep -rnE "#[0-9a-fA-F]{3,8}" \
  frontends/wealth/src/lib/components/terminal/ \
  --include="*.svelte" | grep -v "choreo\|test"
```

NOTE: The screener components live under `$lib/components/screener/terminal/` (not `$lib/components/terminal/screener/`). If H4 did NOT relocate them (the plan marked relocation as optional/lower priority), also check:
```bash
grep -rnE "#[0-9a-fA-F]{3,8}" \
  frontends/wealth/src/lib/components/screener/terminal/ \
  --include="*.svelte"
```

### 5. Navigation consistency (H5)
```bash
# No window.location in terminal surface
grep -rn "window\.location" \
  frontends/wealth/src/lib/components/terminal/ \
  frontends/wealth/src/routes/\(terminal\)/

# No bare location.reload except in error recovery panels
grep -rn "location\.reload" \
  frontends/wealth/src/lib/components/terminal/ \
  frontends/wealth/src/routes/\(terminal\)/
```

### 6. Border consistency (H5)
Verify all terminal table row borders use `var(--terminal-border-hairline)`. Tables verified:
- `WeightsTab.svelte` -- fixed in this session (lines 345, 367)
- `StressTab.svelte` -- already uses `var(--terminal-border-hairline)` (line 126)
- `AdvisorTab.svelte` -- already uses `var(--terminal-border-hairline)` (lines 228-229, 286)
- `BacktestTab.svelte` -- already uses `var(--terminal-border-hairline)` (line 244)
- `HoldingsTable.svelte` -- fixed in H2 (lines 170, 191)
- `DriftMonitorPanel.svelte` -- fixed in H2 (lines 235, 247)
- `TerminalDataGrid.svelte` -- uses `1px solid rgba(255, 255, 255, 0.08)` (line 446) and `1px solid rgba(255, 255, 255, 0.06)` (line 689). If H4 migrated these to tokens, confirm. If not, these are acceptable post-H4 since the entire DataGrid was token-migrated.

### 7. Choreo adoption (H5)
```bash
grep -rn "svelteTransitionFor" \
  frontends/wealth/src/lib/components/ \
  frontends/wealth/src/routes/ | wc -l
```
Expected: >= 6 consumers.

### 8. SSE sanitization (H0)
```bash
grep -rn "sanitize_payload" \
  backend/app/domains/wealth/workers/drift_monitor.py \
  backend/vertical_engines/wealth/monitoring/alert_engine.py \
  backend/app/domains/wealth/services/rebalancing/preview_service.py
```
Expected: 3 files, each importing and calling `sanitize_payload`.

### 9. Visual browser validation
```bash
make dev-wealth
```
Walk through:
1. Open Screener -- verify monospace font, terminal tokens, no blue accent leak
2. Highlight a row with arrows, press `b` -- verify toast "Fund must be approved to universe first" (if not approved) or navigation to Builder
3. Press `u` to approve a fund, then `b` -- verify navigation to Builder
4. In Builder, verify "SCREENER" back-link at top-left
5. Click back-link -- verify client-side navigation (no full reload)
6. In Builder, run a construction -- verify CascadeTimeline slides in with transition
7. Switch tabs -- verify subtle fade transition on content swap
8. Complete all 6 tabs -- verify ActivationBar flies in from below
9. Navigate to Live -- verify consistent visual language across all 3 pages
10. Click alert pill in TopNav -- verify client-side navigation (no full reload)

---

## ANTI-PATTERNS

- Do NOT use `window.location.href` or `window.location.assign()` for navigation.
- Do NOT add `transition:` directives to every component -- only the 2-3 specified above. Over-animating a financial terminal degrades trust.
- Do NOT create new components or files for this session.
- Do NOT change any business logic, API calls, or data flow.
- Do NOT use `location.reload()` outside of error recovery panels.
- Do NOT add inline `duration: 900` or `delay: 120` literals -- always use `svelteTransitionFor()`.

---

## COMMIT MESSAGE

```
fix(terminal): H5 cross-page navigation + final polish

- Replace window.location.href with goto() in TerminalTopNav alert click
- Add "b" keyboard shortcut in Screener to navigate to Builder (approved funds only)
- Add Screener back-link in Builder left column
- Fix WeightsTab row borders to use var(--terminal-border-hairline)
- Wire svelteTransitionFor() into ActivationBar, CascadeTimeline, and Builder tab switch
- Completes Terminal Harmonization Plan (H0-H5)
```
