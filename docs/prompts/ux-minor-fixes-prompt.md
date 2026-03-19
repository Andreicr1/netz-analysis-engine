# UX Minor Fixes — 26 Issues Across All Frontends

> **Context:** Full design review identified 11 CRITICAL and 23 MAJOR issues (all resolved). These 26 MINOR issues remain. Each is self-contained with exact file path, line reference, and fix specification.
>
> **Execution:** Launch 5 parallel agents grouped by frontend. All fixes are mechanical — no architectural decisions needed.

---

## Group 1 — Credit Frontend (11 fixes)

### m1. FRED Explorer search results lack keyboard navigation
**File:** `frontends/credit/src/routes/(team)/dashboard/+page.svelte`
**Location:** ~lines 232-241 (FRED series result buttons)
**Fix:** Add `onkeydown` handler to the result list container for arrow-key navigation. Each `<button>` in the results list should support `ArrowDown`/`ArrowUp` to move focus between items:
```svelte
<div role="listbox" onkeydown={handleResultsKeydown}>
    {#each results as series}
        <button role="option" ...>{series.title}</button>
    {/each}
</div>
```
Add a handler function:
```typescript
function handleResultsKeydown(e: KeyboardEvent) {
    const items = (e.currentTarget as HTMLElement).querySelectorAll('[role="option"]');
    const current = Array.from(items).indexOf(document.activeElement as Element);
    if (e.key === 'ArrowDown' && current < items.length - 1) {
        (items[current + 1] as HTMLElement).focus();
        e.preventDefault();
    } else if (e.key === 'ArrowUp' && current > 0) {
        (items[current - 1] as HTMLElement).focus();
        e.preventDefault();
    }
}
```

### m2. FRED Explorer chip close button needs aria-label
**File:** `frontends/credit/src/routes/(team)/dashboard/+page.svelte`
**Location:** ~line 248 (chip close `&times;` button)
**Fix:** Add `aria-label` and replace raw entity with SVG icon:
```svelte
<!-- Before -->
<button onclick={() => ...}>&times;</button>
<!-- After -->
<button onclick={() => removeSeries(id)} aria-label="Remove {id}" class="ml-1 opacity-60 hover:opacity-100">
    <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
</button>
```

### m3. Kanban error toast has no transition
**File:** `frontends/credit/src/lib/components/PipelineKanban.svelte`
**Location:** ~lines 202-206 (error toast div)
**Fix:** Add `transition:fade` from Svelte:
```svelte
<script>
    import { fade } from 'svelte/transition';
</script>
<!-- on the error toast div: -->
{#if errorMessage}
    <div transition:fade={{ duration: 200 }} class="..." role="alert">
        {errorMessage}
    </div>
{/if}
```
If the Toast component from `@netz/ui` exists and is appropriate, consider replacing the manual toast entirely. Check `@netz/ui` exports first.

### m4. DataTable status columns render raw text instead of StatusBadge
**Files:**
- `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte`

**Fix:** For each file, find DataTable column definitions for `stage`, `status`, or `priority` fields. These render raw strings like "IC_REVIEW" or "UNDER_REVIEW". Add a cell snippet that renders a `StatusBadge`:

Read each file to find the DataTable columns config. For columns with status/stage/priority, add a cell renderer snippet:
```svelte
{#snippet stageCell(row)}
    <StatusBadge status={row.stage} />
{/snippet}
```
Then pass the snippet to the DataTable column definition (check DataTable API for how cell renderers are passed — likely via a `cell` property in the column config object).

Import `StatusBadge` from `@netz/ui` if not already imported.

### m5. Document metadata renders raw keys
**File:** `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.svelte`
**Location:** ~line 150 (Object.entries loop displaying key-value pairs)
**Fix:** Add a label map and use it for display:
```typescript
const keyLabels: Record<string, string> = {
    created_at: 'Created At',
    updated_at: 'Updated At',
    blob_uri: 'File Location',
    root_folder: 'Root Folder',
    file_name: 'File Name',
    file_size: 'File Size',
    mime_type: 'MIME Type',
    classification: 'Classification',
    confidence: 'Confidence',
    page_count: 'Page Count',
    organization_id: 'Organization',
};

function humanizeKey(key: string): string {
    return keyLabels[key] ?? key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
```
Then replace `{key}` with `{humanizeKey(key)}` in the template.

### m6. Copilot input should be textarea for multiline
**File:** `frontends/credit/src/routes/(team)/copilot/+page.svelte`
**Location:** ~line 167 (single-line `<input type="text">`)
**Fix:** Replace `<input type="text">` with `<textarea>` with auto-resize:
```svelte
<textarea
    bind:value={query}
    placeholder="Ask anything about your portfolio..."
    rows="1"
    class="... resize-none overflow-hidden"
    onkeydown={(e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }}
    oninput={(e) => {
        const target = e.currentTarget;
        target.style.height = 'auto';
        target.style.height = target.scrollHeight + 'px';
    }}
></textarea>
```
Keep all existing classes. The `oninput` handler auto-resizes. `rows="1"` starts as single line. Shift+Enter adds newline, Enter sends.

### m7. Dashboard imports unused chart components
**File:** `frontends/credit/src/routes/(team)/dashboard/+page.svelte`
**Location:** ~lines 13-14 (imports)
**Fix:** Remove unused imports. Check which of `FunnelChart`, `ScatterChart`, `TimeSeriesChart` are actually used in the template. Remove any that aren't referenced. Use grep within the file to confirm.

### m8. Kanban card shows redundant StatusBadge for column stage
**File:** `frontends/credit/src/lib/components/PipelineKanban.svelte`
**Location:** ~line 187 (StatusBadge showing stage inside card that's already in that stage's column)
**Fix:** Remove the `<StatusBadge status={deal.stage} />` from the card. The card is already in the column that represents that stage — the badge is redundant. If there are other StatusBadges on the card for different fields (priority, etc.), keep those.

### m9. Dataroom page EmptyState wrapped in Card inconsistently
**File:** `frontends/credit/src/routes/(team)/funds/[fundId]/documents/dataroom/+page.svelte`
**Fix:** Read the file. If the EmptyState is wrapped in `<Card class="p-6">`, remove the Card wrapper and render EmptyState directly (matching other pages). Or wrap in `<SectionCard>` for consistency:
```svelte
<SectionCard title="Data Room">
    <EmptyState message="..." />
</SectionCard>
```

### m10. Pipeline view mode toggle lacks aria-label
**File:** `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte`
**Location:** ~lines 108-123 (List/Kanban toggle buttons)
**Fix:** Add `role="group"` and `aria-label` to the container, and `aria-label` + `aria-pressed` to each button:
```svelte
<div role="group" aria-label="View mode">
    <Button aria-label="List view" aria-pressed={viewMode === 'list'} ...>
        List
    </Button>
    <Button aria-label="Board view" aria-pressed={viewMode === 'kanban'} ...>
        Board
    </Button>
</div>
```

### m11. Review detail has mixed PT-BR text
**File:** `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`
**Location:** ~line 508 (impactSummary string)
**Fix:** Find `"Reverter este item exige justificativa..."` and replace with English:
```
"Reverting this item requires justification. Unchecking a completed checklist item..."
```
Search the entire file for any other Portuguese text and translate to English.

---

## Group 2 — Wealth Frontend Non-Screener (8 fixes)

### m12. Model-portfolios list imports unused components
**File:** `frontends/wealth/src/routes/(team)/model-portfolios/+page.svelte`
**Location:** ~line 8
**Fix:** Remove `UtilizationBar` and `PeriodSelector` from imports if not used in the template. Grep within the file to confirm.

### m13. Inconsistent card shadow usage
**Files across wealth frontend:**
- Some use `shadow-(--netz-shadow-1)` or `shadow-(--netz-shadow-card)` (token-based)
- Some use `shadow-sm` (Tailwind default, not token)
- Some SectionCards have no shadow

**Fix:** Search wealth frontend for `shadow-sm` in `.svelte` files. Replace with `shadow-(--netz-shadow-1)` for consistency with the token system. Do NOT add shadows to components that intentionally have none.

Files to check:
- `frontends/wealth/src/routes/(investor)/*.svelte` — likely have `shadow-sm`
- Any other wealth pages

### m14. DD report detail sidebar uses string interpolation in class
**File:** `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`
**Location:** ~lines 98-99
**Fix:** Replace string interpolation in `class` attribute with `class:` directives or a conditional helper:
```svelte
<!-- Before -->
class="w-full rounded-md px-3 py-2 text-left text-xs transition-colors
    {activeChapter === i ? 'bg-(--netz-brand-primary)/10...' : '...'}"

<!-- After (using ternary in a derived or cn() utility) -->
<button
    class={cn(
        "w-full rounded-md px-3 py-2 text-left text-xs transition-colors",
        activeChapter === i
            ? "bg-(--netz-brand-primary)/10 text-(--netz-brand-primary) font-medium"
            : "text-(--netz-text-secondary) hover:bg-(--netz-surface-highlight)"
    )}
>
```
Import `cn` from `@netz/ui` if not already imported. The `cn()` utility (typically `clsx` + `tailwind-merge`) is safer for Tailwind class merging than string interpolation.

### m15. Backtest `paretoComputedAt` state never set
**File:** `frontends/wealth/src/routes/(team)/backtest/+page.svelte`
**Location:** ~line 93 (declaration), ~line 612 (conditional)
**Fix:** Read the file. If `paretoComputedAt` is truly never assigned anywhere in the file, remove:
1. The `let paretoComputedAt = $state<string | null>(null);` declaration
2. The `{#if paretoComputedAt}...{/if}` conditional block and its contents (since it can never render)

If the variable IS set somewhere (perhaps in an effect or API callback), leave it. Verify by searching the file for all occurrences of `paretoComputedAt`.

### m16. EmptyState props: `message` vs `description`
**Fix:** First, read `packages/ui/src/lib/components/EmptyState.svelte` to determine which prop name is canonical.

Then search ALL `.svelte` files for `<EmptyState` and check which prop they use. Standardize all to the canonical prop name.

If EmptyState accepts both (via `let { message, description } = $props()` with one aliasing the other), that's fine — but usage should still be consistent. Pick one and update all call sites.

### m17. `$derived` used with function instead of `$derived.by`
**File:** `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte`
**Location:** ~line 107
**Fix:** Replace:
```typescript
let weights = $derived<Record<string, number>>(() => {
    // ... function body
});
```
With:
```typescript
let weights: Record<string, number> = $derived.by(() => {
    // ... same function body
});
```

### m18. Timeout not cleaned up on unmount
**File:** `frontends/wealth/src/routes/(team)/funds/+page.svelte`
**Location:** ~line 79 (`closingTimeout` setTimeout)
**Fix:** Wrap the timeout in an `$effect` that returns a cleanup function, or use `onDestroy`:
```typescript
import { onDestroy } from 'svelte';

// ... existing code ...

onDestroy(() => {
    if (closingTimeout) clearTimeout(closingTimeout);
});
```
Or if the timeout is set inside an `$effect`, return the cleanup:
```typescript
$effect(() => {
    // ... logic that sets timeout ...
    return () => {
        if (closingTimeout) clearTimeout(closingTimeout);
    };
});
```
Read the file to determine which pattern fits.

### m19. Investor language toggle has no persistence
**File:** `frontends/wealth/src/routes/(investor)/+layout.svelte`
**Location:** Where `let language = $state<"pt" | "en">("pt")` is declared
**Fix:** Persist to localStorage:
```typescript
function getInitialLanguage(): "pt" | "en" {
    if (typeof localStorage !== 'undefined') {
        const saved = localStorage.getItem('netz-investor-language');
        if (saved === 'pt' || saved === 'en') return saved;
    }
    return 'pt';
}

let language = $state<"pt" | "en">(getInitialLanguage());

$effect(() => {
    if (typeof localStorage !== 'undefined') {
        localStorage.setItem('netz-investor-language', language);
    }
});
```

---

## Group 3 — Wealth Screener (1 fix)

### m20. Screener uses `window.location.reload()` instead of `invalidateAll()`
**File:** `frontends/wealth/src/routes/(team)/screener/+page.svelte`
**Location:** ~line 152 (`executeBatch` function)
**Fix:** Replace `window.location.reload()` with `await invalidateAll()`. Add import:
```typescript
import { invalidateAll } from '$app/navigation';
```

---

## Group 4 — Admin Frontend (3 fixes)

### m21. TenantCard `replace` only replaces first underscore
**File:** `frontends/admin/src/lib/components/TenantCard.svelte`
**Location:** ~line 20
**Fix:** Replace:
```typescript
const verticalLabel = $derived(tenant.vertical.replace("_", " "));
```
With:
```typescript
const verticalLabel = $derived(tenant.vertical.replace(/_/g, " "));
```

### m22. Duplicate `$effect` in ConfigDiffView
**File:** `frontends/admin/src/lib/components/ConfigDiffView.svelte`
**Location:** ~lines 129-143 (two `$effect` blocks both calling `mountView`)
**Fix:** Read the file. Consolidate the two effects into one that depends on all relevant reactive values:
```typescript
$effect(() => {
    // Reading these creates dependencies
    const _mode = viewMode;
    const _before = beforeDoc;
    const _after = afterDoc;
    mountView(_mode);
});
```
Remove the second `$effect` block. The single effect will re-run when any of the three dependencies change.

### m23. Error page links use "Go to Dashboard" but link to `/health`
**File:** `frontends/admin/src/routes/+error.svelte`
**Location:** ~lines 30-31, 43-44
**Fix:** Change the link label from "Go to Dashboard" to "Go to System Health" (which is the actual admin landing page). Or change to "Go Home" for simplicity:
```svelte
<a href="/" class="...">Go Home</a>
```

---

## Group 5 — Shared UI Package (3 fixes)

### m24. Sidebar border-radius hardcoded `6px`
**File:** `packages/ui/src/lib/layouts/Sidebar.svelte`
**Location:** ~line 144 in `<style>` block
**Fix:** Replace `border-radius: 6px;` with `border-radius: var(--netz-radius-sm, 6px);`. This uses the token with a fallback.

### m25. PageHeader title uses hardcoded `24px` font-size
**File:** `packages/ui/src/lib/layouts/PageHeader.svelte`
**Location:** ~line 102 in `<style>` block
**Fix:** Replace `font-size: 24px;` with `font-size: var(--netz-text-h2, 1.5rem);`. Check `packages/ui/src/lib/styles/typography.css` for the correct token name (likely `--netz-text-h2` or `--netz-font-size-h2`). Use the actual token name found.

### m26. Tailwind config fallback colors stale
**File:** `packages/ui/tailwind.config.ts`
**Location:** ~lines 11-15 (fallback hex colors in theme extend)
**Fix:** Read `packages/ui/src/lib/styles/tokens.css` to get the current token hex values. Then update the fallback colors in `tailwind.config.ts` to match:

Expected current token values (verify from tokens.css):
- `--netz-brand-primary`: likely `#18324d` (was `#1B365D`)
- `--netz-brand-secondary`: likely `#3e628d` (was `#3A7BD5`)
- `--netz-text-secondary`: likely `#8395a8` (was `#8B9DAF`)
- `--netz-surface-elevated`: likely `#e6edf6` (was `#D4E4F7`)
- `--netz-brand-accent`: likely `#c58757` (was `#FF975A`)

Read the actual values from `tokens.css` and sync the tailwind config fallbacks.

---

## Execution Instructions

1. Run all 5 groups as parallel agents
2. Each agent reads the target file BEFORE editing
3. Use Tailwind v4 parenthesis syntax: `text-(--netz-*)` (not bracket `[var()]`)
4. Use Svelte 5 patterns: `$state`, `$derived`, `$effect`, `onclick` (not `on:click`)
5. Import from `@netz/ui` for shared components/utils
6. Do NOT restructure pages — minimal targeted fixes only
7. After all fixes, run `pnpm -r check` from repo root to verify no type errors
