# Phase 3C — IC Governance Workflows (Macro Review + Rebalancing + Content)

**Status:** Ready
**Estimated scope:** ~600 lines changed
**Risk:** Medium (workflow UI with state machines, ConsequenceDialog)
**Prerequisite:** None (backend endpoints already exist)

---

## Context

Three IC governance workflows have backend routes but limited/no frontend UI. Users currently need curl/Postman for approval operations.

**Common UX Doctrine patterns for all three:**
- §16 (Workflow): Status pipeline visible — draft → pending_review → approved → published/executed
- §7 (Layer 4 — Process Layer): Stage transitions, consequence dialogs, approval maturity
- ConsequenceDialog: required for approve/reject/execute actions (rationale field mandatory)

---

## Task 1: Macro Reviews Governance Enhancement

### What exists

Backend:
- `PATCH /macro/reviews/{id}/approve` — already exists
- `PATCH /macro/reviews/{id}/reject` — already exists
- `POST /macro/reviews/generate` — already exists

Frontend (`frontends/wealth/src/routes/(team)/macro/+page.svelte`):
- Reviews section exists (lines ~134-152)
- Approve/reject handlers exist (lines ~42-78)
- Generate trigger exists (lines ~28-40)

### What to enhance

**Step 1.1 — Status badges**

Add status pipeline badges to each review card:
```svelte
<StatusBadge status={getReviewStatus(review.status)}>
  {review.status}
</StatusBadge>
```

Status mapping:
- `draft` → neutral
- `pending_review` → info
- `approved` → success
- `published` → accent
- `rejected` → danger

**Step 1.2 — ConsequenceDialog for approve/reject**

Replace inline confirm with proper `ConsequenceDialog`:

```svelte
<ConsequenceDialog
  open={showApproveDialog}
  title="Approve Macro Review"
  description="This review will be published and visible to the team."
  confirmLabel="Approve"
  onConfirm={handleApprove}
>
  <textarea bind:value={rationale} placeholder="Approval rationale (required)" required />
</ConsequenceDialog>
```

**Step 1.3 — Race condition check**

Verify backend uses `.with_for_update()` on approve/reject endpoints. If not, flag as TODO (per wealth-macro-intelligence-suite learning P1 bug).

**Step 1.4 — Audit trail link**

Add link per review to audit trail (if endpoint exists: `GET /audit?entity_type=macro_review&entity_id={id}`).

---

## Task 2: Rebalancing Workflow UI

### What exists

Backend endpoints (verify exact paths by reading rebalance routes):
- `POST /portfolios/{profile}/rebalance/propose` — propose weight changes
- `GET /portfolios/{profile}/rebalance/pending` — list pending proposals
- `POST /portfolios/{profile}/rebalance/{id}/approve` — approve
- `POST /portfolios/{profile}/rebalance/{id}/execute` — execute

### What to build

**Step 2.1 — Rebalancing tab**

Create `frontends/wealth/src/routes/(team)/portfolios/[profile]/RebalancingTab.svelte`:

Find the Portfolio Detail page and add a "Rebalancing" tab. The component should show:

1. **"Propose Rebalance" button** — triggers POST propose, shows result
2. **Pending list** — shows all pending proposals with status badges
3. **Proposal detail** — before/after weight comparison table
4. **CVaR impact** — MetricCard pair (current vs projected) with limit markLine
5. **Approve button** — ConsequenceDialog with rationale + before/after comparison
6. **Execute button** — ConsequenceDialog (separate from Approve — executing triggers real portfolio changes)

**Step 2.2 — Before/After visualization**

Paired horizontal bar chart (butterfly/tornado):
- Two bar series sharing Y axis (fund names)
- "Before": negative values extending left, `--netz-chart-4` (muted)
- "After": positive values extending right, `--netz-chart-1` (bold)
- Use raw `ChartContainer` from ECharts

**Step 2.3 — State machine**

```
proposed → pending_review → approved → executing → executed
                         ↘ rejected          ↘ failed
```

Each state has a StatusBadge color:
- proposed: info
- pending_review: warning
- approved: success
- executing: accent
- executed: success (final)
- rejected: danger
- failed: danger

**Step 2.4 — Frontend API**

Add to `frontends/wealth/src/lib/api/portfolios.ts` (or create if doesn't exist):

```typescript
export async function proposeRebalance(api, profile: string) {
  return api.post(`/portfolios/${profile}/rebalance/propose`);
}
export async function getPendingRebalances(api, profile: string) {
  return api.get(`/portfolios/${profile}/rebalance/pending`);
}
export async function approveRebalance(api, profile: string, id: string, rationale: string) {
  return api.post(`/portfolios/${profile}/rebalance/${id}/approve`, { rationale });
}
export async function executeRebalance(api, profile: string, id: string) {
  return api.post(`/portfolios/${profile}/rebalance/${id}/execute`);
}
```

---

## Task 3: Content Management Enhancement

### What exists

Backend (`backend/app/domains/wealth/routes/content.py`):
- `POST /content/outlooks` — 202 async generation
- `POST /content/flash-reports`
- `POST /content/spotlights`
- Approve/reject endpoints (verify existence)

Frontend (`frontends/wealth/src/routes/(team)/content/+page.svelte`):
- Lists content items (basic)

### What to enhance

**Step 3.1 — Status pipeline per content item**

```
generating → draft → pending_review → approved → published
```

Show as horizontal status pipeline in each content card.

**Step 3.2 — SSE progress for active generations**

When content is in `generating` state, show progress bar. Use `fetch()` + `ReadableStream` for SSE (NOT EventSource — auth headers needed).

```typescript
async function subscribeToProgress(jobId: string) {
  const res = await fetch(`/api/v1/jobs/${jobId}/stream`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  const reader = res.body.getReader();
  // Parse SSE events...
}
```

**Step 3.3 — Approve/reject inline**

ConsequenceDialog for approve/reject with rationale field.

**Step 3.4 — Download buttons**

For approved content, show download button (PDF/DOCX). Verify download endpoint exists or needs to be created.

---

## Files Changed

| File | Change |
|------|--------|
| `frontends/wealth/src/routes/(team)/macro/+page.svelte` | Enhance reviews section with StatusBadge + ConsequenceDialog |
| `frontends/wealth/src/routes/(team)/portfolios/[profile]/RebalancingTab.svelte` | New component |
| Portfolio detail page (find exact path) | Add Rebalancing tab |
| `frontends/wealth/src/routes/(team)/content/+page.svelte` | Enhance with status pipeline + SSE + approval |

## Acceptance Criteria

- [ ] Macro reviews: status badges + ConsequenceDialog + audit trail link
- [ ] Rebalancing: propose → pending → approve → execute workflow complete
- [ ] Rebalancing: before/after weight chart + CVaR impact MetricCards
- [ ] Content: status pipeline visible per item
- [ ] Content: SSE progress for active generations
- [ ] Content: approve/reject with ConsequenceDialog
- [ ] Content: download buttons for approved items
- [ ] All actions role-gated (ADMIN or INVESTMENT_TEAM)
- [ ] Dark mode functional
- [ ] `make check` passes (frontend)

## Gotchas

- ConsequenceDialog may be named differently — check `@netz/ui` or `packages/ui/` for actual component name (could be `ConfirmDialog`, `ConsequenceDialog`, etc.)
- Rebalancing Execute needs its OWN ConsequenceDialog (separate from Approve — executing triggers real changes)
- SSE: use `fetch()` + `ReadableStream`, NEVER `EventSource` (can't send auth headers)
- Verify backend approve/reject endpoints use `.with_for_update()` for race condition safety
- Content download endpoint may not exist — check backend routes first
- All mutations: `$state(saving)` + `invalidateAll()` + `finally` + dismissible error banner
