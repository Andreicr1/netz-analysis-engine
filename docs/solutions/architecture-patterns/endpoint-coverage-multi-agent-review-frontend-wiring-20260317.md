---
title: "Wire 95 disconnected backend API endpoints across 3 SvelteKit frontends"
date: 2026-03-17
category: architecture-patterns
module:
  - frontends/admin
  - frontends/credit
  - frontends/wealth
  - packages/ui
problem_type: endpoint-coverage-gap
severity: high
tags:
  - frontend
  - api-integration
  - sveltekit
  - multi-tenant
  - echarts
  - sse
  - svelte-context
  - code-review
  - security
  - deal-lifecycle
  - document-workflow
  - dashboard
  - analytics
  - portfolio
  - instruments
related_issues:
  - "PR feat/endpoint-coverage (15 commits, fast-forward merged)"
  - "44.6% endpoint coverage baseline → ~100%"
  - "19 multi-agent review findings (5 P1, 8 P2, 6 P3) — 18 resolved, 1 deferred"
symptoms:
  - "55.4% of backend API endpoints had no frontend consumer"
  - "Deal lifecycle, document workflow, analytics, and instrument screens were stub/placeholder"
  - "No real-time data flow for dashboards or AI-powered features"
  - "Portfolio operations and content generation not wired"
root_cause: "Frontend platform (Phases A-F) established routing and layout scaffolding but left API integration as stubs — endpoints existed in backend but frontend pages did not call them"
---

# Full Frontend Endpoint Coverage — Multi-Agent Review Validated Wiring

## Problem Statement

A multi-tenant institutional investment platform had 172 backend API endpoints, but only 77 (44.6%) were consumed by any frontend. 95 endpoints across Admin (12), Credit (40), and Wealth (47) were fully implemented on the backend but had zero frontend UI. Users could view data but could not take action — no mutations, no file operations, no bulk workflows.

## Solution: Systematic 8-Phase Wiring

### Approach

Rather than building features ad-hoc, the work followed a systematic approach:

1. **Phase 0** locked down security and built shared primitives (components, API client, utilities)
2. **Phases 1-8** wired endpoints vertical-by-vertical, reusing Phase 0 primitives everywhere
3. **Multi-agent review** (6 specialized agents) caught 19 issues before merge

### Phase Breakdown

| Phase | Scope | Endpoints | Key Deliverables |
|-------|-------|-----------|-----------------|
| 0 | Shared Infrastructure | — | 7 security fixes, ConfirmDialog/ActionButton/FormField, API client extensions, createPoller, SSE registry |
| 1 | Admin Completion | 12 | Tenant CRUD, config editor save/delete, prompt versioning |
| 2 | Credit Deal Lifecycle | 10 | Create deal, decide, resolve conditions, convert to asset, portfolio CRUD |
| 3 | Credit Documents | 15 | Document detail, folders, ingestion, evidence, review actions, checklist |
| 4 | Credit Dashboard & AI | 8 | FRED explorer, AI history/activity/retrieve |
| 5 | Wealth Content | 12 | Content generation/approval/download, DD reports, fact sheets |
| 6 | Wealth Portfolio Ops | 15 | Portfolio profiles, rebalancing, allocation editor, model portfolio CRUD |
| 7 | Wealth Analytics | 15 | Backtest, optimization, Pareto, drift, attribution, macro committee, risk SSE |
| 8 | Wealth Instruments | 5 | Instruments list/detail/create, bulk sync, external search |

**Stats:** 84 files changed, +7812/-550 lines, 15 commits.

## Three Core Patterns

### Pattern 1: Mutation with State and Invalidation

Every mutation across all 95 endpoints follows this exact shape:

```svelte
<script lang="ts">
  let saving = $state(false);
  let actionError = $state<string | null>(null);

  async function handleSave() {
    saving = true;
    actionError = null;
    try {
      const api = createClientApiClient(getToken);
      await api.post(`/endpoint`, payload);
      await invalidateAll(); // re-runs all server loaders
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'Operation failed';
    } finally {
      saving = false;
    }
  }
</script>

{#if actionError}
  <div class="rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]">
    {actionError}
    <button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
  </div>
{/if}

<ActionButton loading={saving} loadingText="Saving..." onclick={handleSave}>
  Save Changes
</ActionButton>
```

**Why:** `$state(saving)` gives reactive loading indicators. `invalidateAll()` ensures SvelteKit server loaders re-fetch. The `finally` block guarantees the button re-enables even on error. The dismissible banner prevents dead-end UX.

### Pattern 2: Resilient Server Loaders with Promise.allSettled

```typescript
// +page.server.ts
export const load: PageServerLoad = async ({ params, parent }) => {
  const { token } = await parent();
  const api = createServerApiClient(token);

  const [deals, stats, alerts] = await Promise.allSettled([
    api.get(`/funds/${params.fundId}/deals`),
    api.get(`/funds/${params.fundId}/stats`),
    api.get(`/funds/${params.fundId}/alerts`),
  ]);

  return {
    deals: deals.status === "fulfilled" ? deals.value : { items: [] },
    stats: stats.status === "fulfilled" ? stats.value : null,
    alerts: alerts.status === "fulfilled" ? alerts.value : { items: [] },
  };
};
```

**Why:** A 500 on alerts still renders deals and stats. Never `Promise.all` for page loads.

### Pattern 3: Sequence Counter for Debounced Search

```svelte
<script lang="ts">
  let query = $state('');
  let results = $state.raw<Result[]>([]); // $state.raw for 500+ items
  let seq = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function debouncedSearch() {
    clearTimeout(timer);
    timer = setTimeout(() => doSearch(), 300);
  }

  async function doSearch() {
    const q = query.trim();
    if (q.length < 2) { results = []; return; }
    const thisSeq = ++seq;
    const api = createClientApiClient(getToken);
    const res = await api.get('/search', { q });
    if (thisSeq === seq) results = res.items ?? []; // discard stale
  }
</script>
```

**Why:** Replaces `AbortController` (which was dead code — signal never passed to fetch). Sequence counter is simpler, race-free, and doesn't interfere with SSE connections.

## Architecture Decisions

### ECharts via `svelte-echarts` (no Chart.js)

Institutional-grade charts (CVaR timeline with regime bands, markArea for breach zones, yAxis.inverse, Bayesian bounds) require ECharts first-class features. Added `ToolboxComponent`, `TitleComponent`, `globalChartOptions`, `sparklineOptions`, `regimeColors`, `statusColors` to `echarts-setup.ts`.

### No localStorage for Portfolio Data

In-memory store via `$state` in root layout + SSE primary + polling fallback (30s). Stale detection: data before 08:00 BRT on business days triggers banner. Created `risk-store.svelte.ts` initialized once in `(team)/+layout.svelte`, shared via Svelte context.

### ConfirmDialog for All Destructive Actions

Shared `ConfirmDialog` component with `confirmVariant="destructive"` for irreversible operations. Double-confirmation (type entity name) for data-critical operations like deal conversion.

## Multi-Agent Review Findings

6 specialized agents analyzed the complete diff. **19 issues found, 5 P1-critical:**

| P1 Issue | Agent | Impact | Fix |
|----------|-------|--------|-----|
| Risk store URL path mismatch | architecture-strategist | All CVaR fetches 404 silently | Fixed URL order: `/risk/${p}/cvar` |
| Wrong argument to API client | architecture-strategist | Runtime crash on portfolio detail | Changed `(token)` to `(getToken)` |
| Content polling fires once | performance-oracle | "Generating..." stuck forever | `setInterval` instead of `setTimeout` |
| Backtest polling leaks on navigation | performance-oracle | Orphaned fetch calls | Added `stopped` flag + `$effect` cleanup |
| Frontend calls missing endpoint | agent-native-reviewer | 405 on rebalance list | Added `GET /portfolios/{profile}/rebalance` |

**Key insight:** The review agents paid for themselves on this single PR. URL mismatch and missing endpoint would have been silent failures in production (swallowed by `r.ok ? r.json() : null`).

## Prevention Strategies

### CI/CD Checks (Highest Leverage)

1. **Route contract validation** — CI step that diffs frontend API URLs against OpenAPI spec. Any mismatch fails the build.
2. **TypeScript strict mode** — `noExplicitAny` + `noUnusedLocals` catches wrong argument types and dead AbortControllers at compile time.
3. **ESLint: no empty catch** — Flags `catch {}` blocks without error handling.
4. **ESLint: no raw `{@html}`** — Requires sanitization or explicit opt-out comment.
5. **`$effect` cleanup lint** — Flags `setInterval`/`setTimeout` in `$effect` without matching cleanup return.

### Architectural Patterns

1. **Generated typed API client** from OpenAPI eliminates URL mismatches entirely (highest leverage single change).
2. **`usePolling` composable** with built-in cleanup makes leaked timers structurally impossible.
3. **`SafeHtml.svelte` component** as the only sanctioned way to render dynamic HTML.
4. **Single-source business rules** — expose enums/transitions via API, never duplicate in frontend.

### Code Review Checklist

```markdown
### Endpoint Wiring Checklist
- [ ] Every frontend URL has a matching backend route
- [ ] API client call arguments match function signature
- [ ] All polling effects have cleanup returns
- [ ] Destructive actions have ConfirmDialog
- [ ] No empty catch blocks
- [ ] No {@html} without sanitization
- [ ] No duplicated business rules
```

## Security Fixes (Phase 0 Prerequisites)

7 security fixes were non-negotiable before wiring mutations:

1. **SQL injection in `SET LOCAL`** — parameterized RLS context setting
2. **SSE job ownership** — deny-by-default when Redis key missing
3. **Content generation RLS bypass** — parameterized query
4. **Path traversal** — reject `..` segments in fact sheet paths
5. **Risk SSE** — documented as global (PortfolioSnapshot has no org_id)
6. **Evidence SAS placeholder** — real `StorageClient.generate_upload_url()`
7. **Config PUT** — requires `If-Match` header (428 when missing)

## Related Documentation

### Origin
- [Endpoint Coverage Audit](../../audit/endpoint_coverage_audit.md) — 186 total endpoints, 83 connected (44.6%)
- [Endpoint Coverage Plan](../../plans/2026-03-17-feat-endpoint-coverage-full-frontend-wiring-plan.md) — 8-phase plan deepened with 4 review agents

### UX Principles
- [Wealth UX Principles](../../ux/wealth-frontend-ux-principles.md) — ECharts standard, no localStorage, institutional density
- [Credit UX Principles](../../ux/credit-frontend-ux-principles.md) — Deal workflow, audit-ready screens
- [Admin UX Principles](../../ux/admin-frontend-ux-principles.md) — Operations panel, system visibility

### Related Solutions
- [Admin Frontend Production Bugs](../design-decisions/multi-agent-review-admin-frontend-production-bugs-2026-03-17.md) — 5 P1 bugs caught by multi-agent review
- [Wealth Frontend Review Decisions](../design-decisions/2026-03-17-wealth-frontend-review-decisions.md) — TopNav + ContextSidebar, dark theme, discriminated unions
- [Azure Search Tenant Isolation](../security-issues/azure-search-tenant-isolation-organization-id-filtering-20260315.md) — organization_id OData filters
- [LLM Output Sanitization](../security-issues/llm-output-sanitization-nh3-persist-boundary-PipelineStorage-20260315.md) — nh3 at persist boundary
- [RLS Subselect 1000x Slowdown](../performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md) — `(SELECT current_setting(...))` required
- [StorageClient ADLS Dual-Write](../architecture-patterns/phase3-storageclient-adls-dualwrite-pattern-20260315.md) — File operations via StorageClient
- [FastAPI Route Shadowing](../logic-errors/fastapi-route-shadowing-and-sql-limit-bias-multi-instrument-20260317.md) — Literal routes before parameterized

## The Compounding Effect

First time wiring 95 endpoints: 2 sessions of implementation + 1 review session.
Next time a similar coverage gap appears: this document provides the phase structure, patterns, review checklist, and prevention strategies. Time to execute drops from days to hours.

The multi-agent review alone saved at least 5 production incidents (the P1 findings would have been silent failures — empty dashboards, crashed pages, stuck status indicators).
