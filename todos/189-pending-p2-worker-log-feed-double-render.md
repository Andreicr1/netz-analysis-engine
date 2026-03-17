---
status: complete
priority: p2
issue_id: "189"
tags: [code-review, performance, admin, frontend]
dependencies: []
---

# WorkerLogFeed double-render on every log line at capacity

## Problem Statement

The WorkerLogFeed component pushes to the reactive `logs` array then conditionally slices it. `push()` triggers a reactive update, then `slice()` triggers a second update, causing a double render on every log line when the buffer is full (1000 lines). `{#each logs as line}` without a key causes full list re-render on every mutation.

## Findings

- `frontends/admin/src/lib/components/WorkerLogFeed.svelte`
- `push()` then `slice()` = two reactive updates per log line at capacity
- `{#each logs as line}` without key = full list re-render
- At 100+ lines/sec, causes frame drops and UI jank

## Proposed Solutions

### Option 1: Single assignment + key + $state.raw

**Approach:** Replace push-then-slice with `logs = [...logs.slice(-(MAX_LINES - 1)), line]`. Add key to each block. Use `$state.raw` since log lines are never mutated.

**Effort:** 30 minutes

**Risk:** Low

## Recommended Action

## Technical Details

**Affected files:**
- `frontends/admin/src/lib/components/WorkerLogFeed.svelte`

## Acceptance Criteria

- [ ] Single reactive update per log line
- [ ] {#each} has stable key
- [ ] No frame drops at high throughput
- [ ] Auto-scroll still works

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — performance-oracle agent)
