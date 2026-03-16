---
status: pending
priority: p3
issue_id: "101"
tags: [code-review, simplicity, cleanup, frontend]
dependencies: []
---

# Cleanup: remove genuinely dead code from @netz/ui (~159 LOC)

## Problem Statement

The original simplicity review flagged ~607 LOC as unused. After domain-aware triage, only ~159 LOC is genuinely dead code (internal duplication). The rest is design system infrastructure for imminent features (i18n, SSE error UI, tooltips, formatting).

## Triage Results

### DELETE — genuinely dead (~159 LOC)

| Item | LOC | Why dead |
|---|---|---|
| `DataTableColumnHeader.svelte` | 56 | Exact duplicate of DataTable inline headers (lines 115-175). DataTable renders its own sorting UI — this standalone version is never needed |
| `DataTablePagination.svelte` | 73 | Exact duplicate of DataTable inline pagination (lines 216-277). DataTable renders its own pagination — this standalone version is never needed |
| `getBrandingFromCSS()` in branding.ts | ~30 | Reads CSS vars back into a BrandingConfig object. Flow is always config→CSS (via injectBranding), never the reverse. No use case exists |

### KEEP — design system infrastructure for imminent features

| Item | Why keep |
|---|---|
| `LanguageToggle.svelte` | i18n message files (en.json, pt.json) exist in both frontends with full translations. Product serves LatAm + global. Language switching is planned |
| `ConnectionLost.svelte` | SSE client has error/disconnected states but NO visual feedback to users. IC memo generation (~3min) and pipeline ingestion need this. Will wire when SSE error handling is complete |
| `Tooltip.svelte` | Every financial dashboard needs tooltips for KPI explanations, metric definitions. Current pages are MVPs — tooltips are imminent |
| `Sheet.svelte` | Overlay panel with backdrop (filters, settings). Different from ContextPanel (persistent side panel for deal detail). Both serve distinct UX patterns |
| `formatDateRange` | Report packs have period_start/period_end. Investor statements have period_month. Reporting pages will use this |
| `formatISIN` | Many funds and securities (especially fixed income, European, Brazilian) have no ticker — only ISIN. Credit vertical deals with private credit instruments where ISIN is the primary identifier |
| `formatCompact` | Dashboards show AUM as raw strings today. Compact notation (R$ 1.2B, $45.3M) is essential for financial UIs |
| `createSSEWithSnapshot` | Subscribe-then-snapshot eliminates event gaps during REST load. Current SSE usage is simple but pipeline ingestion will need gap-free event streams |

### ALREADY RESOLVED (no longer applicable)

| Item | Status |
|---|---|
| `createClerkHook` stub | Implemented in PR #46 — now has real JWKS verification |
| `createRootLayoutLoader` stub | Removed in PR #46 auth.ts rewrite |
| `injectBranding()` | Now actively used by both root layouts (PR #46 replaced {@html} with injectBranding) |
| Duplicate barrel exports | Still exists but low priority — utils/index.ts serves the subpath export |

## Recommended Action

Delete 3 items (~159 LOC). Update barrel exports in `packages/ui/src/lib/index.ts` to remove references to deleted components.

## Technical Details

**Files to delete:**
- `packages/ui/src/lib/components/DataTableColumnHeader.svelte`
- `packages/ui/src/lib/components/DataTablePagination.svelte`

**Files to edit:**
- `packages/ui/src/lib/utils/branding.ts` — remove `getBrandingFromCSS` function
- `packages/ui/src/lib/index.ts` — remove exports for deleted components and function
- `packages/ui/src/lib/utils/index.ts` — remove `getBrandingFromCSS` export

## Acceptance Criteria

- [ ] 2 dead components deleted
- [ ] `getBrandingFromCSS` removed from branding.ts
- [ ] Barrel exports updated
- [ ] No broken imports (grep for deleted names across entire repo)
- [ ] Design system components for imminent features preserved

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Code Simplicity Reviewer (ce:review PRs #37-#45)

### 2026-03-16 - Domain-Aware Triage

**By:** Andrei + Claude Code

**Actions:**
- Re-evaluated each "unused" component against domain context
- Identified that only 3 items are genuinely dead (internal duplication)
- 8 items reclassified as design system infrastructure for planned features
- Key domain insights: ISIN is primary identifier in private credit; i18n is planned for LatAm; SSE error UI is needed for long-running operations

**Learnings:**
- "Zero imports" ≠ "safe to delete" in a design system package
- Domain knowledge is critical for triage — simplicity reviewer flagged formatISIN as dead code, but private credit instruments often lack tickers
- Components serving imminent features (i18n, tooltips, SSE error states) should be kept even without current consumers

## Resources

- **PRs:** #37, #38 (Phases A, A.11)
- **PR #46:** Resolved createClerkHook stub, injectBranding now actively used
