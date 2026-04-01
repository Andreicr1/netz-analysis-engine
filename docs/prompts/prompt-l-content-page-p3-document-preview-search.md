# Content Page P3 — Document Preview + Content Search/Filter

## Context

This is Phase 3 of the Content Page Completeness plan (`docs/plans/2026-04-01-feat-content-page-completeness-audit-plan.md`). Phases P0-P2 are already implemented and committed on branch `feat/content-page-completeness`:

- **P0 (done):** Content detail route `/content/[id]` with markdown reader, DOMPurify, shared `renderMarkdown()`, `PdfPreview.svelte`, clickable cards
- **P1 (done):** `MonthlyReportPanel.svelte` SSE component wired into `/portfolios/[profile]`
- **P2 (done):** Macro committee PDF download (`macro_pdf.py` + `GET /macro/reviews/{id}/download` + button in `CommitteeReviews.svelte`)

**Also pending from P2:** Content SSE (replacing 5s polling with SSE streaming for content generation). See plan section 2.4 for full spec.

## What to Implement

### Task 1 — Document File Preview (backend + frontend)

**Backend:** Add `GET /wealth/documents/{document_id}/preview-url` endpoint in `backend/app/domains/wealth/routes/documents.py`.

- Fetch document + latest version from DB
- Call `StorageClient.generate_read_url(version.blob_path, expires_in=300)` — this method **already exists** on both `LocalStorageClient` (returns `file://` URI) and `R2StorageClient` (returns presigned S3 URL)
- Return `{"url": str, "content_type": str, "filename": str}`
- RLS-scoped via `get_db_with_rls`
- Import `create_storage_client` from `app.services.storage_client`

Key models/tables:
- `WealthDocument` — has `id`, `filename`, `content_type`, `current_version`
- `WealthDocumentVersion` — has `document_id`, `version_number`, `blob_path`, `ingestion_status`
- Need to query latest version by `document_id` + `version_number = doc.current_version`

**Frontend:** Update `frontends/wealth/src/routes/(app)/documents/[documentId]/+page.svelte` (currently shows only metadata).

- Add a "Preview" section below the existing metadata
- On mount (or button click), call `GET /wealth/documents/{documentId}/preview-url` via `api.get()`
- For PDFs (`content_type` starts with `application/pdf`): render `PdfPreview.svelte` (already exists at `$lib/components/PdfPreview.svelte`) — note: PdfPreview expects a **blob URL** but presigned URLs work directly in `<object data={url}>`, so either:
  - Option A: Pass presigned URL directly to `<object data={url}>` (simplest, no blob needed)
  - Option B: Fetch blob via presigned URL, create blob URL, pass to PdfPreview
  - **Prefer Option A** — presigned URL already has auth baked in
- For images (`content_type` starts with `image/`): render `<img src={url}>`
- For other types: show download link only
- Add "Refresh" button if presigned URL expires (5 min TTL)
- Handle loading state and errors

### Task 2 — Content Search and Filter (frontend only)

**File:** `frontends/wealth/src/routes/(app)/content/+page.svelte`

Add client-side search and filter to the existing tab bar area. No backend changes needed.

- **Search input:** Filter cards by title. Use `$state` + `$derived` pattern:
  ```typescript
  let searchQuery = $state("");
  let filtered = $derived.by(() => {
    let items = activeTab === "all" ? content : content.filter(c => c.content_type === activeTab);
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      items = items.filter(c => (c.title ?? "").toLowerCase().includes(q));
    }
    return items;
  });
  ```
- **Sort select:** Options: "Newest first" (default), "Oldest first", "A-Z"
- Place search input + sort select in the tab bar row, right-aligned
- Use `--ii-*` design tokens for all styling (no hardcoded colors)
- Reference pattern: DD reports list page at `frontends/wealth/src/routes/(app)/dd-reports/+page.svelte` has a similar search input

### Task 3 (bonus, from P2.4) — Content Generation SSE

Replace the 5-second polling in `/content/+page.svelte` with SSE streaming.

**Backend changes** (`backend/app/domains/wealth/routes/content.py`):

1. In POST triggers (outlooks, flash-reports, spotlights), generate a `job_id = str(uuid.uuid4())`, call `await register_job_owner(job_id, str(org_id))`, include `job_id` in the response alongside the ContentSummary fields.

2. Add SSE stream endpoint:
   ```python
   @router.get("/{content_id}/stream/{job_id}")
   async def stream_content_generation(content_id, job_id, request, ...):
       if not await verify_job_owner(job_id, str(org_id)):
           raise HTTPException(403)
       return await create_job_stream(request, job_id)
   ```

3. In `_run_content_generation()` background tasks, publish SSE events:
   - `await publish_event(job_id, "started", {"content_type": ...})`
   - `await publish_terminal_event(job_id, "done", {"status": "review", "content_id": ...})`
   - On error: `await publish_terminal_event(job_id, "error", {"error": str(e)})`

   Import from `app.core.jobs.tracker`: `register_job_owner`, `publish_event`, `publish_terminal_event`, `verify_job_owner`
   Import from `app.core.jobs.sse`: `create_job_stream`

**Frontend changes** (`content/+page.svelte`):

1. Capture `job_id` from POST response
2. Use manual `fetch()` + `ReadableStream` SSE (same pattern as `LongFormReportPanel.svelte:94-170`)
3. On terminal event (`done`/`error`), call `invalidateAll()`
4. **Keep polling as fallback** — start SSE, set 10s timer; if no SSE event received, fall back to 5s `setInterval`
5. Clean up SSE on navigation via `onDestroy` + `abortController.abort()`

## Acceptance Criteria

- [ ] `GET /wealth/documents/{id}/preview-url` returns presigned URL with 5 min TTL
- [ ] Document detail page shows inline PDF preview via `<object>` tag
- [ ] Document detail page shows inline image preview via `<img>` tag
- [ ] Preview works in dev (LocalStorage) and prod (R2)
- [ ] Content page has search input filtering by title
- [ ] Content page has sort selector (newest, oldest, A-Z)
- [ ] Content generation publishes SSE events (started, done, error)
- [ ] Frontend uses SSE for content generation with polling fallback
- [ ] SSE connection cleaned up on navigation away

## Key Files

**Read first (existing patterns):**
- `backend/app/services/storage_client.py` — `generate_read_url()` at line ~96
- `backend/app/domains/wealth/routes/documents.py` — existing document endpoints
- `backend/app/domains/wealth/models/document.py` — WealthDocument + WealthDocumentVersion models
- `frontends/wealth/src/routes/(app)/documents/[documentId]/+page.svelte` — current metadata viewer
- `frontends/wealth/src/routes/(app)/content/+page.svelte` — current card grid with tabs + polling
- `frontends/wealth/src/lib/components/LongFormReportPanel.svelte:94-170` — SSE pattern reference
- `backend/app/core/jobs/tracker.py` — register_job_owner, publish_event, etc.
- `backend/app/core/jobs/sse.py` — create_job_stream
- `backend/app/domains/wealth/routes/content.py` — current generation triggers + background tasks

**Modify:**
- `backend/app/domains/wealth/routes/documents.py` — add preview-url endpoint
- `frontends/wealth/src/routes/(app)/documents/[documentId]/+page.svelte` — add preview
- `frontends/wealth/src/routes/(app)/content/+page.svelte` — add search/sort + SSE
- `backend/app/domains/wealth/routes/content.py` — add job tracking + SSE endpoint

**Already created (reuse):**
- `frontends/wealth/src/lib/components/PdfPreview.svelte` — inline PDF viewer component
- `frontends/wealth/src/lib/utils/render-markdown.ts` — shared utility

## Rules

- Branch: continue on `feat/content-page-completeness`
- Use `--ii-*` design tokens for all CSS (no hardcoded colors)
- Use `async def` + `AsyncSession` for all route handlers
- Use `$state` / `$derived` (Svelte 5 runes) — no legacy `let` reactivity
- Use `fetch()` + `ReadableStream` for SSE — never `EventSource` (needs auth headers)
- Run `make check` or at minimum `pytest -x -q -k "content or document"` after backend changes
