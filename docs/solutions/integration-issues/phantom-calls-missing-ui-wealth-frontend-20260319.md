---
module: Wealth Frontend
date: 2026-03-19
problem_type: integration_issue
component: frontend_stimulus
symptoms:
  - "8 phantom frontend API calls hitting nonexistent or mismatched backend endpoints"
  - "6 wealth document backend endpoints with zero frontend UI"
  - "4 universe approval workflow endpoints with zero frontend UI"
root_cause: wrong_api
resolution_type: code_fix
severity: high
tags: [phantom-calls, sveltekit, wealth-frontend, endpoint-mismatch, documents, universe]
---

# Troubleshooting: Phantom Frontend API Calls + Missing Document & Universe UI in Wealth Frontend

## Problem

Endpoint-frontend coverage audit identified 8 phantom API calls in the wealth SvelteKit frontend (calls to nonexistent or path-mismatched backend endpoints), plus 10 backend endpoints (6 documents + 4 universe) with zero frontend UI coverage.

## Environment
- Module: frontends/wealth (SvelteKit "netz-wealth-os")
- Stack: SvelteKit + Svelte 5 runes + @netz/ui + FastAPI backend
- Affected Components: instruments, model-portfolios, screener, analytics, portfolios pages + missing documents/universe pages
- Date: 2026-03-19

## Symptoms

- `POST /instruments/bulk-sync` — endpoint does not exist (backend has `POST /instruments/import/yahoo`)
- `POST /instruments/search-external` — endpoint does not exist (no search endpoint)
- `GET /model-portfolios/{id}/backtest` — wrong method (backend is POST)
- `POST /model-portfolios/{id}/allocate` — wrong path (backend is `/construct`)
- `POST /model-portfolios/{id}/rebalance` — endpoint does not exist on model-portfolios router
- `fetch("/api/screener/run")` — raw fetch bypassing API client and auth, wrong path
- `GET /analytics/attribution/funds/{fundId}/period` — wrong path (backend is `GET /analytics/attribution/{profile}`)
- `GET /portfolios/{profile}/drift-history/export` — wrong path (backend is `GET /analytics/strategy-drift/{instrument_id}/export`)
- 6 wealth document endpoints (`upload-url`, `upload-complete`, `upload`, `process-pending`, list, detail) with zero frontend
- 4 universe endpoints (`list`, `pending`, `approve`, `reject`) with zero frontend

## What Didn't Work

**Direct solution:** Each phantom call was identified via grep audit against backend route definitions and fixed individually. The approach was systematic: read each backend route file to confirm exact path, method, and payload, then update the frontend call to match.

## Solution

### C.1 — instruments/bulk-sync → import/yahoo

```typescript
// Before (broken):
await api.post("/instruments/bulk-sync", {});

// After (correct):
const tickers = instruments.filter(i => i.ticker).map(i => i.ticker);
await api.post("/instruments/import/yahoo", { tickers });
```

### C.2 — instruments/search-external → import/yahoo dialog

Replaced the two-step search→import flow with a direct "Import from Yahoo Finance" dialog accepting comma-separated tickers:

```typescript
// Before (broken):
await api.post("/instruments/search-external", { query });

// After (correct):
const tickers = importTickers.split(",").map(t => t.trim().toUpperCase()).filter(Boolean);
await api.post("/instruments/import/yahoo", { tickers });
```

### C.3 — model-portfolios backtest GET → POST

```typescript
// Before: api.get(`/model-portfolios/${id}/backtest`)
// After:  api.post(`/model-portfolios/${id}/backtest`, {})
```

### C.4 — model-portfolios allocate → construct

```typescript
// Before: api.post(`/model-portfolios/${id}/allocate`, {})
// After:  api.post(`/model-portfolios/${id}/construct`, {})
```

### C.5 — model-portfolios rebalance removed

No rebalance endpoint exists on the model-portfolios router. Replaced ActionButton with a disabled Button + tooltip directing users to the Portfolios page where rebalance lives.

### C.6 — screener raw fetch → api.post

```typescript
// Before (broken — wrong path, bypasses auth):
const res = await fetch("/api/screener/run", { method: "POST", ... });

// After (correct):
const api = createClientApiClient(getToken);
await api.post("/screener/run", {});
```

### C.7 — analytics attribution path fix

```typescript
// Before: api.get(`/analytics/attribution/funds/${selectedFundId}/period`)
// After:  api.get(`/analytics/attribution/${selectedPortfolio}`)
```

### C.8 — drift export path fix

```typescript
// Before: api.get(`/portfolios/${profile}/drift-history/export`) with raw fetch fallback
// After:  api.getBlob(`/analytics/strategy-drift/${driftInstrumentId}/export?format=csv`)
```

### Part A — New document pages

Created 5 new files + 1 component:
- `(team)/documents/+page.server.ts` — loads via `GET /wealth/documents`
- `(team)/documents/+page.svelte` — document list with domain filter, process pending, upload link
- `(team)/documents/upload/+page.svelte` — two-step presigned URL upload with IngestionProgress SSE
- `(team)/documents/[documentId]/+page.server.ts` — loads single document detail
- `(team)/documents/[documentId]/+page.svelte` — metadata display with re-process action
- `lib/components/IngestionProgress.svelte` — SSE pipeline progress (adapted from credit)

### Part B — New universe page

Created 2 new files:
- `(team)/universe/+page.server.ts` — loads approved + pending via `GET /universe` and `GET /universe/pending`
- `(team)/universe/+page.svelte` — two-tab layout with approve/reject ConfirmDialog actions

### Navigation

Added "Universe", "Instruments", and "Documents" to `+layout.svelte` navItems.

## Why This Works

1. **Phantom calls** occurred because frontend pages were scaffolded with assumed endpoint paths during rapid UI development, before backend routes were finalized. The actual backend router prefixes and HTTP methods differed.
2. **Missing UI** existed because the wealth document and universe backend services were implemented in a later sprint than the initial frontend pages.
3. Each fix was verified by reading the actual FastAPI route decorator (`@router.get/post`, prefix in `APIRouter()`) to confirm exact path, method, and payload schema.

## Prevention

- **Always read backend route handler before implementing frontend API calls** — confirm exact path, method, payload, and response shape from the `APIRouter(prefix=...)` and `@router.get/post(...)` decorators.
- **Run endpoint-frontend coverage audit** periodically (`docs/audit/endpoint-frontend-coverage-audit.md`) to catch phantom calls early.
- **Never use raw `fetch()` for backend API calls** — always use the API client (`api.post/get/getBlob`) which handles auth headers, error typing, and base URL.
- **Use `svelte-check --threshold error`** after changes to catch type errors immediately.

## Related Issues

- See also: [endpoint-coverage-multi-agent-review-frontend-wiring-20260317.md](../architecture-patterns/endpoint-coverage-multi-agent-review-frontend-wiring-20260317.md) — the original 95-endpoint wiring sprint that preceded this fix
