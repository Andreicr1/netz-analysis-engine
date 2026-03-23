# Fix 3 Phantom Frontend Calls + 8 UX Gaps

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Context

The endpoint coverage audit (`docs/audit/endpoint-frontend-coverage-audit.md` v4) identified:
- **3 phantom frontend calls** — the frontend calls API paths that don't exist in the backend
- **8 real UX gaps** — backend endpoints that need frontend surfaces (validated against `docs/system-map.md`)

This prompt fixes ALL phantoms and implements the 5 simplest UX gaps (the ones that add UI to existing pages). The 3 remaining gaps (fund-investment, credit actions, admin configs validate) require new components and are deferred.

---

## Part A — Fix 3 Phantom Frontend Calls

### Phantom 1: `GET /funds/{fundId}/documents/{documentId}/timeline`

**File:** `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.server.ts:14`

**Problem:** The frontend calls `/funds/${fundId}/documents/${documentId}/timeline` but no backend route matches this path. The closest backend route is `/funds/{fund_id}/deals/{deal_id}/ic-memo/timeline` (provenance.py) which requires a `deal_id` the document detail page doesn't have.

**Fix:** Remove the timeline fetch from the document detail page server load. The document detail page should show classification provenance and version history (which are already loaded from `/documents/${documentId}` and `/documents/${documentId}/versions`). A document-level timeline is not part of the system-map.

**Steps:**
1. Read `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.server.ts`
2. Remove the line that fetches `timeline` (line ~14)
3. Read `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.svelte`
4. Remove any reference to `data.timeline` — replace with the existing version history or remove the section entirely
5. Verify the page still loads correctly with `pnpm check` from `frontends/credit/`

### Phantom 2: `PUT /admin/tenants/{orgId}/branding`

**File:** `frontends/admin/src/lib/components/BrandingEditor.svelte:52`

**Problem:** The frontend calls `PUT /admin/tenants/${orgId}/branding` but the backend has no such route. The tenants router only has `PATCH /admin/tenants/{org_id}` for metadata updates.

**Fix:** Change the frontend to use `PATCH /admin/tenants/${orgId}` with the branding fields in the request body. The `update_tenant` endpoint already accepts partial updates.

**Steps:**
1. Read `frontends/admin/src/lib/components/BrandingEditor.svelte`
2. Read `backend/app/domains/admin/routes/tenants.py` — find the `update_tenant` handler and its schema to confirm it accepts branding fields
3. If the schema doesn't accept branding fields, read the `TenantUpdate` schema and add branding fields (colors, settings) to it
4. In `BrandingEditor.svelte`, change `api.put(\`/admin/tenants/${orgId}/branding\`, body)` to `api.patch(\`/admin/tenants/${orgId}\`, { branding: body })`
5. Test: `pnpm check` from `frontends/admin/`

**Alternative:** If `TenantUpdate` schema doesn't support branding fields, create a new route `PUT /admin/tenants/{org_id}/branding` in `tenants.py` instead of modifying the frontend. This is preferred if the branding payload is complex (nested colors, theme settings) and doesn't fit cleanly into the generic tenant update.

### Phantom 3: `GET /admin/configs/{orgId}?vertical=branding`

**File:** `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.server.ts:8`

**Problem:** The frontend calls `GET /admin/configs/${params.orgId}` where `params.orgId` is the tenant's org ID (a UUID). But the backend route is `GET /admin/configs/{vertical}/{config_type}` — two path segments, not one. Sending the UUID as the `{vertical}` segment results in a 404 or wrong data.

**Fix:** Change the frontend to call the correct path: `GET /admin/configs/branding/theme?org_id=${params.orgId}` (or whatever the correct `vertical` and `config_type` values are for branding config).

**Steps:**
1. Read `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.server.ts`
2. Read `backend/app/domains/admin/routes/configs.py` — find the `get_config` handler to understand expected path params and query params
3. Determine the correct `vertical` and `config_type` values for branding (likely `vertical="wealth"` or `vertical="common"`, `config_type="branding"`)
4. Fix the frontend call: `api.get(\`/admin/configs/${vertical}/${configType}\`, { org_id: params.orgId })`
5. Test: `pnpm check` from `frontends/admin/`

---

## Part B — Implement 5 UX Gaps (simplest first)

### Gap 1: CSV Instrument Import — `POST /instruments/import/csv`

**File to modify:** `frontends/wealth/src/routes/(team)/instruments/+page.svelte`

**Context:** The page already has a Yahoo import dialog (lines ~102-133). Add a CSV import option alongside it.

**Steps:**
1. Read the instruments page and the Yahoo import dialog code
2. Read `backend/app/domains/wealth/routes/instruments.py` — find the `import_from_csv` handler, its request schema (what CSV format it expects)
3. Add a "CSV Import" button next to the Yahoo import
4. Create a file upload dialog that accepts `.csv` files
5. On submit, call `api.upload('/instruments/import/csv', formData)` or `api.post('/instruments/import/csv', { csv_content })` — match the backend schema
6. Show success/error feedback + `invalidateAll()` on success
7. Test: `pnpm check` from `frontends/wealth/`

### Gap 2: Model Portfolio Stress Test — `POST /model-portfolios/{id}/stress`

**File to modify:** `frontends/wealth/src/routes/(team)/model-portfolios/[portfolioId]/+page.svelte`

**Context:** The system-map §8.1 confirms "stress test bar chart" on the model portfolio detail page. The page already shows backtest results — add a stress test trigger alongside.

**Steps:**
1. Read the model portfolio detail page
2. Read `backend/app/domains/wealth/routes/model_portfolios.py` — find the `trigger_stress` handler and its response schema
3. Add a "Run Stress Test" button (similar to the backtest button pattern)
4. On click, call `api.post(\`/model-portfolios/${portfolioId}/stress\`)`
5. Display results in a bar chart (use the same chart component pattern as backtest results)
6. Test: `pnpm check` from `frontends/wealth/`

### Gap 3: Investor Statement Generate — `POST .../investor-statements/generate`

**File to modify:** `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte`

**Context:** The reporting page already lists investor statements (`GET .../reports/investor-statements` at +page.server.ts:13). Add a generate trigger.

**Steps:**
1. Read the reporting page (both +page.server.ts and +page.svelte)
2. Read `backend/app/domains/credit/reporting/routes/reports.py` — find `generate_investor_statement` handler and schema
3. Add a "Generate Investor Statement" button in the investor statements section
4. On click, call `api.post(\`/funds/${fundId}/reports/investor-statements/generate\`, body)`
5. `invalidateAll()` on success to refresh the statement list
6. Test: `pnpm check` from `frontends/credit/`

### Gap 4: Investor Statement Download — `GET .../investor-statements/{id}/download`

**File to modify:** `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte`

**Context:** The statement list already renders rows. Add a download link per row.

**Steps:**
1. Read the reporting page, find where investor statements are rendered
2. Add a download button/link to each statement row
3. On click, call `api.getBlob(\`/funds/${fundId}/reports/investor-statements/${statementId}/download\`)` and trigger browser download
4. Follow the same pattern used for evidence pack PDF download (already at line ~138)
5. Test: `pnpm check` from `frontends/credit/`

### Gap 5: Deal Context Editing — `PATCH /pipeline/deals/{id}/context`

**File to modify:** `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`

**Context:** The deal detail page shows deal info in the Overview tab. Add an edit form for deal context fields.

**Steps:**
1. Read the deal detail page, find the Overview tab content
2. Read `backend/app/domains/credit/modules/deals/routes.py` — find `patch_deal_context` handler, its request schema (what fields can be patched)
3. Add an "Edit Context" button that opens an inline form or dialog
4. Populate with current deal context values
5. On save, call `api.patch(\`/pipeline/deals/${dealId}/context\`, { ...fields })` — note: this uses the new pipeline route, not the old fund-scoped route
6. `invalidateAll()` on success
7. Test: `pnpm check` from `frontends/credit/`

---

## Deferred (3 remaining gaps — separate prompt)

These require new components or pages, not modifications to existing ones:

- **Fund Investment** (`POST/GET .../assets/{id}/fund-investment`) — needs a new sub-tab in the portfolio page with LP commitment form
- **Credit Actions** (`POST/GET/PATCH /funds/{id}/actions`) — needs investigation: these overlap with portfolio actions (`/funds/{id}/portfolio/actions`). May be the same feature with different paths, or a separate module. Check system-map §5.5 before implementing.
- **Admin Configs Validate** (`POST /admin/configs/validate`) — needs a validate button wired into ConfigEditor's save flow

---

## Validation

After all changes:
```bash
# Frontend type checks
cd frontends/credit && pnpm check
cd frontends/wealth && pnpm check
cd frontends/admin && pnpm check

# Backend (should be unchanged, but verify)
make check
```

## Critical Rules

- Follow `CLAUDE.md` formatting rules — use `@netz/ui` formatters, never inline `toFixed()` / `Intl`
- Use `invalidateAll()` after mutations to refresh server-loaded data
- Use `ConsequenceDialog` for destructive actions (delete, generate)
- Use SSE via `createSSEStream` from `@netz/ui/utils` — never `EventSource`
- Match existing patterns in each page — don't introduce new component libraries or patterns
- Run `pnpm check` after each file change to catch type errors early
