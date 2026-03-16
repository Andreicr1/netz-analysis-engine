---
status: complete
priority: p2
issue_id: "099"
tags: [code-review, bug, svelte, frontend]
dependencies: []
---

# PipelineFunnel uses $derived() instead of $derived.by() — bypasses reactivity

## Problem Statement

`PipelineFunnel.svelte:11` uses `$derived(() => {...})` which wraps the function as the derived value (making `stages` a function, not an array). The template calls `stages()` to invoke it. This should be `$derived.by(() => {...})` which evaluates the function and returns the result. The current pattern bypasses Svelte's fine-grained reactivity tracking.

## Findings

- `frontends/credit/src/lib/components/PipelineFunnel.svelte:11` — `let stages = $derived(() => { ... })`
- Template calls `stages()` on lines 20-21
- Should be `$derived.by(() => { ... })` and use `stages` directly

**Source:** Pattern Recognition agent

## Proposed Solutions

### Option 1: Change to $derived.by()

**Effort:** 5 minutes

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/lib/components/PipelineFunnel.svelte:11`

## Acceptance Criteria

- [ ] Uses `$derived.by()` instead of `$derived()`
- [ ] Template uses `stages` directly (not `stages()`)

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Pattern Recognition agent

## Resources

- **PR:** #39 (Phase B)
