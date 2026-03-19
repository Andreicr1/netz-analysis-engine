# UX Medium Priority — Instrument Import, Worker Triggers, Admin Inspect

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Context

An endpoint↔frontend coverage audit (`docs/audit/endpoint-frontend-coverage-audit.md`) identified three medium-priority gaps:

1. **Instrument import dialogs** — `import/yahoo` and `import/csv` endpoints exist but the instruments page uses phantom endpoints (`bulk-sync`, `search-external`)
2. **9 worker trigger endpoints** — no admin UI to manually trigger workers
3. **5 admin inspect endpoints** — DuckDB data lake inspection with no UI

**Dependency:** The high-priority prompt (`docs/prompts/ux-high-priority-coverage-prompt.md`) fixes the instrument phantom calls (C.1, C.2). This prompt builds on that by adding proper import dialogs. If the high-priority prompt was already executed, the phantom calls are fixed — just enhance the import UX. If not, fix them here too.

## Reference Files (read these first)

```
# Audit report
docs/audit/endpoint-frontend-coverage-audit.md

# High-priority prompt (may have been executed already)
docs/prompts/ux-high-priority-coverage-prompt.md

# Pages to modify
frontends/wealth/src/routes/(team)/instruments/+page.svelte
frontends/wealth/src/routes/(team)/instruments/+page.server.ts
frontends/admin/src/routes/(admin)/health/+page.svelte
frontends/admin/src/routes/(admin)/health/+page.server.ts (if exists)

# Backend endpoints (read for exact signatures)
backend/app/domains/wealth/routes/instruments.py    # POST /import/yahoo, POST /import/csv
backend/app/domains/wealth/routes/workers.py        # 9 POST /workers/run-* endpoints
backend/app/domains/wealth/schemas/instrument.py    # InstrumentImportYahoo schema
backend/app/domains/admin/routes/inspect.py         # 5 GET /inspect/* endpoints (or wherever they live)

# Admin health page (add worker triggers here)
frontends/admin/src/routes/(admin)/health/+page.svelte
frontends/admin/src/lib/components/ServiceHealthCard.svelte
frontends/admin/src/lib/components/WorkerLogFeed.svelte

# Shared UI
packages/ui/src/lib/components/  # DataTable, Card, Button, Dialog, etc.
```

---

## Part A: Instrument Import Dialogs

### A.1 Yahoo Finance Import Dialog

Enhance the "Bulk Sync" / "Search External" flow on the instruments page. Replace the phantom calls with proper import dialogs.

**File:** `frontends/wealth/src/routes/(team)/instruments/+page.svelte`

**Dialog: "Import from Yahoo Finance"**

Trigger: Button in page header (replace or enhance existing "Bulk Sync" button)

UI:
- Dialog title: "Import from Yahoo Finance"
- Textarea for tickers (comma or newline separated), placeholder: "SPY, AGG, GLD, VWO, ARKK"
- Helper text: "Enter up to 50 tickers. Instruments will be imported with metadata from Yahoo Finance."
- Character count / ticker count display
- "Import" button (primary) + "Cancel" button

On submit:
```typescript
// Parse tickers from textarea
const tickers = tickerInput
    .split(/[,\n\s]+/)
    .map(t => t.trim().toUpperCase())
    .filter(t => t.length > 0);

if (tickers.length === 0 || tickers.length > 50) {
    importError = "Enter between 1 and 50 tickers";
    return;
}

const result = await api.post("/instruments/import/yahoo", { tickers });
await invalidateAll();
```

Post-success:
- Show Toast: "{N} instruments imported"
- Close dialog
- Table refreshes automatically via `invalidateAll()`

Error handling:
- Display API error in dialog (not page-level)
- Keep dialog open on error so user can retry

### A.2 CSV Import Dialog

**Dialog: "Import from CSV"**

Trigger: Button in page header (new, next to Yahoo import)

UI:
- Dialog title: "Import from CSV"
- File picker (accept=".csv")
- Helper text: "CSV must have columns: ticker, name, asset_class, currency. Optional: isin, geography, block_id"
- Preview table showing first 5 rows after file selection (parse client-side with simple CSV parser)
- "Import" button (primary) + "Cancel" button

On submit:
```typescript
const formData = new FormData();
formData.append("file", csvFile);
const result = await api.upload("/instruments/import/csv", formData);
await invalidateAll();
```

Read `backend/app/domains/wealth/routes/instruments.py` to confirm:
- The CSV import endpoint path (should be `POST /instruments/import/csv`)
- Whether it accepts `multipart/form-data` or JSON
- What columns are required vs optional

### A.3 Update page header buttons

Replace the current buttons with clear import actions:

```svelte
<Button on:click={() => showYahooImport = true}>Import from Yahoo</Button>
<Button variant="outline" on:click={() => showCsvImport = true}>Import CSV</Button>
<Button variant="outline" on:click={() => showCreateDialog = true}>Add Manual</Button>
```

Remove the "Bulk Sync" and "Search External" buttons entirely (they were calling phantom endpoints).

---

## Part B: Worker Trigger Buttons in Admin

### B.1 Add trigger buttons to admin health page

**File:** `frontends/admin/src/routes/(admin)/health/+page.svelte`

The admin health page already has a "Workers" SectionCard with a DataTable showing worker status. Add a "Trigger" button column to each worker row.

**Worker definitions** (hardcode in frontend — these are stable):

```typescript
const WORKER_TRIGGERS = [
    { name: "ingestion", label: "NAV Ingestion (legacy)", endpoint: "/workers/run-ingestion", scope: "wealth" },
    { name: "instrument_ingestion", label: "Instrument NAV Ingestion", endpoint: "/workers/run-instrument-ingestion", scope: "wealth" },
    { name: "macro_ingestion", label: "Macro Data (FRED)", endpoint: "/workers/run-macro-ingestion", scope: "wealth" },
    { name: "benchmark_ingest", label: "Benchmark NAV", endpoint: "/workers/run-benchmark-ingest", scope: "global" },
    { name: "risk_calc", label: "Risk Calculation", endpoint: "/workers/run-risk-calc", scope: "wealth" },
    { name: "portfolio_eval", label: "Portfolio Evaluation", endpoint: "/workers/run-portfolio-eval", scope: "wealth" },
    { name: "screening_batch", label: "Screening Batch", endpoint: "/workers/run-screening-batch", scope: "wealth" },
    { name: "watchlist_check", label: "Watchlist Check", endpoint: "/workers/run-watchlist-check", scope: "wealth" },
    { name: "fact_sheet_gen", label: "Fact Sheet Generation", endpoint: "/workers/run-fact-sheet-gen", scope: "wealth" },
];
```

**Important:** Worker endpoints are on the **wealth** backend (`/api/v1/wealth/workers/run-*`), not the admin backend. The admin frontend API client may need to call the wealth API base URL. Check how the admin health page currently fetches from `/admin/health/workers` — it likely uses the same base URL that routes to the backend.

Read `backend/app/domains/wealth/routes/workers.py` to confirm:
- Each endpoint's exact path
- Which ones accept parameters (e.g., `lookback_days` for instrument_ingestion)
- Which ones need `org_id` (scope: wealth) vs global (benchmark_ingest)

**Per-row trigger button:**

Add a "Run" button column to the workers DataTable:
```svelte
{#each workers as worker}
    <tr>
        <!-- existing columns: name, status, last_run, duration_ms -->
        <td>
            <Button
                size="sm"
                variant="outline"
                disabled={worker.status === "running" || triggeringWorker === worker.name}
                on:click={() => triggerWorker(worker.name)}
            >
                {triggeringWorker === worker.name ? "Starting..." : "Run"}
            </Button>
        </td>
    </tr>
{/each}
```

**Trigger function:**
```typescript
async function triggerWorker(workerName: string) {
    const trigger = WORKER_TRIGGERS.find(w => w.name === workerName);
    if (!trigger) return;

    triggeringWorker = workerName;
    try {
        await api.post(trigger.endpoint, {});
        // Refresh worker status after short delay
        setTimeout(async () => {
            healthData = await api.get("/admin/health/workers");
            triggeringWorker = null;
        }, 2000);
    } catch (e) {
        triggerError = `Failed to trigger ${trigger.label}: ${e.message}`;
        triggeringWorker = null;
    }
}
```

**ConfirmDialog** for destructive workers (optional but recommended):
```svelte
<ConfirmDialog
    open={confirmTrigger !== null}
    title="Run Worker"
    message={`Trigger ${confirmTrigger?.label}? This may take several minutes.`}
    onConfirm={() => { triggerWorker(confirmTrigger.name); confirmTrigger = null; }}
    onCancel={() => confirmTrigger = null}
/>
```

### B.2 Worker parameter inputs

Some workers accept parameters. Add inline inputs where needed:

- **instrument_ingestion**: `lookback_days` (number input, default 30, range 1-1095)
- **Others**: no parameters needed

For instrument_ingestion, add a small inline input next to the Run button:
```svelte
{#if worker.name === "instrument_ingestion"}
    <Input type="number" min={1} max={1095} bind:value={lookbackDays} class="w-20" />
{/if}
```

And pass it: `api.post(trigger.endpoint + "?lookback_days=" + lookbackDays, {})`

---

## Part C: Admin Data Lake Inspection Page

### C.1 Create inspection page

**File:** `frontends/admin/src/routes/(admin)/inspect/+page.svelte`

The backend has 5 DuckDB inspection endpoints that provide data lake health metrics:

| Endpoint | Returns |
|----------|---------|
| `GET /admin/inspect/{org_id}/{vertical}/chunk-stats` | Chunk count, avg size, total docs |
| `GET /admin/inspect/{org_id}/{vertical}/coverage` | Documents with/without chunks |
| `GET /admin/inspect/{org_id}/{vertical}/embedding-audit` | Embedding dimension stats, model usage |
| `GET /admin/inspect/{org_id}/{vertical}/extraction-quality` | OCR quality metrics |
| `GET /admin/inspect/{org_id}/{vertical}/stale-embeddings` | Embeddings needing refresh |

**Layout:**

Page header: "Data Lake Inspection"

Controls bar:
- Tenant selector (dropdown from `GET /admin/tenants/`)
- Vertical selector: "credit" / "wealth" (toggle or dropdown)
- "Inspect" button → fetches all 5 endpoints in parallel

Results area (5 SectionCards):

**SectionCard 1: Chunk Statistics**
- MetricCards: total_documents, total_chunks, avg_chunks_per_doc, avg_chunk_size_chars

**SectionCard 2: Coverage**
- DataTable: document_id, title, has_chunks (boolean badge), chunk_count, last_processed
- Highlight rows where has_chunks=false (these need reprocessing)

**SectionCard 3: Embedding Audit**
- MetricCards: total_embeddings, models_in_use, dimension_mismatches
- DataTable (if dimension mismatches > 0): document_id, expected_dim, actual_dim, model

**SectionCard 4: Extraction Quality**
- MetricCards: avg_ocr_confidence, low_confidence_docs, empty_extraction_count
- DataTable for low-confidence docs: document_id, title, confidence, char_count

**SectionCard 5: Stale Embeddings**
- MetricCards: stale_count, oldest_embedding_date
- DataTable: document_id, embedding_date, current_model, embedded_model

**Server data loading:**

```typescript
// frontends/admin/src/routes/(admin)/inspect/+page.server.ts
export const load = async ({ parent }) => {
    const { api } = await parent();
    const tenants = await api.get("/admin/tenants/");
    return { tenants: tenants.data ?? tenants ?? [] };
};
```

The 5 inspection calls should be client-side (triggered by "Inspect" button), not server-side load, because they depend on user-selected tenant + vertical.

### C.2 Register in admin navigation

Add "Inspect" to admin sidebar between "Health" and "Config". Check the admin layout file for the navigation pattern.

---

## Verification

```bash
# Build all frontends
cd frontends/wealth && pnpm check
cd frontends/admin && pnpm check

# Verify no remaining phantom calls
grep -rn "bulk-sync\|search-external" frontends/wealth/src/
# Should return zero results
```

---

## Critical Rules

- Follow existing component patterns — use `@netz/ui` primitives
- Use `api.post()` / `api.get()` — never raw `fetch()` for backend calls
- Use `invalidateAll()` after mutations
- Use `Promise.allSettled()` in server loads
- Wrap all API calls in try/catch with error state
- Use ConfirmDialog for worker triggers and destructive actions
- Read backend route handlers before implementing — confirm exact paths, methods, payloads
- Admin API calls go to the same backend base URL — check the admin API client configuration

## What NOT to Do

- Do not modify backend code — this is frontend-only
- Do not create new API endpoints
- Do not add inline date/number formatting — use `@netz/ui` formatters
- Do not guess endpoint response shapes — read the backend schemas
- Do not hardcode org_ids — use the tenant selector for inspect page
