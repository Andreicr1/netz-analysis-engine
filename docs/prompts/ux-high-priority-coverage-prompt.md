# UX High Priority — Documents, Universe Approval, Phantom Fixes

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Context

An endpoint↔frontend coverage audit (`docs/audit/endpoint-frontend-coverage-audit.md`) identified three high-priority gaps:

1. **Wealth documents** — 6 backend endpoints, zero frontend UI
2. **Universe approval workflow** — 4 backend endpoints, zero frontend UI
3. **8 phantom frontend calls** — frontend calls endpoints that don't exist or have path mismatches

## Reference Files (read these first)

```
# Audit report
docs/audit/endpoint-frontend-coverage-audit.md

# Credit upload page (PATTERN TO REPLICATE for wealth documents)
frontends/credit/src/routes/(team)/funds/[fundId]/documents/upload/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/documents/+page.svelte

# Wealth existing pages (MODIFY these)
frontends/wealth/src/routes/(team)/instruments/+page.svelte           # Fix phantoms
frontends/wealth/src/routes/(team)/instruments/+page.server.ts
frontends/wealth/src/routes/(team)/model-portfolios/+page.svelte      # Fix phantoms
frontends/wealth/src/routes/(team)/screener/+page.svelte              # Fix phantom
frontends/wealth/src/routes/(team)/analytics/+page.svelte             # Fix phantom
frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte  # Fix phantom

# Wealth API client
frontends/wealth/src/lib/api/client.ts

# Backend schemas (for response types)
backend/app/domains/wealth/schemas/document.py      # WealthDocumentOut, WealthUploadUrlResponse, etc.
backend/app/domains/wealth/routes/documents.py      # 6 endpoints
backend/app/domains/wealth/routes/universe.py       # 4 endpoints
backend/app/domains/wealth/routes/instruments.py    # import/yahoo, import/csv
backend/app/domains/wealth/routes/model_portfolios.py  # construct, backtest (POST)
backend/app/domains/wealth/routes/screener.py       # POST /screener/run
backend/app/domains/wealth/routes/analytics.py      # GET /analytics/attribution/{profile}
backend/app/domains/wealth/routes/strategy_drift.py # GET /strategy-drift/{id}/export

# Shared UI components
packages/ui/src/lib/components/  # DataTable, Card, Button, Dialog, EmptyState, SectionCard, etc.
packages/ui/src/lib/utils/api-client.ts
```

---

## Part A: Wealth Document Upload & Listing (NEW pages)

### A.1 Create document list page

**File:** `frontends/wealth/src/routes/(team)/documents/+page.server.ts`

```typescript
// Load from GET /wealth/documents
export const load = async ({ parent }) => {
    const { api } = await parent();
    const [documents] = await Promise.allSettled([
        api.get("/wealth/documents", { limit: "100" }),
    ]);
    return {
        documents: documents.status === "fulfilled" ? documents.value : { items: [], total: 0 },
    };
};
```

**File:** `frontends/wealth/src/routes/(team)/documents/+page.svelte`

Replicate the credit document list pattern:
- PageHeader with title "Documents" and action buttons
- "Upload" button → navigates to `documents/upload`
- "Process Pending" button → POST `/wealth/documents/ingestion/process-pending` → shows IngestionProgress SSE
- DataTable with columns: title, filename, domain, ingestion_status, created_at
- Row click → navigates to `documents/{document_id}`
- Filter by: portfolio_id (optional dropdown), domain (optional dropdown)

### A.2 Create document upload page

**File:** `frontends/wealth/src/routes/(team)/documents/upload/+page.svelte`

Replicate the credit two-step upload flow exactly:

1. File picker (drag-and-drop + click)
2. Optional: portfolio_id selector, domain selector (dd_report, fact_sheet, compliance, other)
3. "Upload & Process" button:
   - POST `/wealth/documents/upload-url` → `{ upload_url, upload_id, blob_path }`
   - PUT to `upload_url` (raw fetch, SAS URL, headers: `x-ms-blob-type: BlockBlob`)
   - POST `/wealth/documents/upload-complete` → `{ job_id, version_id, document_id }`
   - Show `<IngestionProgress {jobId} />` SSE component
4. Error handling: display upload errors, file validation (max 100MB, allowed types)

**Important:** Check whether `upload_url` returned by the backend is a presigned R2 URL or an SAS URL. The wealth backend uses R2 (`StorageClient`), not Azure. The PUT headers may differ — read the backend `documents.py` upload-url handler to confirm the exact URL format.

### A.3 Create document detail page

**File:** `frontends/wealth/src/routes/(team)/documents/[documentId]/+page.server.ts`
**File:** `frontends/wealth/src/routes/(team)/documents/[documentId]/+page.svelte`

- Load from GET `/wealth/documents/{document_id}`
- Show: title, filename, content_type, domain, ingestion_status, created_at, blob_path
- Show version history if available
- "Re-process" button if status is FAILED

### A.4 Register in navigation

Add "Documents" to the wealth sidebar/navigation. Check how other menu items are registered (look at the layout file `frontends/wealth/src/routes/(team)/+layout.svelte`).

---

## Part B: Universe Approval Workflow (NEW page)

### B.1 Create universe page

**File:** `frontends/wealth/src/routes/(team)/universe/+page.server.ts`

```typescript
// Load approved universe + pending approvals
export const load = async ({ parent }) => {
    const { api } = await parent();
    const [universe, pending] = await Promise.allSettled([
        api.get("/universe"),
        api.get("/universe/pending"),
    ]);
    return {
        universe: universe.status === "fulfilled" ? universe.value : [],
        pending: pending.status === "fulfilled" ? pending.value : [],
    };
};
```

**File:** `frontends/wealth/src/routes/(team)/universe/+page.svelte`

Layout:
- PageHeader: "Investment Universe"
- Two tabs: "Approved" (default), "Pending Approval"

**Approved tab:**
- DataTable: instrument name, ticker, asset_class, block_id, approval_date, approved_by
- Badge for status (approved/rejected)
- Row count in tab badge

**Pending Approval tab:**
- DataTable: instrument name, ticker, asset_class, screener_score, screener_status
- Two action buttons per row:
  - "Approve" (green) → ConfirmDialog → POST `/universe/funds/{instrument_id}/approve` → `invalidateAll()`
  - "Reject" (red) → ConfirmDialog with rationale textarea → POST `/universe/funds/{instrument_id}/reject` → `invalidateAll()`
- Bulk actions: "Approve All Selected" / "Reject All Selected" (optional, lower priority)

### B.2 Register in navigation

Add "Universe" to sidebar between "Screener" and "Instruments" — it's the logical next step after screening.

---

## Part C: Fix Phantom Frontend Calls (8 fixes)

### C.1 — Instruments: `bulk-sync` → `import/yahoo`

**File:** `frontends/wealth/src/routes/(team)/instruments/+page.svelte`

**Line ~97:** Change `api.post("/instruments/bulk-sync", {})` to:
```typescript
// Collect all tickers from current instruments list
const tickers = instruments.filter(i => i.ticker).map(i => i.ticker);
await api.post("/instruments/import/yahoo", { tickers });
```

Update the ConfirmDialog message to explain this refreshes metadata from Yahoo Finance.

### C.2 — Instruments: `search-external` → `import/yahoo`

**Line ~118:** The "Search External" dialog currently calls `POST /instruments/search-external`. This endpoint doesn't exist. Replace with a client-side flow:

1. User types ticker(s) in the dialog input
2. On "Import" button: `await api.post("/instruments/import/yahoo", { tickers: [query] })`
3. On success: `invalidateAll()` to refresh the instruments list
4. Remove the two-step search→import pattern (we don't have a search endpoint)

Update the dialog to be an "Import from Yahoo Finance" dialog with a ticker input field (comma-separated).

### C.3 — Model Portfolios: `GET /backtest` → `POST /backtest`

**File:** `frontends/wealth/src/routes/(team)/model-portfolios/+page.svelte`

**Line ~128:** Change from GET to POST:
```typescript
// Before (broken):
backtestResult = await api.get(`/model-portfolios/${selectedPortfolio.id}/backtest`);

// After (correct):
backtestResult = await api.post(`/model-portfolios/${selectedPortfolio.id}/backtest`, {});
```

Read `backend/app/domains/wealth/routes/model_portfolios.py` to confirm the POST backtest endpoint exists and what it returns.

### C.4 — Model Portfolios: `allocate` → `construct`

**Line ~142:** Change endpoint path:
```typescript
// Before (broken):
await api.post(`/model-portfolios/${selectedPortfolio.id}/allocate`, {});

// After (correct):
await api.post(`/model-portfolios/${selectedPortfolio.id}/construct`, {});
```

Update the button label from "Build Portfolio" to "Construct Portfolio" (or keep "Build" — just fix the API path). Read the backend route to confirm the endpoint name and payload.

### C.5 — Model Portfolios: `rebalance` → remove or redirect

**Line ~157:** `POST /model-portfolios/{id}/rebalance` does not exist. The rebalance endpoint exists on the **portfolios** router: `POST /portfolios/{profile}/rebalance`.

Options:
- If the model portfolio has an associated profile, redirect: `await api.post(\`/portfolios/${selectedPortfolio.profile}/rebalance\`, {})`
- If not, remove the "Rebalance" button from the model-portfolios page and add a note directing users to the Portfolios page

Read the backend `model_portfolios.py` to check if there's a rebalance endpoint. If not, disable the button with a tooltip: "Rebalance available on the Portfolios page".

### C.6 — Screener: raw fetch → api.post

**File:** `frontends/wealth/src/routes/(team)/screener/+page.svelte`

**Line ~144:** Change from raw fetch to api client:
```typescript
// Before (broken — wrong path, bypasses auth):
const res = await fetch("/api/screener/run", { method: "POST", headers, body: JSON.stringify({}) });

// After (correct):
await api.post("/screener/run", {});
await invalidateAll();
```

Check `backend/app/domains/wealth/routes/screener.py` for the exact POST endpoint path and any required payload.

### C.7 — Analytics: attribution path mismatch

**File:** `frontends/wealth/src/routes/(team)/analytics/+page.svelte`

**Line ~339:** Change path to match backend:
```typescript
// Before (broken — passes fundId):
attributionData = await api.get(`/analytics/attribution/funds/${selectedFundId}/period`);

// After (correct — uses profile):
attributionData = await api.get(`/analytics/attribution/${selectedPortfolio}`);
```

Check `backend/app/domains/wealth/routes/attribution.py` for the exact endpoint signature. The backend expects a profile string, not a fund ID.

### C.8 — Portfolios: drift-history export path

**File:** `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte`

**Line ~396:** Change path to match backend:
```typescript
// Before (broken):
const res = await api.get(`/portfolios/${profile}/drift-history/export`);

// After (correct — if export exists on strategy-drift router):
const res = await api.get(`/analytics/strategy-drift/${driftInstrumentId}/export?format=csv`);
```

Check `backend/app/domains/wealth/routes/strategy_drift.py` for the exact export endpoint. The fallback at line ~404 already tries this path — make it the primary call.

---

## Verification

```bash
# Build wealth frontend (catches type errors)
cd frontends/wealth && pnpm check

# Verify no remaining phantom calls
grep -rn "bulk-sync\|search-external\|/allocate\|/api/screener" frontends/wealth/src/
# Should return zero results
```

---

## Critical Rules

- Follow existing component patterns — use `@netz/ui` primitives (DataTable, Card, Button, Dialog, EmptyState, SectionCard, PageHeader, Badge)
- Use `api.post()` / `api.get()` from the wealth API client — never raw `fetch()` for backend calls
- Use `invalidateAll()` after successful mutations to refresh server data
- Use `Promise.allSettled()` in `+page.server.ts` for error resilience
- Wrap all API calls in try/catch with `actionError` state for error display
- Use ConfirmDialog for destructive or state-changing actions (approve, reject, process)
- Always read the backend route handler before implementing — confirm exact path, method, payload, and response shape

## What NOT to Do

- Do not modify backend code — this is frontend-only
- Do not create new API endpoints
- Do not add new `@netz/ui` components — use existing ones
- Do not change the API client base URL or auth pattern
- Do not add inline `new Intl.NumberFormat` — use `@netz/ui` formatters
