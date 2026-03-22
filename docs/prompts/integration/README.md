# Full Backend-to-Frontend Integration — Session Backlog

**Plan:** `docs/plans/2026-03-21-feat-full-backend-frontend-integration-plan.md`
**Total:** 10 sessions, 21 items, ~17 endpoints, ~4 pages + ~8 enhanced

---

## Execution Order

| Session | File | Items | Effort | Dependencies |
|---------|------|-------|--------|--------------|
| **1A** | `phase-1a-enrich-region-score-and-drift-trigger.md` | 1.1 + 1.5 | ~120 LOC | None |
| **1B** | `phase-1b-nport-holdings-and-brochure-search.md` | 1.2 + 1.3 | ~350 LOC | None |
| **1C** | `phase-1c-momentum-signals-ui.md` | 1.4 | ~200 LOC | None |
| **2A** | `phase-2a-esma-worker-and-endpoints.md` | 2.1 + 2.2 | ~500 LOC | None |
| **2B** | `phase-2b-esma-frontend.md` | 2.3 | ~400 LOC | 2A |
| **3A** | `phase-3a-macro-raw-data-panels.md` | 3.1 | ~500 LOC | None |
| **3B** | `phase-3b-credit-market-data-page.md` | 3.2 | ~250 LOC | None |
| **3C** | `phase-3c-governance-workflows.md` | 3.3 + 3.4 + 3.5 | ~600 LOC | None |
| **4A** | `phase-4a-worker-management-dashboard.md` | 4.1 | ~500 LOC | None |
| **4B** | `phase-4b-prompt-versioning-and-pipeline-visibility.md` | 4.2 + 4.3 | ~200 LOC | None |
| **5A** | `phase-5a-engine-activation.md` | 5.1 + 5.2 + 5.3 | ~350 LOC | None |
| **5B** | `phase-5b-dead-code-removal.md` | 5.4 | ~50 LOC removed | None |

## Parallel Execution Matrix

Sessions with no dependencies can run in parallel (separate git branches):

```
Parallel Group 1:  1A, 1B, 1C          (Phase 1 — all independent)
Parallel Group 2:  2A                   (Phase 2 backend)
Sequential:        2B after 2A          (Phase 2 frontend needs backend)
Parallel Group 3:  3A, 3B, 3C          (Phase 3 — all independent)
Parallel Group 4:  4A, 4B              (Phase 4 — independent)
Parallel Group 5:  5A, 5B              (Phase 5 — independent)
```

## Gate After Each Session

Every session must end with:
```bash
make check  # lint + typecheck + test + architecture
```

## Cross-Cutting Rules (All Sessions)

- Backend: `async def` + `AsyncSession` + `response_model=` + `model_validate()`
- Global tables (BIS, IMF, Treasury, OFR, SEC, ESMA): no RLS, no `organization_id`
- Frontend: `@netz/ui` formatters only (no `.toFixed()`, no inline `Intl`)
- Frontend: `Promise.allSettled` in server loads (never `Promise.all`)
- Frontend: sequence counter for search debounce (not AbortController)
- Frontend: `fetch()` + `ReadableStream` for SSE (not EventSource)
- Frontend: Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`)
- Charts: ECharts via `@netz/ui` (not LayerChart)
- Workers: advisory lock with deterministic ID, Redis idempotency, `finally` unlock
- Import architecture: `make architecture` after cross-package integrations
