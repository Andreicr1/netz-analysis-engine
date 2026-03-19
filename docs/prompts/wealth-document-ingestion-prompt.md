# Wealth Document Ingestion — Implementation Prompt

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Context

The Credit vertical has a complete document upload + ingestion flow:
- `POST /documents/upload-url` — generates presigned URL, creates pending `DocumentVersion`
- `POST /documents/upload-complete` — marks version as `PROCESSING`, publishes SSE event
- `POST /documents/upload` — single-step upload (file in body, writes to storage directly)
- `POST /documents/ingestion/process-pending` — picks up pending versions, runs `unified_pipeline.process()`

All paths go through `ai_engine/pipeline/unified_pipeline.py::process()` with an `IngestRequest` envelope. The pipeline is vertical-agnostic — it works for any vertical via `IngestRequest.vertical`.

Wealth currently has **zero** document upload routes. The DD Report engine (`vertical_engines/wealth/dd_report/`) needs documents in the data lake to generate evidence-based chapters, but there is no way to get documents in.

The storage backend is Cloudflare R2 (`FEATURE_R2_ENABLED=true`, S3-compatible via boto3). See `backend/app/services/storage_client.py` for `R2StorageClient`.

## Goal

Implement Wealth document ingestion with two entry points:
1. **Frontend upload** — two-step presigned URL flow (identical pattern to Credit)
2. **API direct upload** — single POST with file in body (for programmatic integrations)

Both feed the same `unified_pipeline.process()` with `vertical="wealth"`.

## Reference Files (read these first)

```
# Credit upload routes (pattern to replicate)
backend/app/domains/credit/documents/routes/upload_url.py
backend/app/domains/credit/documents/routes/ingest.py

# Credit document service (pattern to replicate)
backend/app/domains/credit/documents/service.py

# Credit document models + schemas
backend/app/domains/credit/modules/documents/models.py
backend/app/domains/credit/modules/documents/schemas.py

# Unified pipeline (reuse as-is)
ai_engine/pipeline/unified_pipeline.py
ai_engine/pipeline/storage_routing.py

# Storage client (R2 backend)
backend/app/services/storage_client.py

# Wealth domain structure
backend/app/domains/wealth/routes/
backend/app/domains/wealth/models/
backend/app/domains/wealth/schemas/

# Wealth router registration
backend/app/domains/wealth/__init__.py
```

## Implementation Steps

### Step 1: Wealth Document Models

Create `backend/app/domains/wealth/models/document.py`:

- `WealthDocument` model — mirrors Credit's `Document` but scoped to wealth:
  - `id: UUID` (PK, server_default=uuid4)
  - `organization_id: UUID` (RLS)
  - `portfolio_id: UUID | None` (FK to portfolios, nullable — equivalent to Credit's fund_id)
  - `instrument_id: UUID | None` (FK to instruments, nullable — for instrument-specific docs)
  - `title: str`
  - `filename: str`
  - `content_type: str`
  - `root_folder: str` (default "documents")
  - `subfolder_path: str | None`
  - `domain: str | None` (e.g., "dd_report", "fact_sheet", "compliance")
  - `created_at`, `updated_at`, `created_by`, `updated_by`
  - All relationships with `lazy="raise"`

- `WealthDocumentVersion` model — mirrors Credit's `DocumentVersion`:
  - `id: UUID` (PK, server_default=uuid4)
  - `document_id: UUID` (FK to WealthDocument)
  - `organization_id: UUID` (RLS)
  - `portfolio_id: UUID | None`
  - `version_number: int` (default 1)
  - `blob_uri: str | None` (R2 path)
  - `ingestion_status: DocumentIngestionStatus` (reuse Credit's enum from `app/domains/credit/documents/enums.py`, or create shared enum)
  - `ingestion_error: str | None`
  - `created_at`, `updated_at`, `created_by`, `updated_by`
  - All relationships with `lazy="raise"`

Both tables must have RLS policies using `(SELECT current_setting('app.current_organization_id')::uuid)` subselect pattern.

### Step 2: Alembic Migration

Create migration for `wealth_documents` and `wealth_document_versions` tables. Check current head with `alembic heads` first. Include RLS policies.

### Step 3: Wealth Document Schemas

Create `backend/app/domains/wealth/schemas/document.py`:

- `WealthDocumentOut` — Pydantic model for API responses
- `WealthDocumentVersionOut` — version response
- `WealthUploadUrlRequest` — `{ portfolio_id?, instrument_id?, filename, content_type, root_folder?, subfolder_path?, domain?, title? }`
- `WealthUploadUrlResponse` — `{ upload_id, upload_url, blob_path, expires_in }`
- `WealthUploadCompleteRequest` — `{ upload_id, portfolio_id? }`
- `WealthUploadCompleteResponse` — `{ job_id, version_id, document_id }`

### Step 4: Wealth Document Service

Create `backend/app/domains/wealth/services/document_service.py`:

- `create_document_pending()` — creates WealthDocument + WealthDocumentVersion with status PENDING
- `upload_document()` — single-step: creates records + writes to storage via `StorageClient`
- `list_documents()` — query with optional filters (portfolio_id, instrument_id, domain)
- Follow Credit's `service.py` pattern exactly. All functions take `db: AsyncSession` as first arg.

### Step 5: Wealth Upload Routes

Create `backend/app/domains/wealth/routes/documents.py`:

**Route 1: `POST /documents/upload-url`** (two-step presigned URL)
- Mirrors `credit/documents/routes/upload_url.py` exactly
- Uses `bronze_upload_blob_path(org_id, portfolio_id or instrument_id, version_id, filename)`
- Note: `bronze_upload_blob_path` second arg is `fund_id: UUID` — for Wealth, pass `portfolio_id` (same concept, different name). If neither portfolio_id nor instrument_id is provided, use a synthetic "unassigned" UUID or reject.
- Returns presigned URL from `storage.generate_upload_url()`

**Route 2: `POST /documents/upload-complete`** (marks as PROCESSING)
- Mirrors Credit's upload-complete
- Publishes SSE event via `publish_event()`

**Route 3: `POST /documents/upload`** (single-step API upload)
- Accepts `UploadFile` in body (multipart form)
- Writes directly to R2 via `storage.write()`
- Creates document + version records
- Returns document_id, version_id, blob_path

**Route 4: `POST /documents/ingestion/process-pending`** (triggers pipeline)
- Queries WealthDocumentVersion with status=PROCESSING
- For each, creates `IngestRequest(source="api", vertical="wealth", ...)`
- Calls `unified_pipeline.process(request, db=db, actor_id=actor.actor_id)`
- Returns processed/indexed/failed/skipped counts

**Route 5: `GET /documents`** (list with filters)
- Query params: portfolio_id?, instrument_id?, domain?, limit, offset

**Route 6: `GET /documents/{document_id}`** (single document)

Auth: all routes require `Role.INVESTMENT_TEAM` or `Role.ADMIN` (same as Wealth workers).

### Step 6: Register Router

Add the new router to `backend/app/domains/wealth/__init__.py` router registration.

Prefix: `/api/v1/wealth/documents`

### Step 7: Tests

Create `backend/tests/test_wealth_documents.py`:

1. `test_upload_url_generates_presigned_url` — POST /documents/upload-url returns upload_url + upload_id
2. `test_upload_complete_marks_processing` — POST /documents/upload-complete transitions status
3. `test_direct_upload_writes_to_storage` — POST /documents/upload writes file to storage and creates records
4. `test_list_documents_filters_by_portfolio` — GET /documents?portfolio_id=X returns correct subset
5. `test_upload_rejects_empty_file` — 400 on empty file
6. `test_upload_rejects_oversized_file` — 413 on >100MB
7. `test_process_pending_calls_pipeline` — POST /documents/ingestion/process-pending calls unified_pipeline.process
8. `test_rls_isolation` — documents from org A not visible to org B

Use existing test fixtures and patterns from `backend/tests/`. Mock `StorageClient` and `unified_pipeline.process()` — do not call real R2 or LLM.

### Step 8: Verify

```bash
make check  # Must pass: lint + typecheck + architecture + all tests
```

## Critical Rules (from CLAUDE.md)

- `async def` + `AsyncSession` from `get_db_with_rls()` on all routes
- `response_model=` on all routes, return via `model_validate()`
- `expire_on_commit=False` always
- `lazy="raise"` on ALL relationships
- RLS subselect: `(SELECT current_setting(...))` not bare `current_setting()`
- `SET LOCAL` not `SET` for RLS context
- Storage writes via `StorageClient` only — never call boto3 directly
- `bronze_upload_blob_path()` for upload paths — never build paths with f-strings
- Do not modify `ai_engine/` — it is vertical-agnostic

## What NOT to Do

- Do not create a separate pipeline for Wealth — reuse `unified_pipeline.process()`
- Do not modify Credit document routes or models
- Do not add Wealth-specific logic to `ai_engine/`
- Do not create new feature flags — this uses existing infrastructure
- Do not move Credit's `DocumentIngestionStatus` enum — either reuse it or create a shared version in `app/shared/enums.py`
