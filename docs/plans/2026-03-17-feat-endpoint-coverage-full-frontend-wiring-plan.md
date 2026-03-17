---
title: "feat: Full Frontend Endpoint Coverage — Wire 95 Disconnected Backend Endpoints"
type: feat
status: active
date: 2026-03-17
origin: docs/audit/endpoint_coverage_audit.md
deepened: 2026-03-17
---

# Full Frontend Endpoint Coverage — Wire 95 Disconnected Backend Endpoints

## Enhancement Summary

**Deepened on:** 2026-03-17
**Sections enhanced:** All 8 phases + cross-cutting concerns
**Review agents used:** architecture-strategist, security-sentinel, performance-oracle, best-practices-researcher (Svelte 5 runes + SvelteKit patterns)

### Key Improvements

1. **4 Critical security fixes added to Phase 0** — SQL injection in admin_middleware (f-string org_id), SSE job ownership bypass (default-allow on missing key), content generation RLS bypass, CSRF on multipart uploads
2. **3 P1 API client gaps identified** — `NetzApiClient` lacks blob download, file upload, and custom header support. All three are blocking for multiple phases.
3. **Phase restructuring** — Phase 7 split into 7A/7B/7C (overloaded), Phase 8 (Instruments) reordered before Phase 6 (Portfolio Ops) for testability
4. **Shared utilities added to Phase 0** — `createPoller`, `getBlob()`, `upload()`, per-request timeout override, global SSE connection counter
5. **Frontend Mutation Playbook** — Standardized patterns for forms, optimistic UI, polling, blob downloads, file uploads, debounced validation (10 concrete Svelte 5 code patterns)
6. **Pareto optimization safeguards** — Dedicated thread pool (max_workers=2), semaphore, 3-minute frontend timeout, duplicate submission prevention
7. **Risk SSE tenant isolation fix** — Channels must be scoped to `org_id` (currently global — cross-tenant data leak)

### Critical Security Findings (Must Fix Before Phase 1)

| ID | Severity | Finding |
|---|---|---|
| SEC-1 | CRITICAL | SQL injection via f-string in `admin_middleware.py` `SET LOCAL` |
| SEC-2 | CRITICAL | SSE `verify_job_owner` returns `True` when Redis key missing |
| SEC-3 | CRITICAL | Content generation background task uses f-string + raw session |
| SEC-4 | HIGH | Fact sheet download path traversal (`..` segments in `{path:path}`) |
| SEC-5 | HIGH | Risk SSE stream not scoped to organization (cross-tenant leak) |
| SEC-6 | HIGH | Document upload trusts client Content-Type, no magic-byte validation |
| SEC-7 | HIGH | Evidence upload uses hardcoded `SAS_TOKEN_PLACEHOLDER` |
| SEC-8 | HIGH | `If-Match` header optional on config PUT (optimistic locking bypass) |

### Architecture Decisions

| Decision | Rationale |
|---|---|
| Pessimistic UI as default | Optimistic updates only for checklist toggles; all other mutations wait for server response |
| SSE over polling when Redis pub/sub exists | Content generation should use SSE (infrastructure exists), not 10s polling |
| Dedicated Pareto thread pool | Prevents 45-135s runs from exhausting default `asyncio.to_thread` pool |
| Phase 7 split into 3 sub-phases | Original Phase 7 was 2-3x larger than other phases with unrelated subsections |
| 7B/7C independent of Phase 6 | Only 7A (backtest/optimize) has weak dependency on model portfolios. 7B/7C can run in parallel with anything. |
| Phase 8 before Phase 6 | Instruments CRUD must exist before portfolio rebalancing/analytics can be tested |
| Risk SSE in root layout | `$state` in modules doesn't survive SvelteKit route navigation. Use `setContext` in `(team)/+layout.svelte` |

---

## Overview

The endpoint coverage audit (2026-03-17) revealed that **only 44.6% of backend API endpoints are consumed by any frontend**. 95 endpoints across Admin (12), Credit (40), and Wealth (47) are fully implemented on the backend but have zero frontend UI. This plan builds all missing UI components to achieve full endpoint coverage.

## Problem Statement

The Netz Analysis Engine has a significant gap between backend capability and frontend exposure:

- **Admin (57% coverage):** Tenant CRUD is read-only (no create/edit/seed/assets). Config editor validates but cannot save. Prompt versioning is invisible.
- **Credit (50% coverage):** The entire deal lifecycle (create, decide, convert) has no UI. Document workflow is display-only (no actions). Portfolio assets/obligations cannot be created or modified.
- **Wealth (36% coverage):** Content generation has no triggers. Portfolio rebalancing workflow is completely absent. Analytics engines (backtest, optimization) are inaccessible. Macro committee approvals have no interface.

**Business impact:** Users can view data but cannot take action. The backend supports full CRUD and complex workflows, but the frontend only renders read operations. This blocks product adoption for any workflow requiring user input.

## Proposed Solution

Build the missing UI surfaces across all three frontends in 8 phases, prioritized by business value. Each phase is independently deployable.

### Architecture Principles

1. **Reuse `@netz/ui` components** — Button, Dialog, Input, Select, Textarea, ContextPanel, DataTable, Toast, Sheet, StatusBadge
2. **Follow established mutation pattern** — `createClientApiClient(getToken)` + `$state(saving/error)` + inline validation (see PromptEditor as reference)
3. **ConfirmDialog for destructive actions** — Replace `window.confirm()` with a shared component
4. **SSE via `createSSEStream`** — Not raw `fetch` for new real-time features
5. **All CSS via `var(--netz-*)` tokens** — No hex values in components (D4/D5 from design decisions)
6. **Dark/light theme support** — Admin defaults light, Credit light, Wealth dark

## Technical Approach

### Shared Infrastructure (Phase 0)

Before any frontend work, lock contracts and build shared primitives.

### Implementation Phases

---

#### Phase 0: Shared Infrastructure & Contracts

**Goal:** Build shared UI primitives needed by multiple phases. Lock contracts. Fix critical security vulnerabilities.

**Estimated effort:** Medium-Large (2-3 sessions) — SEC-5 (Risk SSE channel rescoping) requires coordinated changes to publishers and subscribers simultaneously; API client extensions touch a shared utility consumed by all 3 frontends; 7 security fixes involve infrastructure-level backend changes (tenancy middleware, job tracker, Redis channels).

##### 0.1 — New `@netz/ui` Components

**`packages/ui/src/lib/components/ConfirmDialog.svelte`**
Replaces `window.confirm()` across all frontends. Props: `open`, `title`, `message`, `confirmLabel`, `confirmVariant` (default/destructive), `onConfirm`, `onCancel`. Built on existing `Dialog.svelte`.

```svelte
<!-- Usage -->
<ConfirmDialog
  bind:open={showConfirm}
  title="Delete Override"
  message="This will revert to the global default. Continue?"
  confirmLabel="Delete"
  confirmVariant="destructive"
  onConfirm={handleDelete}
/>
```

**`packages/ui/src/lib/components/ActionButton.svelte`**
Loading-aware button for mutations. Props: extends `Button` + `loading: boolean`, `loadingText: string`. Disables on loading, shows spinner + text.

```svelte
<ActionButton onclick={save} loading={saving} loadingText="Saving...">
  Save Config
</ActionButton>
```

**`packages/ui/src/lib/components/FormField.svelte`**
Wrapper for label + input + error. Props: `label`, `error`, `required`, `hint`. Children via snippet.

```svelte
<FormField label="Deal Name" error={errors.name} required>
  <Input bind:value={form.name} />
</FormField>
```

Export all three from `packages/ui/src/lib/index.ts`.

##### 0.1b — NetzApiClient Extensions (BLOCKING — identified by architecture review)

The current `NetzApiClient` has three capability gaps that block multiple phases:

**1. `getBlob(path): Promise<Blob>`** — Authenticated blob download for PDF files. Current `handleResponse()` always calls `res.json()`. Needed by: Phase 5 (content PDF, DD report PDF, fact sheet PDF), Phase 7 (DD report download).

```typescript
// packages/ui/src/lib/utils/api-client.ts
async getBlob(path: string): Promise<Blob> {
  const res = await fetch(`${this.baseUrl}${path}`, {
    headers: await this.headers(),
    signal: AbortSignal.timeout(this.timeoutMs),
  });
  if (!res.ok) throw await this.handleError(res);
  return res.blob();
}
```

**2. `upload(path, formData: FormData): Promise<T>`** — Multipart file upload. Current `post()` hardcodes `Content-Type: application/json` and `JSON.stringify(body)`. Needed by: Phase 1 (branding assets), Phase 3 (document upload).

```typescript
async upload<T>(path: string, formData: FormData): Promise<T> {
  const h = await this.headers();
  delete h["Content-Type"]; // Let browser set multipart boundary
  const res = await fetch(`${this.baseUrl}${path}`, {
    method: "POST",
    headers: h,
    body: formData,
    signal: AbortSignal.timeout(this.timeoutMs),
  });
  return this.handleResponse<T>(res);
}
```

**3. Custom headers per request** — `If-Match` for optimistic locking. Add optional `headers` parameter to `put()`, `patch()`, `delete()`. Needed by: Phase 1 (config save), Phase 6 (rebalance approval).

```typescript
async put<T>(path: string, body?: unknown, extraHeaders?: Record<string, string>): Promise<T> {
  const h = { ...await this.headers(), ...extraHeaders };
  // ... rest of implementation
}
```

**4. Per-request timeout override** — Pareto optimization needs 180s vs default 15s.

```typescript
async post<T>(path: string, body?: unknown, options?: { timeoutMs?: number }): Promise<T> {
  const timeout = options?.timeoutMs ?? this.timeoutMs;
  // ... use timeout in AbortSignal.timeout(timeout)
}
```

##### 0.1c — Shared Utilities

**`packages/ui/src/lib/utils/poller.svelte.ts`** — Reusable polling with `$effect` cleanup.

```typescript
export function createPoller<T>(config: {
  fn: () => Promise<T>;
  intervalMs: number;
  maxDurationMs?: number; // Default 5 minutes
  shouldStop?: (result: T) => boolean;
}): { result: T | null; error: string | null; stop: () => void } {
  // Returns reactive state, auto-cleans up in $effect
}
```

Needed by: Phase 5 (content generation status), Phase 7 (backtest results).

**`packages/ui/src/lib/utils/sse-registry.svelte.ts`** — Global SSE connection counter (max 4 per tab, reserve 2 for API calls on HTTP/1.1).

##### 0.2 — TypeScript Types from OpenAPI

Run `make types` to generate response/request types from the backend OpenAPI schema. This gives frontends compile-time safety for all 95 endpoints.

> **Verified:** `make types` target exists in Makefile (line 74). Uses `npx openapi-typescript http://localhost:8000/openapi.json -o packages/ui/src/types/api.d.ts`. Requires running backend (`make serve`). Pre-requisite: `pnpm add -Dw openapi-typescript` if not already in devDependencies.

##### 0.3 — Route Manifest Verification

Verify all 95 backend endpoints are mounted in `main.py` by running:
```bash
python -c "from app.main import app; [print(f'{m} {r.path}') for r in app.routes for m in r.methods if m not in {'HEAD','OPTIONS'}]"
```

Cross-reference with the audit document. Fix any missing `include_router()` calls.

##### 0.4 — Backend Bug Fixes (Pre-requisites)

1. **Content generation failure path** — `backend/app/domains/wealth/routes/content.py` `_run_content_generation` exception handler must set `status = "failed"` and `error_message = str(e)` in the except branch. Without this, the UI cannot display generation failures.

2. **ContentSummary add `created_by`** — Required for self-approval prevention UX (disable "Approve" button for the creator).

3. **Phantom call cleanup** — Remove or stub `/funds/{fundId}/risk` and `/funds/{fundId}/nav` calls in wealth frontend `funds/[fundId]/+page.server.ts` (these 404 silently).

##### 0.5 — Critical Security Fixes (BLOCKING — identified by security audit)

These MUST be fixed before any phase begins. They are existing backend vulnerabilities that the new UI would expose to users:

1. **SQL injection in admin_middleware** — `backend/app/core/tenancy/admin_middleware.py:26` uses f-string interpolation for `org_id` in `SET LOCAL`. Replace with parameterized query: `text("SET LOCAL app.current_organization_id = :oid"), {"oid": str(org_id)}`. Apply same fix to `backend/app/core/tenancy/middleware.py:48`.

2. **SSE job ownership bypass** — `backend/app/core/jobs/tracker.py:60-74` `verify_job_owner` returns `True` when Redis key is missing (expired or never set). Change to `return False` (deny by default). Log warning when `owner is None`.

3. **Content generation RLS bypass** — `backend/app/domains/wealth/routes/content.py:386-389` background task uses f-string + raw session. Fix with parameterized query and re-validate `org_id` as UUID.

4. **Risk SSE cross-tenant leak** — `backend/app/domains/wealth/routes/risk.py:199-231` subscribes to global channels (`wealth:alerts:{profile}`) without tenant scoping. Fix: scope to `wealth:alerts:{org_id}:{profile}`. Update publishers to match.

5. **Fact sheet path traversal** — `backend/app/domains/wealth/routes/fact_sheets.py:170-206` accepts `..` in `{fact_sheet_path:path}`. Add: `if ".." in fact_sheet_path: raise HTTPException(403)`.

6. **Evidence upload SAS placeholder** — `backend/app/domains/credit/documents/routes/uploads.py:63` returns literal `?SAS_TOKEN_PLACEHOLDER`. Fix to use `StorageClient.generate_upload_url()`.

7. **Config PUT must require If-Match** — `backend/app/domains/admin/routes/configs.py:69-85` allows omitting `If-Match` header (defaults to version 0, bypassing optimistic locking). Return 428 Precondition Required when missing.

##### 0.6 — Frontend Mutation Playbook

Document these patterns as a code comment block in `packages/ui/src/lib/utils/PATTERNS.md` to ensure consistency across all 95 endpoint implementations:

| Pattern | Default | When to use |
|---|---|---|
| **Pessimistic save** | YES | All mutations — wait for server response before UI update |
| **Optimistic update** | NO | Only checklist toggles (Phase 3) — must handle rollback |
| **422 error mapping** | YES | Map Pydantic `detail[].loc[-1]` to field names for inline errors |
| **Form reset** | After success | Call `resetForm()` for edit-in-place; `goto()` for create |
| **Touched tracking** | YES | Show validation errors only after field blur, not on mount |
| **`$derived` aggregate** | YES | `canSubmit = $derived(allFilled && !hasErrors && !saving)` |
| **Blob download** | `getBlob()` + createObjectURL | All PDF downloads — revoke URL after click |
| **File upload** | `upload()` + FormData | All file inputs — validate magic bytes client-side |
| **Polling** | `createPoller` | Only when SSE not available — max 5 min duration |
| **SSE** | `createSSEStream` | Preferred for all real-time status — use registry |

**Success criteria:**
- [ ] ConfirmDialog, ActionButton, FormField added to `@netz/ui` and exported
- [ ] `NetzApiClient` extended with `getBlob()`, `upload()`, custom headers, per-request timeout
- [ ] `createPoller` and SSE registry utilities added
- [ ] TypeScript types generated from OpenAPI
- [ ] All 95 endpoints verified as mounted
- [ ] Content generation failure path fixed
- [ ] All 7 critical security fixes applied
- [ ] Frontend Mutation Playbook documented
- [ ] `make check` passes

---

#### Phase 1: Admin Frontend Completion (12 endpoints)

**Goal:** Complete the admin panel with full CRUD for tenants, config save/delete, and prompt versioning.

**Estimated effort:** Medium (1-2 sessions)

**Endpoints wired:**
1. `POST /admin/tenants/` — Create tenant
2. `PATCH /admin/tenants/{org_id}` — Edit tenant
3. `POST /admin/tenants/{org_id}/seed` — Seed tenant defaults
4. `POST /admin/tenants/{org_id}/assets` — Upload branding asset
5. `DELETE /admin/tenants/{org_id}/assets/{asset_type}` — Delete branding asset
6. `GET /admin/configs/invalid` — List invalid config overrides
7. `PUT /admin/configs/{vertical}/{config_type}` — Save config override
8. `DELETE /admin/configs/{vertical}/{config_type}` — Delete config override (revert)
9. `PUT /admin/configs/defaults/{vertical}/{config_type}` — Update global default
10. `GET /admin/prompts/{vertical}/{name}/versions` — Prompt version history
11. `POST /admin/prompts/{vertical}/{name}/revert/{version}` — Revert to version
12. `GET /assets/tenant/{org_slug}/{asset_type}` — Serve tenant asset (if not implicit)

##### 1.1 — Tenant CRUD

**`frontends/admin/src/routes/(admin)/tenants/+page.svelte`** — Add "Create Tenant" button + Dialog form.

Form fields (from `TenantCreate` schema): `name`, `slug`, `clerk_org_id`, `plan_tier`. On success → navigate to `/tenants/{orgId}`.

**`frontends/admin/src/routes/(admin)/tenants/[orgId]/+page.svelte`** — Add inline edit form for tenant metadata.

Fields: `name`, `plan_tier`, `status`. Use ActionButton for save. Add "Seed Defaults" button with ConfirmDialog.

**`frontends/admin/src/routes/(admin)/tenants/[orgId]/branding/+page.svelte`** — Wire asset upload/delete.

Upload: `<input type="file" accept="image/png,image/jpeg,image/x-icon">` (NO SVG — XSS risk, per admin brainstorm). Preview with `<img>` tag. ActionButton for upload. ConfirmDialog for delete.

Mutation pattern (all tenant writes):
```typescript
const api = createClientApiClient(getToken);
let saving = $state(false);
let error = $state<string | null>(null);

async function createTenant() {
  saving = true; error = null;
  try {
    const tenant = await api.post("/admin/tenants/", form);
    goto(`/tenants/${tenant.org_id}`);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed";
  } finally { saving = false; }
}
```

##### 1.2 — Config Editor Save/Delete

**`frontends/admin/src/lib/components/ConfigEditor.svelte`** — Add Save and Delete buttons.

- Save: `PUT /admin/configs/{vertical}/{config_type}` with `If-Match` header for optimistic locking
- Delete: `DELETE /admin/configs/{vertical}/{config_type}` with ConfirmDialog
- On 409 conflict: Toast "Config was modified by another user" + reload
- Defaults: new button "Update Default" → `PUT /admin/configs/defaults/{vertical}/{config_type}` with ConfirmDialog

**`frontends/admin/src/routes/(admin)/config/[vertical]/+page.svelte`** — Add "Invalid Overrides" tab/section.

New server load: `GET /admin/configs/invalid`. Display as warning list with link to each config editor.

##### 1.3 — Prompt Versioning

**`frontends/admin/src/lib/components/PromptEditor.svelte`** — Add version history panel.

- New tab/accordion "History" that loads `GET /admin/prompts/{vertical}/{name}/versions`
- Each version: date, diff preview, "Revert" button
- Revert: `POST /admin/prompts/{vertical}/{name}/revert/{version}` with ConfirmDialog
- On revert success: reload editor content

##### Research Insights — Phase 1

**Security (from security-sentinel):**
- Branding upload MUST validate magic bytes server-side (already done in `tenants.py`), but also add client-side validation before upload to avoid round-trip: check first 4 bytes for PNG (`\x89PNG`), JPEG (`\xFF\xD8\xFF`), ICO (`\x00\x00\x01\x00`)
- Config PUT must send `If-Match` header (Phase 0.5 makes it required on backend). On 428 response: show "Please reload to get current version"
- Asset upload uses `multipart/form-data` — add custom `X-Netz-Request: 1` header to force CORS preflight (CSRF defense-in-depth for multipart)
- Tenant create form: sanitize `slug` field (alphanumeric + hyphens only) client-side before POST

**Architecture (from architecture-strategist):**
- Config 409 conflict UX: on `ConflictError`, show Toast + reload editor content (not a diff merge UI — too complex for v1). The `setConflictHandler` on `NetzApiClient` is the hook for this.
- Invalid configs page should link directly to the config editor with the `vertical` and `config_type` pre-filled (not just a flat list)
- Prompt version history: load lazily (on tab click, not on page load) to avoid slowing the editor

**Svelte 5 patterns (from best-practices-researcher):**
- Dialog form: reset form state on open (not on close) to prevent flash of empty fields during close animation
- Debounced validation for config editor: 500ms `setTimeout`, clear on each keystroke, only call server when local JSON parse succeeds
- File upload: use `URL.createObjectURL()` for instant preview, revoke on component destroy

**Success criteria:**
- [ ] Create tenant form works with validation
- [ ] Edit tenant metadata saves via PATCH
- [ ] Seed tenant triggers with confirmation
- [ ] Asset upload restricted to PNG/JPEG/ICO, preview shown, magic bytes validated
- [ ] Asset delete with confirmation
- [ ] Config editor saves overrides (PUT) with `If-Match` header
- [ ] Config 409 conflict → Toast + reload (not silent failure)
- [ ] Config 428 → "Reload to get current version" message
- [ ] Config delete reverts to default with confirmation
- [ ] Update default config with confirmation
- [ ] Invalid configs list shown with links to editor
- [ ] Prompt version history loaded lazily on tab click
- [ ] Prompt revert works with confirmation
- [ ] `make check:all` passes

---

#### Phase 2: Credit Deal Lifecycle (10 endpoints)

**Goal:** Enable the full deal pipeline workflow — create, view, decide, resolve conditions, convert to asset.

**Estimated effort:** Medium (1-2 sessions)

**Endpoints wired:**
1. `POST /funds/{fund_id}/deals` — Create deal
2. `PATCH /funds/{fund_id}/deals/{deal_id}/decision` — Approve/reject deal
3. `PATCH /funds/{fund_id}/deals/{deal_id}/ic-memo/conditions` — Resolve IC condition
4. `POST /funds/{fund_id}/deals/{deal_id}/convert` — Convert deal to portfolio asset
5. `POST /funds/{fund_id}/assets` — Create portfolio asset (manual)
6. `POST /funds/{fund_id}/assets/{asset_id}/obligations` — Create obligation
7. `PATCH /funds/{fund_id}/obligations/{obligation_id}` — Update obligation
8. `PATCH /funds/{fund_id}/portfolio/actions/{action_id}` — Update portfolio action
9. `POST /funds/{fund_id}/report-packs/{pack_id}/generate` — Generate report pack
10. `POST /funds/{fund_id}/report-packs/{pack_id}/publish` — Publish report pack

##### 2.1 — Create Deal

**`frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte`** — Add "New Deal" button in PageHeader actions.

Opens Dialog with form fields from `DealCreate` schema: `borrower_name`, `deal_type`, `requested_amount`, `currency`, `sector`, `description`. On success → navigate to deal detail page.

##### 2.2 — Deal Actions (Detail Page)

**`frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`** — Add action buttons.

Layout: SectionCard with action buttons based on deal stage:

| Stage | Available Actions |
|---|---|
| SCREENING | Advance to ANALYSIS, Reject |
| ANALYSIS | Advance to IC_REVIEW, Reject |
| IC_REVIEW | Approve (with conditions), Reject |
| APPROVED | Convert to Asset |
| CONDITIONAL | Resolve Conditions → Convert |

Decision buttons: `PATCH /deals/{deal_id}/decision` with `{decision: "APPROVED"|"REJECTED"|"CONDITIONAL", comments: string}`.

IC Condition resolution: For each pending condition, render a checkbox + notes field. On check → `PATCH /ic-memo/conditions` with `{condition_id, resolved: true, notes}`.

Convert: ActionButton "Convert to Portfolio Asset" → `POST /deals/{deal_id}/convert` with ConfirmDialog. On success → navigate to portfolio page.

##### 2.3 — Portfolio Asset/Obligation CRUD

**`frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte`** — Add action buttons.

- "Add Asset" button → Dialog form → `POST /funds/{fund_id}/assets`
- Per-asset "Add Obligation" button → Dialog → `POST /assets/{asset_id}/obligations`
- Per-obligation "Edit" button → inline edit or Dialog → `PATCH /obligations/{obligation_id}`
- Per-action "Update Status" button → `PATCH /portfolio/actions/{action_id}`

##### 2.4 — Report Pack Actions

**`frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte`** — Add Generate/Publish buttons.

Per report pack row:
- "Generate" button → `POST /report-packs/{pack_id}/generate` with ActionButton (long-running)
- "Publish" button (only if generated) → `POST /report-packs/{pack_id}/publish` with ConfirmDialog

##### Research Insights — Phase 2

**Architecture (from spec-flow-analyzer):**
- Deal stage transitions need a defined state machine. The UI must know valid next-stages to render appropriate buttons. Query `DealCreate` schema via OpenAPI types to get the enum values. Backend `service.patch_stage` enforces valid transitions — the frontend should mirror these to disable invalid buttons.
- The "Convert to Asset" operation is irreversible. Use ConfirmDialog with `confirmVariant="destructive"` and require typing the borrower name to confirm (double-confirmation pattern for data-critical operations).

**Svelte 5 patterns (from best-practices-researcher):**
- IC condition checklist: use optimistic UI with per-item `inflightIds` Set to prevent double-toggle. Show "Saving..." per item, red border + "Retry" on failure, rollback on error.
- Deal create form: validate `requested_amount` as positive number client-side with `$derived` error. Use `touched` tracking to only show errors after field blur.
- Report pack generate is long-running — use ActionButton with loading state. Consider wiring SSE if backend publishes to Redis on completion.

**Security (from security-sentinel):**
- Deal decision comments field: sanitize on render (never `{@html}`). Comments are user input that could contain XSS payloads if rendered unsanitized.
- Report pack publish is a permission-elevated action — verify backend checks `require_fund_access()` with appropriate role.

**Success criteria:**
- [ ] Create deal form with validation, navigates to detail
- [ ] Deal decision buttons (approve/reject/conditional) with comments
- [ ] Decision buttons disabled for invalid stage transitions
- [ ] IC condition checkboxes with optimistic UI + rollback on error
- [ ] Convert deal to asset with double-confirmation (type borrower name)
- [ ] Create asset form
- [ ] Create obligation form
- [ ] Update obligation inline
- [ ] Update action status
- [ ] Report pack generate/publish buttons with role guard
- [ ] `make check:all` passes

---

#### Phase 3: Credit Document Workflow (15 endpoints)

**Goal:** Complete the document management workflow — detail views, folder management, evidence lifecycle, review actions, ingestion control.

**Estimated effort:** Medium-Large (2 sessions)

**Endpoints wired:**
1. `POST /documents/upload` — Alternative upload (non-SAS)
2. `GET /documents/root-folders` — List root folders
3. `GET /documents/{document_id}` — Document detail
4. `GET /documents/{document_id}/versions` — Document versions
5. `POST /documents/root-folders` — Create root folder
6. `POST /documents/ingestion/process-pending` — Process pending documents
7. `POST /funds/{fund_id}/evidence/upload-request` — Request evidence upload
8. `PATCH /funds/{fund_id}/evidence/{evidence_id}/complete` — Mark evidence uploaded
9. `GET /funds/{fund_id}/auditor/evidence` — Auditor evidence view
10. `POST /funds/{fund_id}/document-reviews` — Submit document for review
11. `POST /funds/{fund_id}/document-reviews/{review_id}/assign` — Assign reviewer
12. `POST /funds/{fund_id}/document-reviews/{review_id}/finalize` — Finalize review
13. `POST /funds/{fund_id}/document-reviews/{review_id}/resubmit` — Resubmit for review
14. `POST /funds/{fund_id}/document-reviews/{review_id}/ai-analyze` — Trigger AI analysis
15. `POST /funds/{fund_id}/document-reviews/{review_id}/checklist/{item_id}/check` + `uncheck` — Toggle checklist items

##### 3.1 — Document Detail Page

**New route: `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.server.ts`**

Loads: `GET /documents/{document_id}` + `GET /documents/{document_id}/versions`

**`+page.svelte`**: SectionCard with document metadata (type, classification, status, upload date). Versions tab with version history list. "Submit for Review" button → `POST /document-reviews`.

##### 3.2 — Folder Management

**`frontends/credit/src/routes/(team)/funds/[fundId]/documents/+page.svelte`** — Add folder sidebar/filter.

Server load adds: `GET /documents/root-folders`. Display as tree/list in sidebar. "Create Folder" button → Dialog → `POST /documents/root-folders`.

##### 3.3 — Ingestion Control

**`frontends/credit/src/routes/(team)/funds/[fundId]/documents/+page.svelte`** — Add "Process Pending" button.

ActionButton in PageHeader → `POST /documents/ingestion/process-pending`. Returns job_id → open IngestionProgress component with SSE.

##### 3.4 — Evidence Lifecycle

**New component: `frontends/credit/src/lib/components/EvidencePanel.svelte`**

Used within deal detail or standalone. "Request Upload" → Dialog form → `POST /evidence/upload-request`. Per-evidence "Mark Complete" → `PATCH /evidence/{evidence_id}/complete`.

##### 3.5 — Auditor View

**New route: `frontends/credit/src/routes/(team)/funds/[fundId]/documents/auditor/+page.server.ts`**

Loads: `GET /funds/{fund_id}/auditor/evidence`. DataTable with all evidence across documents, filterable by status.

##### 3.6 — Review Actions (Detail Page Enhancement)

**`frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`**

Add action bar with contextual buttons based on review status:

| Status | Actions |
|---|---|
| PENDING_ASSIGNMENT | Assign Reviewer (Select → POST assign) |
| UNDER_REVIEW | Decide (existing), AI Analyze (POST), Checklist toggles |
| REVISION_REQUESTED | Resubmit (POST) |
| APPROVED/REJECTED | Finalize (POST with ConfirmDialog) |

Checklist: Render each item with interactive checkbox → `POST .../check` on check, `POST .../uncheck` on uncheck. Optimistic UI update.

AI Analysis: ActionButton "Run AI Analysis" → `POST /ai-analyze`. Returns job_id → SSE progress.

##### Research Insights — Phase 3

**Security (from security-sentinel):**
- **Document upload MUST validate magic bytes** (SEC-6). The `/documents/upload` endpoint trusts client `Content-Type`. Add server-side magic-byte validation for PDF (`%PDF-`), DOCX (PK zip header), XLSX (PK zip). Client-side: check first bytes of `File` object before upload.
- **Evidence upload SAS token is broken** (SEC-7). Fix `uploads.py:63` to use `StorageClient.generate_upload_url()` instead of literal `?SAS_TOKEN_PLACEHOLDER`. This must be fixed before wiring the evidence lifecycle UI.
- Review checklist toggle endpoints accept arbitrary `item_id` — ensure backend validates that the item belongs to the specified review.

**Architecture (from architecture-strategist):**
- The document detail page (`/documents/[documentId]`) creates a new route that needs a parent layout load for fund context. Ensure the route is nested under `funds/[fundId]/documents/` to inherit the fund layout.
- Checklist toggles: use the optimistic UI pattern with `inflightIds` Set (same as Phase 2 IC conditions). Two endpoints (`/check` and `/uncheck`) should be abstracted into a single `toggleChecklistItem(id, checked)` function.

**Svelte 5 patterns:**
- For the interactive checklist, Svelte 5's fine-grained reactivity with `$state` arrays means mutating individual items via index is more performant than creating new arrays. Use: `items[idx] = { ...items[idx], checked: !items[idx].checked }`.
- AI analysis returns a `job_id` → use `createSSEStream` (not polling) to track progress, same as IC memo generation.

**Performance (from performance-oracle):**
- The auditor evidence DataTable may have hundreds of items across all documents for a fund. Use server-side pagination (`limit=50, offset=N`) from the start.

**Success criteria:**
- [ ] Document detail page with versions (nested under fund layout)
- [ ] Root folder listing and creation
- [ ] Process pending with SSE progress
- [ ] Evidence upload with real SAS URL (not placeholder)
- [ ] Evidence mark complete
- [ ] Document upload with magic-byte validation
- [ ] Auditor evidence view with pagination
- [ ] Submit document for review
- [ ] Assign reviewer from select
- [ ] Finalize review with confirmation
- [ ] Resubmit for review
- [ ] AI analysis trigger with SSE progress
- [ ] Interactive checklist toggles with optimistic UI
- [ ] `make check:all` passes

---

#### Phase 4: Credit Dashboard & AI (8 endpoints)

**Goal:** Add FRED/Macro explorer to dashboard and wire AI module.

**Estimated effort:** Small-Medium (1 session)

**Endpoints wired:**
1. `GET /dashboard/macro-history` — Macro history time-series
2. `GET /dashboard/macro-fred-series` — Single FRED series
3. `GET /dashboard/fred-search` — Search FRED indicators
4. `GET /dashboard/macro-fred-multi` — Multi-series FRED comparison
5. `POST /ai/query` — Alternative copilot query
6. `GET /ai/activity` — AI activity log
7. `GET /ai/history` — Query history
8. `POST /ai/retrieve` — Document retrieval

##### 4.1 — FRED/Macro Explorer

**New route: `frontends/credit/src/routes/(team)/dashboard/macro-explorer/+page.svelte`**

Or add as a tab/section within the existing dashboard. Components:

- **Search bar**: Input with debounce (300ms) → `GET /dashboard/fred-search?q={query}`
- **Series chart**: Select series → `GET /dashboard/macro-fred-series?series_id={id}&period={period}`
- **Multi-series comparison**: Select multiple → `GET /dashboard/macro-fred-multi?series_ids={ids}`
- **History view**: `GET /dashboard/macro-history?period={period}`
- **PeriodSelector** from `@netz/ui` for time range selection

##### 4.2 — AI Module Enhancement

**`frontends/credit/src/routes/(team)/copilot/+page.svelte`** — Enhance with history and activity.

- Add sidebar "History" tab: `GET /ai/history` → list of past queries with answers
- Add "Activity" tab: `GET /ai/activity` → log of AI operations
- Wire "Retrieve" for document search: `POST /ai/retrieve` → document list with relevance scores
- Existing `/ai/answer` continues as primary query endpoint

##### Research Insights — Phase 4

**Performance (from performance-oracle):**
- FRED proxy endpoints use `ThreadPoolExecutor(max_workers=4)`. Rapid period selector changes can pile up threads. Add 300ms debounce on the frontend (already planned) AND use `AbortController` to cancel stale FRED requests when the user changes selection.
- Multi-series FRED comparison can return large payloads. Consider caching results in `$state` keyed by series_ids to avoid re-fetching on tab switch.

**Svelte 5 patterns:**
- FRED search: debounced input with `$effect` cleanup pattern. Clear timer on each keystroke, only fire after 300ms idle.
- AI history sidebar: load lazily on tab click, not on page mount. Use `$state` to track which tab is active and `$effect` to trigger the load.

**Success criteria:**
- [ ] FRED search with 300ms debounce + AbortController for stale requests
- [ ] Single FRED series chart
- [ ] Multi-series comparison chart with client-side result caching
- [ ] Macro history time-series
- [ ] AI query history sidebar (lazy-loaded on tab click)
- [ ] AI activity log
- [ ] Document retrieval interface
- [ ] `make check:all` passes

---

#### Phase 5: Wealth Content & Report Generation (12 endpoints)

**Goal:** Enable content generation triggers, approval workflow, and report downloads across Wealth.

**Estimated effort:** Medium (1-2 sessions)

**Endpoints wired:**
1. `POST /content/outlooks` — Generate Investment Outlook
2. `POST /content/flash-reports` — Generate Flash Report
3. `POST /content/spotlights` — Generate Manager Spotlight
4. `POST /content/{content_id}/approve` — Approve content
5. `GET /content/{content_id}/download` — Download content PDF
6. `POST /dd-reports/funds/{fund_id}` — Generate DD Report
7. `GET /dd-reports/{report_id}` — DD Report full detail
8. `POST /dd-reports/{report_id}/regenerate` — Regenerate DD Report
9. `POST /fact-sheets/model-portfolios/{portfolio_id}` — Generate fact sheet
10. `GET /fact-sheets/{path}/download` — Download fact sheet PDF
11. `GET /fact-sheets/dd-reports/{report_id}/download` — Download DD as PDF
12. `GET /content/{content_id}/content-history` — Content generation history

##### 5.1 — Content Page Actions

**`frontends/wealth/src/routes/(team)/content/+page.svelte`** — Add generation triggers + approval.

Action bar with three generation buttons:
- "Generate Outlook" → `POST /content/outlooks`
- "Generate Flash Report" → `POST /content/flash-reports`
- "Generate Spotlight" → opens **fund picker Dialog** first (spotlight requires `instrument_id`), then `POST /content/spotlights?instrument_id={id}`

Per content item in list:
- "Approve" button (disabled if current user is creator — check `created_by`) → `POST /content/{content_id}/approve` with ConfirmDialog
- "Download PDF" link → `GET /content/{content_id}/download` (blob download)
- Status badge: draft → generating → ready → approved → archived
- **"failed" status** display (after Phase 0 backend fix)

Content generation is async (background task with semaphore limit 3). Show Toast "Generation started" on trigger. Poll list every 10s while any item is in "generating" status (or wire SSE if available).

##### 5.2 — DD Report Generation & Detail

**`frontends/wealth/src/routes/(team)/dd-reports/[fundId]/+page.svelte`** — Add "Generate Report" button.

ActionButton → `POST /dd-reports/funds/{fund_id}`. Returns `report_id` → connect to existing `GET /dd-reports/{report_id}/stream` SSE for progress.

**New route: `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.server.ts`**

Loads: `GET /dd-reports/{report_id}` (full report with chapters).

Page shows: chapter navigation, full chapter content, "Regenerate" button → `POST /dd-reports/{report_id}/regenerate` with ConfirmDialog, "Download PDF" → `GET /fact-sheets/dd-reports/{report_id}/download`.

##### 5.3 — Fact Sheet Generation & Download

**`frontends/wealth/src/routes/(investor)/fact-sheets/+page.svelte`** — Add generation + download.

Per model portfolio:
- "Generate Fact Sheet" button → `POST /fact-sheets/model-portfolios/{portfolio_id}` with ActionButton (202 Accepted, async)
- "Download PDF" link per fact sheet → `GET /fact-sheets/{path}/download`

##### Research Insights — Phase 5

**Security (from security-sentinel):**
- **XSS in LLM-generated content** (SEC-11). DD report chapters and content items contain LLM-generated Markdown. NEVER use `{@html rawContent}`. Use a sanitizing Markdown renderer: `marked` with DOMPurify post-processing, strip `javascript:` URLs. Define a `renderSafeMarkdown(md: string): string` utility in `@netz/ui`.
- **Self-approval prevention**: `ContentSummary` must include `created_by` (Phase 0.4 fix). Disable "Approve" button when `content.created_by === currentUserId`. Server enforces this with 403.
- **Spotlight requires `instrument_id`** — the current content page's "Spotlight" button sends no fund ID. Add a fund picker Dialog that opens before calling `POST /content/spotlights?instrument_id={id}`.
- **Rate limiting**: Add per-org rate limit (max 5 generation requests/minute) before wiring these triggers. Without it, a single user can exhaust the semaphore (limit 3) and block all other tenants.

**Performance (from performance-oracle):**
- Content generation uses `asyncio.create_task` (fire-and-forget). **Prefer SSE over polling**: the DD report generation already uses SSE streaming, and Redis pub/sub infrastructure exists. Wire a Redis publish at generation completion and use `createSSEStream` instead of 10s polling. If SSE is not feasible for v1, use `createPoller` with max 5-minute duration.
- **DD Report PDF generation holds DB connection during CPU work**. Fix: extract data first, close session, then run `generate_dd_report_pdf()` in `asyncio.to_thread()`. File: `fact_sheets.py:220-279`.
- Fact sheet generation returns 202 but runs synchronously via `asyncio.to_thread`. Semaphore blocks after 3 concurrent. 4th+ user's request hangs. Show "Server busy, please try again" on timeout (30s).

**Architecture (from architecture-strategist):**
- Content PDF download and fact sheet PDF download both need the new `NetzApiClient.getBlob()` method (Phase 0.1b). Use the blob download pattern: `fetch` → `res.blob()` → `URL.createObjectURL()` → hidden anchor `.click()` → `revokeObjectURL()`.
- DD Report detail page: chapter navigation should be a sidebar or tab strip, not a vertical scroll. Chapters can be long (5-10 pages of Markdown each).

**Success criteria:**
- [ ] Three content generation buttons (outlook, flash, spotlight with fund picker)
- [ ] Content approval with self-approval prevention (check `created_by`)
- [ ] Content PDF download via `getBlob()` + createObjectURL
- [ ] Failed generation status visible (after Phase 0.4 fix)
- [ ] DD Report generation with SSE progress
- [ ] DD Report detail page with chapter navigation
- [ ] DD Report regeneration with confirmation
- [ ] DD Report PDF download
- [ ] Fact sheet generation with "server busy" handling
- [ ] Fact sheet PDF download
- [ ] All Markdown rendered via sanitizing renderer (no `{@html}` with raw content)
- [ ] `make check:all` passes

---

#### Phase 6: Wealth Portfolio Operations (15 endpoints)

**Goal:** Enable the complete portfolio rebalancing workflow, allocation management, and model portfolio CRUD.

**Estimated effort:** Large (2-3 sessions)

**Endpoints wired:**
1. `GET /portfolios/{profile}` — Portfolio profile detail
2. `GET /portfolios/{profile}/snapshot` — Latest snapshot
3. `GET /portfolios/{profile}/history` — Snapshot history
4. `POST /portfolios/{profile}/rebalance` — Trigger rebalance
5. `GET /portfolios/{profile}/rebalance/{event_id}` — Rebalance event detail
6. `POST /portfolios/{profile}/rebalance/{event_id}/approve` — Approve rebalance
7. `POST /portfolios/{profile}/rebalance/{event_id}/execute` — Execute rebalance
8. `PUT /allocation/{profile}/strategic` — Update strategic allocation
9. `PUT /allocation/{profile}/tactical` — Update tactical allocation
10. `POST /model-portfolios` — Create model portfolio
11. `POST /model-portfolios/validate` — Validate model portfolio
12. `GET /model-portfolios/{id}/backtest` — Run backtest
13. `POST /model-portfolios/{id}/allocate` — Allocate to model
14. `POST /model-portfolios/{id}/rebalance` — Rebalance model
15. `GET /funds/{fund_id}/stats` + `performance` + `holdings` — Fund detail enrichment

##### 6.1 — Portfolio Profile Detail + Rebalancing

**New route: `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.server.ts`**

Loads: `GET /portfolios/{profile}`, `GET /portfolios/{profile}/snapshot`, `GET /portfolios/{profile}/history`

**`+page.svelte`**: MetricCards for current snapshot (NAV, return, volatility). History chart. Action bar:
- "Rebalance" ActionButton → `POST /portfolios/{profile}/rebalance` with ConfirmDialog

**Rebalance event list**: Loaded inline or as separate section. Each event shows:
- Status badge (pending/approved/executed)
- "View Detail" → loads `GET /portfolios/{profile}/rebalance/{event_id}`
- "Approve" button (pending only) → `POST .../approve` with ConfirmDialog. Handle 409 (concurrent approval attempt) with Toast.
- "Execute" button (approved only) → `POST .../execute` with ConfirmDialog. Uses `SELECT FOR UPDATE` on backend — handle 409.

##### 6.2 — Allocation Editor

**`frontends/wealth/src/routes/(team)/allocation/+page.svelte`** — Add edit mode.

Toggle "Edit Mode" button. In edit mode:
- Strategic tab: weight inputs per asset class → "Save" ActionButton → `PUT /allocation/{profile}/strategic`
- Tactical tab: tilt inputs → "Save" → `PUT /allocation/{profile}/tactical`
- Validation: weights must sum to 100%, each weight 0-100

##### 6.3 — Model Portfolio CRUD

**`frontends/wealth/src/routes/(team)/model-portfolios/+page.svelte`** — Add "Create" button.

Dialog form with: name, description, benchmark, target allocations → `POST /model-portfolios`.

Pre-validate with `POST /model-portfolios/validate` before submit (debounced, like ConfigEditor pattern).

**`frontends/wealth/src/routes/(team)/model-portfolios/[portfolioId]/+page.svelte`** — Add actions.

- "Backtest" button → `GET /model-portfolios/{id}/backtest` → display results in ContextPanel
- "Allocate" button → `POST /model-portfolios/{id}/allocate` with ConfirmDialog
- "Rebalance" button → `POST /model-portfolios/{id}/rebalance` with ConfirmDialog

##### 6.4 — Fund Detail Enrichment

**`frontends/wealth/src/routes/(team)/funds/[fundId]/+page.server.ts`** — Add missing data loads.

Add to parallel fetch: `GET /funds/{fund_id}/stats`, `GET /funds/{fund_id}/performance`, `GET /funds/{fund_id}/holdings`.

**`+page.svelte`**: Add Stats section (MetricCards), Performance chart, Holdings DataTable.

##### Research Insights — Phase 6

**Architecture (from architecture-strategist + spec-flow-analyzer):**
- **Phase dependency**: This phase requires instruments to exist for rebalancing/allocation to be testable. Either execute Phase 8 (Instruments) first, or document that seed data is required for testing.
- **Rebalance rejection flow is missing**: The state machine supports `pending → approved → executed` but has no `reject` or `cancel`. An IC member who decides NOT to approve has no action. Consider adding a `POST .../reject` endpoint, or at minimum a "Cancel" action that sets status back to `cancelled`.
- Rebalance approval uses `SELECT FOR UPDATE` — the 409 response on concurrent approval must be handled gracefully: Toast "Another IC member already approved this rebalance" + reload event list.
- Allocation weight editor: validate sum = 100% client-side with `$derived`. Show delta indicator: "Total: 98.5% (-1.5%)" in red when != 100%.

**Svelte 5 patterns:**
- Allocation edit mode: use a `$state(editing)` boolean to toggle between read and edit views. In edit mode, render weight inputs with `bind:value`. On "Cancel", reset to original server values via `$effect` re-sync.
- Model portfolio create: pre-validate with `POST /model-portfolios/validate` debounced at 500ms (same pattern as ConfigEditor). Show validation errors inline before allowing submit.

**Performance:**
- Portfolio snapshot history may be a long time-series. Use cursor-based pagination (by date) to prevent duplicate rows when new snapshots arrive between page loads. Fall back to offset/limit if backend doesn't support cursor.
- Fund detail enrichment adds 3 more `Promise.allSettled` calls. Total for fund page becomes 6 parallel calls. Consider reducing server load timeout to 8s for these non-critical endpoints.

**Success criteria:**
- [ ] Portfolio profile detail page with snapshot + history
- [ ] Rebalance trigger with confirmation
- [ ] Rebalance event detail view
- [ ] Rebalance approval with 409 handling ("already approved" Toast)
- [ ] Rebalance execution with confirmation
- [ ] Allocation strategic/tactical edit mode with weight validation (sum = 100%)
- [ ] Allocation delta indicator when sum != 100%
- [ ] Create model portfolio with debounced pre-validation
- [ ] Model portfolio backtest display
- [ ] Model portfolio allocate/rebalance
- [ ] Fund detail with stats, performance, holdings (non-critical, graceful fallback)
- [ ] `make check:all` passes

---

#### Phase 7: Wealth Analytics & Intelligence (15 endpoints)

> **Note (from architecture review):** This phase should be split into 3 sub-phases (7A/7B/7C) to reduce complexity. The original Phase 7 is 2-3x larger than other phases with architecturally unrelated subsections.

**Goal:** Expose analytical engines — backtest, optimization, macro committee, strategy drift, attribution, correlation, and risk SSE.

**Estimated effort:** Medium-Large (2 sessions)

**Endpoints wired:**
1. `POST /analytics/backtest` — Run backtest
2. `GET /analytics/backtest/{run_id}` — Backtest results
3. `POST /analytics/optimize` — Portfolio optimization
4. `POST /analytics/optimize/pareto` — Multi-objective Pareto optimization
5. `GET /analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` — Pair correlation
6. `POST /analytics/strategy-drift/scan` — Trigger drift scan
7. `GET /analytics/strategy-drift/{instrument_id}` — Instrument drift detail
8. `GET /analytics/attribution/funds/{fund_id}/period` — Performance attribution
9. `POST /macro/reviews/generate` — Generate macro committee report
10. `PATCH /macro/reviews/{review_id}/approve` — CIO approve
11. `PATCH /macro/reviews/{review_id}/reject` — CIO reject
12. `GET /risk/stream` — Risk SSE stream
13. `GET /screener/runs/{run_id}` — Screener run detail
14. `GET /screener/results/{instrument_id}` — Instrument screening history
15. `POST /analytics/strategy-drift/scan` — Strategy drift scan

##### 7.1 — Analytics Page Enhancement

**`frontends/wealth/src/routes/(team)/analytics/+page.svelte`** — Add backtest + optimization sections.

**Backtest panel**: Form with parameters (start_date, end_date, benchmark, cv) → `POST /analytics/backtest`. If response status is "pending", poll `GET /analytics/backtest/{run_id}` every 5s (max 60s). Display results in chart + DataTable.

**Optimization panel**: Form → `POST /analytics/optimize`. Display efficient frontier chart.

**Pareto panel** (advanced): Form → `POST /analytics/optimize/pareto`. **Warning: 45-135s runtime.** Use 3-minute fetch timeout. Show progress spinner with "This may take up to 2 minutes" message. Prevent duplicate submissions.

**Pair correlation**: Click any cell in correlation matrix → opens ContextPanel with `GET /analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` time-series chart.

##### 7.2 — Strategy Drift Enhancement

**`frontends/wealth/src/routes/(team)/risk/+page.svelte`** — Add drift scan trigger + detail.

- "Run Drift Scan" ActionButton → `POST /analytics/strategy-drift/scan` with ConfirmDialog
- Per drift alert row: click → ContextPanel with `GET /analytics/strategy-drift/{instrument_id}` detail

##### 7.3 — Attribution Page

**New route: `frontends/wealth/src/routes/(team)/analytics/attribution/+page.svelte`**

Or add as tab in existing analytics page. Period selector → `GET /analytics/attribution/funds/{fund_id}/period`. Display attribution breakdown chart (contribution by holding).

##### 7.4 — Macro Committee Actions

**`frontends/wealth/src/routes/(team)/macro/+page.svelte`** — Add generation + approval.

- "Generate Committee Report" ActionButton → `POST /macro/reviews/generate`
- Per review: "Approve" / "Reject" buttons (CIO role only) → `PATCH /macro/reviews/{review_id}/approve` or `/reject`

##### 7.5 — Risk SSE Stream

**Architecture decision: SSE connection must live in the root layout, not in individual pages.**

Dashboard (`/dashboard`) and Risk (`/risk`) are in different route trees. A `$state` in a module or page component does not survive navigation between routes. If each page creates its own SSE connection, navigating between them opens two connections (exactly what the SSE registry tries to prevent).

**Solution:** Create a shared SSE context in the wealth app root layout:

**`frontends/wealth/src/routes/(team)/+layout.svelte`** — Initialize risk SSE at the layout level.

```typescript
// In the (team) layout — parent of both dashboard and risk
import { setContext } from "svelte";
import { createSSEStream } from "@netz/ui/utils";

const riskAlerts = $state<RiskAlert[]>([]);
const sse = createSSEStream<RiskAlert>({
  url: `${API_BASE}/api/v1/risk/stream`,
  getToken,
  onEvent: (alert) => { riskAlerts = [alert, ...riskAlerts].slice(0, 50); },
});

setContext("netz:riskAlerts", () => riskAlerts);

// Connect/disconnect based on whether any child page needs it
// The SSE registry (Phase 0.1c) manages the connection lifecycle
```

**Child pages** (`dashboard/+page.svelte`, `risk/+page.svelte`):
```typescript
const getRiskAlerts = getContext<() => RiskAlert[]>("netz:riskAlerts");
const alerts = $derived(getRiskAlerts());
```

This ensures a single SSE connection shared across all pages under `(team)/`, with the connection managed at the layout level where it persists across navigation.

Handle 429 (max connections) with fallback message. (see todo: `todos/138-pending-p2-dashboard-sse-risk-alerts-not-wired.md`)

##### 7.6 — Screener Detail Enhancement

**`frontends/wealth/src/routes/(team)/screener/+page.svelte`** — Add drill-downs.

- Per screening run row: click → ContextPanel with `GET /screener/runs/{run_id}` detail
- Per instrument row: click → ContextPanel with `GET /screener/results/{instrument_id}` screening history

##### Research Insights — Phase 7

**Performance (from performance-oracle — CRITICAL):**
- **Pareto optimization blocks default thread pool** (45-135s per run). `asyncio.to_thread` uses the default `ThreadPoolExecutor` (max 32 workers). 8-10 concurrent Pareto runs would exhaust ALL threads, blocking content generation, CVaR computation, and PDF generation. **Fix**: Create a dedicated `ThreadPoolExecutor(max_workers=2)` for Pareto. Add an asyncio semaphore (limit 2). Return 429 when at capacity.
- **Frontend timeout**: `NetzApiClient` default is 15s. Pareto needs 180s. Use the per-request timeout override from Phase 0.1b: `api.post("/analytics/optimize/pareto", data, { timeoutMs: 180_000 })`.
- **Duplicate submission prevention**: Disable the "Run Pareto" button immediately on click. Show "This may take up to 2 minutes" message. Use `AbortController` to cancel if user navigates away.

**Security (from security-sentinel):**
- **Risk SSE must be scoped to org_id** (SEC-5). Currently subscribes to global channels. This is fixed in Phase 0.5. After the fix, the frontend SSE URL should include profile but NOT org_id (org_id is injected server-side from JWT).
- Macro committee approve/reject: verify backend checks CIO role. The frontend should only render these buttons when `user.role === "CIO"` (from Clerk JWT claims). Client-side gating is UX only — server enforces.
- Backtest/optimization results may contain sensitive portfolio data. Ensure read endpoints have `require_fund_access()` or equivalent.

**Architecture (from architecture-strategist):**
- **Split Phase 7 into sub-phases**:
  - **7A**: Backtest + Optimization + Pareto (compute-heavy, shared timeout patterns)
  - **7B**: Strategy Drift + Attribution + Correlation pair (read-heavy analytics drill-downs)
  - **7C**: Macro Committee + Risk SSE + Screener detail (governance + real-time)
- Pair correlation drill-down: clicking a cell in the existing correlation matrix should open a ContextPanel with the pair time-series. Use the existing `ContextPanel` component — don't create a new one.
- Risk SSE must live in `(team)/+layout.svelte` (root layout), NOT in individual pages. A module-level `$state` does not survive SvelteKit route navigation. Use `setContext` in layout + `getContext` in child pages. See section 7.5 for the full pattern.

**Svelte 5 patterns:**
- Backtest polling: if response status is "pending", use `createPoller` with 5s interval, max 60s. Display results in chart + DataTable when complete.
- Attribution chart: use a horizontal bar chart showing contribution by holding. PeriodSelector for time range.

**Success criteria:**
- [ ] Backtest form with `createPoller` for pending results (5s interval, 60s max)
- [ ] Optimization form with efficient frontier chart
- [ ] Pareto optimization with 180s timeout, duplicate prevention, 429 handling
- [ ] Pareto uses dedicated thread pool (backend fix)
- [ ] Pair correlation drill-down in ContextPanel
- [ ] Strategy drift scan trigger with confirmation
- [ ] Per-instrument drift detail in ContextPanel
- [ ] Performance attribution chart with period selector
- [ ] Macro committee report generation
- [ ] Macro review approve/reject (CIO role gated)
- [ ] Risk SSE live alerts wired (org-scoped after Phase 0.5 fix)
- [ ] Risk SSE in `(team)/+layout.svelte` via `setContext`, consumed by dashboard + risk via `getContext`
- [ ] Screener run detail in ContextPanel
- [ ] Instrument screening history
- [ ] `make check:all` passes

---

#### Phase 8: Wealth Instruments Management (5 endpoints)

> **Note (from architecture review):** Consider executing this phase BEFORE Phase 6 (Portfolio Operations), since instruments are a prerequisite for testing rebalancing, allocation, and analytics features.

**Goal:** Build instruments management page for the wealth vertical.

**Estimated effort:** Small (1 session)

**Endpoints wired:**
1. `GET /instruments` — List instruments
2. `GET /instruments/{instrument_id}` — Instrument detail
3. `POST /instruments` — Create instrument
4. `POST /instruments/bulk-sync` — Bulk sync from external source
5. `POST /instruments/search-external` — Search external data providers

##### 8.1 — Instruments Page

**New route: `frontends/wealth/src/routes/(team)/instruments/+page.server.ts`**

Loads: `GET /instruments?limit=500`

**`+page.svelte`**: DataTable with search filter. Columns: ticker, name, type, currency, last_price, exchange.

- "Add Instrument" button → Dialog → `POST /instruments` with form (ticker, name, asset_class, currency)
- "Bulk Sync" button → `POST /instruments/bulk-sync` with ActionButton + ConfirmDialog
- "Search External" → search input → `POST /instruments/search-external` with results in DataTable → "Import" button per result → `POST /instruments`
- Row click → ContextPanel with `GET /instruments/{instrument_id}` detail

##### Research Insights — Phase 8

**Performance (from performance-oracle):**
- Instruments list loads 500+ items. `@tanstack/svelte-table` handles this fine with client-side filtering/sorting at current scale. For future-proofing: add server-side pagination (`offset`/`limit`) when list exceeds 500 items.
- External search (`POST /instruments/search-external`) may have variable latency (depends on external provider). Use ActionButton with loading state + 10s timeout.
- Bulk sync is a potentially long operation. Use ActionButton + ConfirmDialog. If sync takes > 5s, consider polling for completion status.

**Architecture:**
- Instrument detail in ContextPanel: reuse the existing `ContextPanel` component from `@netz/ui`. Show: ticker, name, asset class, currency, last price, exchange, holdings count.
- "Search External → Import" flow: search results should be displayed in a separate DataTable below the search input. Each result row has an "Import" ActionButton that calls `POST /instruments` with the external data pre-filled.
- Use `$state.raw` (not `$state`) for the 500+ instruments array to avoid deep proxy overhead. The list is replaced wholesale on each fetch, not mutated item-by-item.

**Success criteria:**
- [ ] Instruments list with search and `$state.raw` for performance
- [ ] Create instrument form with validation
- [ ] Bulk sync with confirmation + loading state
- [ ] External search with results table + per-row "Import" button
- [ ] Instrument detail in ContextPanel
- [ ] `make check:all` passes

---

## System-Wide Impact

### Interaction Graph

- Each new mutation endpoint in the frontend creates a write path that goes through: SvelteKit page → `NetzApiClient` → FastAPI route → SQLAlchemy (RLS for credit/wealth, no RLS for admin) → PostgreSQL
- SSE connections go: Frontend `createSSEStream` → FastAPI SSE endpoint → Redis pub/sub → Worker
- Branding asset uploads go: Frontend file input → `POST /admin/tenants/{org_id}/assets` → StorageClient → ADLS/local filesystem

### Error Propagation

- `NetzApiClient` catches HTTP errors and throws typed exceptions (`AuthError`, `ForbiddenError`, `ValidationError`, `ConflictError`, `ServerError`)
- Components catch these in try/catch blocks and display inline error messages
- 401 → single-flight redirect to sign-in (handled by client)
- 409 → Toast notification (conflict handler pattern)
- 422 → Inline validation error display

### State Lifecycle Risks

- **Optimistic concurrency on config edits** — `If-Match` header prevents lost updates. On 409, reload + Toast.
- **Rebalance approval race** — `SELECT FOR UPDATE` prevents double-approval. On 409, Toast + reload.
- **Content generation fire-and-forget** — After Phase 0 fix, failures are captured. Poll list for status updates.
- **SSE connection cleanup** — All SSE connections cleaned up via `$effect` return function or `onDestroy`.

### API Surface Parity

All 95 disconnected endpoints will have corresponding frontend UI. After completion, coverage goes from 44.6% to ~100% (excluding the 4 infra endpoints).

## Dependencies & Prerequisites

1. **Phase 0 must complete before all other phases** — shared components + API client extensions + security fixes + backend bug fixes
2. **Phase 8 (Instruments) should precede Phase 6 (Portfolio Ops)** — instruments are prerequisites for testing rebalancing and allocation
3. **Phase 7 should be split into 7A/7B/7C** — reduces per-phase complexity from 15 to 5 endpoints each
4. **Phases 1-5 and 7A-7C are otherwise independent** — can execute in any order or in parallel
5. **`make types` requires running backend** — generate TypeScript types before frontend work
6. **`@netz/ui` changes (Phase 0) need `pnpm build:all`** — other frontends consume via package

### Recommended Execution Order

```
Phase 0 (shared infrastructure + security fixes) ← 2-3 sessions
  │
  ├── Phase 1 (admin completion)
  ├── Phase 2 (credit deal lifecycle)
  ├── Phase 3 (credit document workflow)
  ├── Phase 4 (credit dashboard & AI)
  ├── Phase 5 (wealth content & reports)
  ├── Phase 7B (drift + attribution + correlation) ← no dependency on 6
  ├── Phase 7C (macro committee + risk SSE + screener) ← no dependency on 6
  ├── Phase 8 (instruments — before 6)
  │     └── Phase 6 (portfolio operations — after 8)
  │           └── Phase 7A (backtest + optimization — weak dependency on 6.3)
  └── (all above can run in parallel except arrows)
```

> **Dependency clarification:** Only Phase 7A (Backtest + Optimization) has a weak dependency on Phase 6 (model portfolios for backtest targets). Phases 7B and 7C have zero dependency on Portfolio Operations and can run in parallel with any other phase. Under time pressure, prioritize 7B/7C before 6.

## Risk Analysis & Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Scope creep (95 endpoints is massive) | Timeline overrun | Strict phase boundaries, each independently deployable |
| Missing backend routes | Frontend 404s | Phase 0 route manifest verification |
| Optimistic locking UX confusion | User frustration | Consistent 409 → Toast + reload pattern, If-Match required |
| SSE connection limits | 429 errors | Global SSE registry (max 4/tab), handle 429 with message |
| Long-running operations (Pareto: 135s) | Timeout/confusion | Dedicated thread pool, 180s timeout, duplicate prevention |
| Theme token mismatches | Visual bugs | All new components use only declared `var(--netz-*)` tokens |
| Cross-frontend import violations | Build failure | Shared code only via `@netz/ui`, enforced by Turborepo |
| **Security: SQL injection in SET LOCAL** | **Data breach** | **Phase 0.5 — parameterized queries (BLOCKING)** |
| **Security: Cross-tenant SSE leak** | **Data breach** | **Phase 0.5 — org-scoped Redis channels (BLOCKING)** |
| **Security: XSS in LLM content** | **Account takeover** | **Sanitizing Markdown renderer, never `{@html}` with raw** |
| **Security: CSRF on multipart uploads** | **Unauthorized writes** | **Custom header `X-Netz-Request: 1` on upload endpoints** |
| **Performance: Pareto thread pool exhaustion** | **System-wide block** | **Dedicated ThreadPoolExecutor(max_workers=2) + semaphore** |
| Inconsistency across 95 implementations | UX fragmentation | Frontend Mutation Playbook (Phase 0.6), per-phase review |
| NetzApiClient capability gaps | Workaround sprawl | Phase 0.1b adds `getBlob()`, `upload()`, custom headers, per-request timeout |

## Sources & References

### Origin

- **Audit document:** [docs/audit/endpoint_coverage_audit.md](../audit/endpoint_coverage_audit.md) — Full endpoint inventory and gap analysis
- **Admin brainstorm:** [docs/brainstorms/2026-03-17-admin-frontend-brainstorm.md](../brainstorms/2026-03-17-admin-frontend-brainstorm.md) — Admin frontend design decisions

### Internal References

- **Mutation pattern reference:** `frontends/admin/src/lib/components/PromptEditor.svelte` — Gold standard for save/validate/revert flow
- **ContextPanel pattern:** `frontends/wealth/src/lib/components/FundDetailPanel.svelte` — Detail panel with tabs + SSE
- **SSE utility:** `packages/ui/src/lib/utils/sse-client.svelte.ts` — `createSSEStream` for real-time features
- **API client:** `packages/ui/src/lib/utils/api-client.ts:145` — `NetzApiClient` with typed errors, `DEFAULT_TIMEOUT_MS = 15_000`
- **Design decisions D1-D9:** `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md`
- **SQL injection vector:** `backend/app/core/tenancy/admin_middleware.py:26` — f-string SET LOCAL (SEC-1)
- **Job ownership bypass:** `backend/app/core/jobs/tracker.py:60-74` — verify_job_owner returns True on missing key (SEC-2)
- **Content background task:** `backend/app/domains/wealth/routes/content.py:386-389` — RLS bypass + f-string (SEC-3)
- **Fact sheet path traversal:** `backend/app/domains/wealth/routes/fact_sheets.py:170-206` — accepts `..` segments (SEC-4)
- **Risk SSE global channels:** `backend/app/domains/wealth/routes/risk.py:199-231` — not org-scoped (SEC-5)
- **Evidence SAS placeholder:** `backend/app/domains/credit/documents/routes/uploads.py:63` — literal placeholder (SEC-7)
- **Config optimistic locking:** `backend/app/domains/admin/routes/configs.py:69-85` — If-Match optional (SEC-8)
- **Pareto thread pool:** `backend/quant_engine/optimizer_service.py:422` — uses default asyncio thread pool

### Institutional Learnings

- **Admin frontend production bugs:** `docs/solutions/design-decisions/multi-agent-review-admin-frontend-production-bugs-2026-03-17.md` — 5 P1 bugs caught by review (RLS bypass, route mounting, trigger crashes, XSS)
- **Wealth frontend patterns:** `docs/solutions/architecture-patterns/wealth-os-design-refresh-multi-agent-review-patterns.md` — Lock contracts before delegation, token audit, SSE audit
- **Route shadowing:** `docs/solutions/logic-errors/fastapi-route-shadowing-and-sql-limit-bias-multi-instrument-20260317.md` — Literal routes before parameterized routes
- **RLS subselect 1000x slowdown:** `docs/solutions/performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md` — Always use `(SELECT current_setting(...))` not bare call

### Deepening Review Agents

- **architecture-strategist:** Phase ordering, API client gaps (P1), Phase 7 split, component boundaries
- **security-sentinel:** 4 Critical + 6 High findings across SQL injection, CSRF, path traversal, tenant isolation
- **performance-oracle:** Pareto thread pool exhaustion, SSE connection density, PDF memory buffering, content polling
- **best-practices-researcher:** 10 concrete Svelte 5 runes patterns for forms, optimistic UI, file upload, polling, blob download
