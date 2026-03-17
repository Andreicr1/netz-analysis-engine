---
status: complete
priority: p3
issue_id: "192"
tags: [code-review, performance, frontend]
dependencies: []
---

# DataTable recreates TanStack table instance on every data change

## Problem Statement

The DataTable component (`packages/ui/src/lib/components/DataTable.svelte`) creates the table via `$derived(createTable({...}))`. Every time `data` or `columns` changes, the entire TanStack table instance is rebuilt from scratch — including pagination position and sorting state. TanStack table's reactive getter pattern is specifically designed to avoid reconstruction.

## Findings

- `packages/ui/src/lib/components/DataTable.svelte` — `$derived(createTable(...))`
- On filter change with 500+ rows, table instance is reconstructed, losing pagination
- Getter pattern (`get data() { return data; }`) is correct but wrapping in $derived negates it

## Proposed Solutions

### Option 1: Call createTable once, use reactive getters

**Approach:** Create table once in `let` assignment, let TanStack's reactive getters handle updates.

**Effort:** 1 hour

**Risk:** Low

## Technical Details

**Affected files:**
- `packages/ui/src/lib/components/DataTable.svelte`

## Acceptance Criteria

- [ ] Table instance created once, not on every data change
- [ ] Pagination/sorting state preserved across data updates
- [ ] Filtering still works reactively

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — performance-oracle agent)
