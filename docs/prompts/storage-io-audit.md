# Storage & I/O Migration Audit — Azure Blob → R2 Data Lake

## Context

You are working on `netz-analysis-engine`, a multi-tenant investment analysis platform that **migrated from Azure Blob Storage to Cloudflare R2** via a `StorageClient` abstraction layer. The migration was completed at Milestone 2.5 (2026-03-19), but several credit domain modules still reference the deprecated `blob_storage.py` stub, which raises `NotImplementedError` at runtime.

**This is a reliability risk**: if any production code path hits a legacy blob_storage call instead of the StorageClient, uploads, downloads, and document processing will fail silently or crash.

Read `CLAUDE.md` at the repo root for full architecture context.

## Architecture Summary

### Active Storage (production)
- `backend/app/services/storage_client.py` — `StorageClient` ABC with two implementations:
  - `LocalStorageClient` — filesystem at `.data/lake/` (dev, `FEATURE_R2_ENABLED=false`)
  - `R2StorageClient` — Cloudflare R2 S3-compatible (prod, `FEATURE_R2_ENABLED=true`)
- Factory: `create_storage_client()` (R2 priority > Local)
- Singleton: `get_storage_client()` (FastAPI dependency)
- Path routing: `ai_engine/pipeline/storage_routing.py` (bronze/silver/gold hierarchy)

### Deprecated Storage (must not be called in production paths)
- `backend/app/services/blob_storage.py` — stub with `NotImplementedError` on all write/list/url-gen functions
  - Exception: `download_bytes()` bridges to `StorageClient.read()` as a compatibility shim
- `backend/app/services/azure/blob_client.py` — dead code (no active callers)
- `backend/app/services/azure/search_client.py` — replaced by pgvector
- `backend/app/services/search_index.py` — `AzureSearchMetadataClient` (deprecated)

### Deprecated Dispatch (conditional fallback)
- `backend/app/services/azure/pipeline_dispatch.py` — `dispatch_extraction()`, `dispatch_ingest()`, `dispatch_deep_review()` use BackgroundTasks by default; Azure Service Bus only if `USE_SERVICE_BUS=true` (never in prod)

---

## Your Task

Perform a **complete audit** of every I/O code path between the AI engine, storage providers, and LLM calls for both Credit and Wealth verticals. For each finding, produce a verdict: `OK`, `RISK`, or `BROKEN`.

### Phase 1 — Credit Document Upload & Ingestion Flow

Trace the full path from document upload to pipeline completion:

1. **Read** `backend/app/domains/credit/documents/routes/uploads.py` and `upload_url.py`
   - How do uploads reach storage? Do they use `StorageClient` or legacy `blob_storage`?
   - Is presigned URL generation using `StorageClient.generate_upload_url()` or legacy `generate_read_link()`?

2. **Read** `backend/app/domains/credit/documents/service.py`
   - Does `upload_bytes_append_only()` call legacy stub? If yes → BROKEN

3. **Read** `backend/app/services/azure/pipeline_dispatch.py`
   - Trace `dispatch_ingest()` — does it reach `unified_pipeline.process()` via BackgroundTasks?
   - Is there any path that tries to write to Azure Service Bus in the default config?

4. **Read** `backend/ai_engine/pipeline/unified_pipeline.py` (the `process()` function)
   - Verify all storage writes use `_write_to_lake()` → `StorageClient`
   - Verify blob download uses `download_bytes()` → and that bridges to `StorageClient.read()`
   - Verify pgvector upsert replaces Azure Search

5. **Read** `backend/ai_engine/ingestion/pipeline_ingest_runner.py`
   - Is this still used? Does it call legacy blob storage or StorageClient?
   - Check `document_scanner.py` — does it reference Azure Search for blob listing?

6. **Read** `backend/ai_engine/ingestion/document_scanner.py`
   - Does it use `AzureSearchMetadataClient`? If yes → RISK (deprecated)
   - Does it use `list_blobs()` from blob_storage? If yes → BROKEN

### Phase 2 — Credit Domain Module I/O

Audit each credit module for legacy storage calls:

7. **Read** `backend/app/domains/credit/modules/ai/memo_chapters.py`
   - Search for `upload_bytes`, `ensure_container`, `generate_read_link`, `exists`
   - Are these reachable from active code paths or gated behind feature flags?

8. **Read** `backend/app/domains/credit/modules/ai/artifacts.py`
   - Same audit: `upload_bytes_idempotent`, `exists`, `generate_read_link`, `list_blobs`
   - Determine if artifact generation/download is currently working or broken

9. **Read** `backend/app/domains/credit/modules/ai/portfolio.py`
   - Check `blob_exists()` and `generate_read_link()` calls
   - Are these on active portfolio routes?

10. **Read** `backend/app/domains/credit/dataroom/routes/routes.py`
    - Check `list_blobs()` and `generate_read_link()` — these serve the UI dataroom view
    - If broken → users cannot browse the document dataroom

11. **Read** `backend/app/domains/credit/modules/deals/routes.py`
    - Check `upload_bytes()`, `blob_uri()`, `download_bytes()` calls
    - Which deal operations are broken?

12. **Read** `backend/app/domains/credit/reporting/routes/reports.py`
    - Check report generation and download paths

### Phase 3 — Wealth Document & Fact Sheet Flow

13. **Read** `backend/app/domains/wealth/routes/documents.py`
    - Verify upload uses `get_storage_client()` → `StorageClient.generate_upload_url()`
    - Verify download uses `StorageClient.read()` or `generate_read_url()`

14. **Read** `backend/app/domains/wealth/routes/fact_sheets.py`
    - Verify fact sheet PDF write/read/list uses `StorageClient`

15. **Read** `backend/app/domains/wealth/services/document_service.py`
    - Verify `storage_client.write()` is the active path

16. **Read** `backend/app/domains/wealth/workers/brochure_ingestion.py` and `fact_sheet_gen.py`
    - Verify workers use `get_storage_client()` throughout

### Phase 4 — LLM & Embedding I/O

17. **Read** `backend/ai_engine/openai_client.py`
    - Verify LLM calls use OpenAI direct (not Azure OpenAI)
    - Check for any fallback to `AZURE_OPENAI_ENDPOINT`

18. **Read** `backend/ai_engine/extraction/embedding_service.py`
    - Verify embeddings use OpenAI `text-embedding-3-large` (not Azure)

19. **Read** `backend/ai_engine/extraction/mistral_ocr.py`
    - Verify OCR uses Mistral API directly

20. **Read** `backend/ai_engine/cache/provider_cache.py`
    - Verify cache reads/writes use local SQLite (no Azure dependency)

### Phase 5 — Search & Index I/O

21. **Read** `backend/ai_engine/extraction/pgvector_search_service.py` (first 50 lines + `upsert_chunks` + `search_and_rerank`)
    - Verify all search operations use pgvector (not Azure Search)
    - Check for any `AzureSearchMetadataClient` imports

22. **Read** `backend/ai_engine/extraction/search_upsert_service.py`
    - Verify upsert targets pgvector tables

23. **Read** `backend/ai_engine/pipeline/search_rebuild.py`
    - Verify rebuild reads from `StorageClient` (silver Parquet) and writes to pgvector

24. **Read** `backend/app/services/search_index.py`
    - Confirm this is fully deprecated and not called from active paths

### Phase 6 — Global Agent & RAG

25. **Read** `backend/app/domains/credit/global_agent/agent.py`
    - Verify RAG retrieval uses pgvector (not Azure Search)
    - Verify deal context reads from `StorageClient`

---

## Output Format

Produce a structured report with these sections:

### 1. Executive Summary
One paragraph: overall migration status, number of OK/RISK/BROKEN findings.

### 2. Findings Table

| # | File | Function/Path | Verdict | Issue | Remediation |
|---|------|--------------|---------|-------|-------------|
| 1 | credit/documents/routes/uploads.py | upload() | OK/RISK/BROKEN | Description | Fix |

### 3. Critical Path Analysis
For each vertical (Credit, Wealth), trace the happy path:
- **Upload** → Storage → Pipeline → Chunks → Embeddings → pgvector
- Mark each step as OK or BROKEN

### 4. Dead Code Candidates
List files/functions that are no longer reachable and can be safely deleted.

### 5. Remediation Priority
Ordered list of fixes needed, grouped by severity:
- **P0 (Broken)**: Production code paths that will crash
- **P1 (Risk)**: Deprecated calls that work via shim but should be migrated
- **P2 (Cleanup)**: Dead code removal, import cleanup

### 6. Suggested Test Coverage
For each RISK/BROKEN finding, suggest a test that would catch the regression:
```python
def test_credit_upload_uses_storage_client():
    """Verify credit document upload uses StorageClient, not blob_storage."""
    ...
```

---

## Rules

- **Read every file listed** — do not skip or assume based on file names
- **Follow imports** — if a function calls another module, read that too
- **Check both the import AND the call site** — a file may import blob_storage but not call it
- **Distinguish between schema references and I/O calls** — `blob_uri` as a column name is OK; `blob_storage.upload_bytes()` as a function call is BROKEN
- **Check feature flags** — some paths are gated behind `FEATURE_R2_ENABLED`, `USE_SERVICE_BUS`, etc.
- **DO NOT modify any source files** — this is a read-only audit
- **Save the report** to `docs/audit/storage_io_audit.md`
