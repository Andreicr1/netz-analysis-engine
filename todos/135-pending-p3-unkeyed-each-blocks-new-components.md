---
status: pending
priority: p3
issue_id: 135
tags: [code-review, svelte, quality]
---

# Problem Statement

Five `{#each}` blocks across three new components lack keys. While low-impact for static lists, this is inconsistent with the project's Svelte conventions and prevents Svelte from performing optimal DOM reconciliation when list items change order or are added/removed.

# Findings

- `HeatmapTable.svelte` — 3 unkeyed `{#each}` blocks (iterating columns, rows, cells).
- `PeriodSelector.svelte` — 1 unkeyed `{#each}` block (iterating period options).
- `RegimeBanner.svelte` — 1 unkeyed `{#each}` block (iterating signal items).
- Svelte without keys falls back to index-based diffing: if items are reordered, all DOM nodes after the first changed index are re-rendered unnecessarily.
- For regime signals and period selectors, items may change dynamically based on data, making this a real (not hypothetical) correctness concern.

# Proposed Solutions

Add unique keys to each block:

- `HeatmapTable.svelte` columns: `{#each cols as col (col)}`
- `HeatmapTable.svelte` rows: `{#each rows as row (row)}`
- `HeatmapTable.svelte` cells: `{#each row.cells as cell (ci)}` (or a cell-specific unique ID)
- `PeriodSelector.svelte`: `{#each periods as period (period)}`
- `RegimeBanner.svelte`: `{#each signals as sig (sig.label)}`

Use the most semantically meaningful key — typically a stable string ID or label rather than array index.

# Technical Details

- **Files:**
  - `frontends/wealth/src/lib/components/HeatmapTable.svelte`
  - `frontends/wealth/src/lib/components/PeriodSelector.svelte`
  - `frontends/wealth/src/lib/components/RegimeBanner.svelte`
- **Svelte docs reference:** `{#each list as item (key)}` — key must be unique and stable
- **Source:** pattern-recognition
