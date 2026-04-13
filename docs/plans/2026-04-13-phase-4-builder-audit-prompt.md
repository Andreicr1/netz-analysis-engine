# Phase 4 Builder Scope Audit — Investigation Brief

**Date:** 2026-04-13
**Mission:** Pure investigation. NO code changes. Determine what Builder surface already exists vs what needs to be built.
**Context:** Backend is ~95% ready (construction_run_executor, optimizer cascade, TAA regime bands, stress scenarios, validation gates, narrative templater — all shipped and tested). Frontend is the gap.

## What to investigate

### A. Existing Builder routes and components

1. Does `frontends/wealth/src/routes/(terminal)/portfolio/builder/` or similar route exist?
2. Does `frontends/wealth/src/routes/(terminal)/portfolio/build/` exist?
3. What's in `frontends/wealth/src/lib/components/portfolio/`? List ALL files with one-line description.
4. Does a `LiveWorkbenchShell.svelte` exist? What does it do?
5. Any existing `TerminalAllocator.svelte`, `TerminalApprovedUniverse.svelte`, `TerminalBlotter.svelte`?
6. What about construction-specific components? `ConstructionNarrative`, `ConstructionCascade`, `StressPanel`?

### B. Backend endpoints the Builder frontend will consume

List all routes in `backend/app/domains/wealth/routes/model_portfolios.py` that the Builder needs:
- POST /model-portfolios/{id}/construction/run (trigger construction)
- GET /jobs/{id}/stream (SSE construction progress)
- GET /model-portfolios/{id}/construction/runs/{runId}/diff
- POST /model-portfolios/{id}/stress-test
- POST /model-portfolios/{id}/activate
- GET /allocation/{profile}/regime-bands (TAA)
- GET /allocation/{profile}/effective-with-regime (TAA)
- DELETE /jobs/{id} (cancel)

For each: does it exist? What's the response shape?

### C. Prior plan alignment

Read `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md` sections relevant to the Builder. What phases are defined? Which are already shipped? What overlaps with our master plan Phase 4?

### D. Shell integration

The Builder will be a `(terminal)/` route wrapped by `TerminalShell`. Verify:
- TopNav has a "BUILDER" tab (currently PENDING per Part C)
- The tab href matches whatever route the Builder will use
- LayoutCage compact density is appropriate for the Builder (data-dense surface)

### E. SSE streaming primitives

The Builder's construction run streams events via `createTerminalStream` (Part B). Verify:
- `createTerminalStream` is importable and functional
- The construction_run_executor publishes sanitized events (Sprint 2.C confirmed)
- The event types are defined and sanitized per the glossary

### F. What the Builder 3-column layout needs

Per master plan Appendix B §2.4:
- Col 1 (320px): Allocation Blocks (from TAA effective bands)
- Col 2 (flex): Approved Universe (filterable, draggable into blocks)
- Col 3 (360px): Construction Preview (proposed weights, constraints, risk, stress)

What components exist for each column? What needs to be built?

## Report Format

```markdown
# Phase 4 Builder Scope Audit — Findings

## A. Existing routes and components
<file inventory with status>

## B. Backend endpoints
<list with exists/missing status and response shape>

## C. Prior plan alignment
<summary of overlap>

## D. Shell integration
<TopNav tab status, route path>

## E. SSE primitives
<availability status>

## F. 3-column layout gap matrix
| Column | Component needed | Exists? | Gap |
```

## Constraints
- Zero file modifications
- Budget: 15-20 minutes
