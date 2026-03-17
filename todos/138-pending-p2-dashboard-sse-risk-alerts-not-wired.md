---
status: pending
priority: p2
issue_id: 138
tags: [code-review, sse, dashboard, incomplete]
---

# Problem Statement

Dashboard declares `let riskAlerts = $state<WealthAlert[]>([])` but never connects to the SSE stream. The AlertFeed component renders "Nenhum alerta" permanently because no `$effect` subscribes to `/risk/stream`.

The plan (Phase 2.3) explicitly required:
- Wire SSE subscription using `$effect` with `AbortController` cleanup
- Cap `riskAlerts` array at 50 entries
- Verify Redis pub/sub channels include `organization_id`

None of these were implemented.

# Findings

- `dashboard/+page.svelte` line 107: `let riskAlerts = $state<WealthAlert[]>([])` — never populated
- No `$effect` block for SSE subscription anywhere in the dashboard
- The `WealthAlert` discriminated union type is correct but the data path from SSE → component is missing
- The `AlertFeed` component works correctly when given data (verified in code)

# Proposed Solutions

## Option 1: Wire SSE now
Add `$effect` with `createSSEStream("/risk/stream")` + `AbortController` cleanup. Parse events into `WealthAlert` discriminated union. Cap at 50 entries.

## Option 2: Defer SSE, add TODO in code
Add a comment `// TODO: Wire SSE subscription for risk alerts (Phase 2.3)` and keep EmptyState. This is acceptable if the Redis pub/sub tenant isolation (channel naming) isn't resolved yet.

# Technical Details
- **File:** `frontends/wealth/src/routes/(team)/dashboard/+page.svelte`
- **Dependency:** Redis pub/sub channels must include `organization_id` (security gap noted in plan)
- **Pattern:** See `FundDetailPanel.svelte` SSE implementation for correct pattern
