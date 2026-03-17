---
id: 168
status: pending
priority: p2
tags: [code-review, quality, ux-bug]
created: 2026-03-17
---

# Silent catch blocks in instruments and copilot — no user feedback

## Problem Statement

Multiple async functions across wealth and credit frontends swallow exceptions in bare `catch {}` blocks, giving users zero feedback when operations fail. The UI silently does nothing, leaving users confused about whether their action succeeded.

## Findings

- **File:** `frontends/wealth/src/routes/(team)/instruments/+page.svelte`
  - `bulkSync` — bare `catch {}`
  - `searchExternal` — bare `catch {}`
  - `importInstrument` — bare `catch {}`

- **File:** `frontends/credit/src/routes/(team)/copilot/+page.svelte`
  - `submitQuery` — bare `catch {}`
  - `loadHistory` — bare `catch {}`
  - `loadActivity` — bare `catch {}`
  - `searchDocuments` — bare `catch {}`

- All 7 functions silently swallow errors; the user sees no toast, banner, or inline error message

## Proposed Solutions

1. Add an `actionError` reactive state variable to each page
2. In each `catch` block, set `actionError` to a user-friendly message (e.g., "Failed to sync instruments. Please try again.")
3. Display an error banner or toast component when `actionError` is set
4. Optionally log the full error to `console.error` for debugging

## Acceptance Criteria

- [ ] All 7 listed catch blocks set a visible error state instead of silently swallowing
- [ ] Users see a clear error message when any of these operations fail
- [ ] Error state is cleared on retry or next successful action
- [ ] No raw exception messages are shown to the user (use generic friendly text)
