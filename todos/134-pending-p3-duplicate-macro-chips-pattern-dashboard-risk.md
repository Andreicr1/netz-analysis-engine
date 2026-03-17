---
status: pending
priority: p3
issue_id: 134
tags: [code-review, duplication]
---

# Problem Statement

Approximately 40 lines of macro indicator chip rendering logic are duplicated between the dashboard and risk pages with only minor coloring differences. This violates DRY, means any future change to chip layout or behavior requires two edits, and risks the two implementations diverging silently over time.

# Findings

- `frontends/wealth/src/routes/(team)/dashboard/+page.svelte` lines 201-218 render macro indicator chips.
- `frontends/wealth/src/routes/(team)/risk/+page.svelte` lines 176-192 contain near-identical chip rendering with slightly different color thresholds.
- The only substantive difference is the color/threshold logic applied to each indicator value.
- Both blocks consume the same `MacroIndicators` data shape from the page load function.
- As additional wealth pages need macro context (e.g., funds, analytics), this pattern will proliferate further.

# Proposed Solutions

Extract a `MacroChips.svelte` component in `packages/ui/src/lib/components/wealth/` (or `frontends/wealth/src/lib/components/`) accepting:

```typescript
interface MacroChipsProps {
    indicators: MacroIndicators;
    thresholds?: Partial<Record<keyof MacroIndicators, { warn: number; danger: number }>>;
}
```

Default thresholds cover the dashboard use case. Risk page overrides only the thresholds that differ. Both pages import and render `<MacroChips {indicators} {thresholds} />`.

# Technical Details

- **Files:**
  - `frontends/wealth/src/routes/(team)/dashboard/+page.svelte` lines 201-218
  - `frontends/wealth/src/routes/(team)/risk/+page.svelte` lines 176-192
- **Duplication size:** ~40 lines
- **Suggested component location:** `frontends/wealth/src/lib/components/MacroChips.svelte`
- **Source:** pattern-recognition, code-simplicity-reviewer
