---
module: Credit Storage I/O
date: 2026-03-23
problem_type: integration_issue
component: service_object
symptoms:
  - "14 credit endpoints raise NotImplementedError at runtime from blob_storage.py stub"
  - "list_blobs(), blob_uri(), upload_bytes(), upload_bytes_idempotent() all crash"
  - "IC memo PDFs, fact sheets, deal creation, reporting all broken"
  - "document_scanner and unified_pipeline source discovery broken"
root_cause: wrong_api
resolution_type: code_fix
severity: critical
tags: [storage-migration, azure-blob, r2, storageclient, dead-code, blob-storage]
---

# Troubleshooting: Incomplete Azure Blob → StorageClient Migration Leaves 14 Credit Endpoints Broken

## Problem

After migrating from Azure Blob Storage to `StorageClient` (R2/LocalStorage), the Wealth vertical was fully migrated but the Credit vertical still had 14 active route endpoints calling the deprecated `blob_storage.py` stub. All write/list/URL-generation functions in the stub raised `NotImplementedError`, meaning IC memo PDFs, fact sheets, marketing presentations, deal creation, deal document uploads, deal context patches, monthly report packs, investor statements, and pipeline document discovery were broken at runtime.

## Environment

- Module: Credit vertical storage I/O + ai_engine pipeline
- Stack: FastAPI + asyncpg + StorageClient (R2/LocalStorage)
- Affected Components: `blob_storage.py` (stub), `blob_client.py` (deprecated), `search_index.py` (deprecated), `search_upsert_service.py` (deprecated), 14 credit route handlers, 2 ai_engine modules
- Date: 2026-03-23

## Symptoms

- `create_deal()` crashes with `NotImplementedError` when writing deal context JSON
- `upload_deal_document()` crashes on PDF upload
- `patch_deal_context()` crashes on `blob_uri()` call for read path
- `get_deal_im_pdf()` and `rebuild_deal_im_pdf()` crash on `ensure_container()`, `blob_exists()`, `upload_bytes_idempotent()`
- `generate_fact_sheet()`, `get_fact_sheet_pdf()`, `generate_marketing_presentation()`, `get_marketing_presentation_pdf()` all crash
- `get_periodic_review_pdf()` crashes on blob_exists/upload
- `generate_monthly_pack()` and `generate_investor_statement()` crash on `upload_bytes_append_only()`
- `unified_pipeline.process()` crashes on `list_blobs()` for extraction source discovery
- `document_scanner.scan_document_registry()` crashes on `list_blobs()`
- `download_monthly_pack()` and `download_investor_statement()` work via `download_bytes()` shim but are fragile

## What Didn't Work

**Direct solution:** The problem was identified via a comprehensive storage I/O audit (`docs/audit/storage_io_audit.md`) that mapped every storage call path in both verticals. The audit classified each path as OK/BROKEN/RISK/DEPRECATED and prioritized remediation into P0/P1/P2 tiers.

## Solution

Three-phase parallel remediation executed via 7 concurrent agents (P0), 2 concurrent agents (P1), and 4 concurrent agents (P2).

### P0 — Migrate 14 broken endpoints to StorageClient

**1. Add credit-specific path helpers to `storage_routing.py`:**

```python
# Before: No credit-specific path helpers existed.
# Callers used Azure container names like "investment-pipeline-intelligence"

# After: 5 new helpers in ai_engine/pipeline/storage_routing.py
def bronze_deal_path(org_id: UUID, deal_id: str, filename: str) -> str:
    return f"bronze/{org_id}/credit/pipeline/deals/{deal_id}/{filename}"

def gold_ic_memo_path(org_id: UUID, deal_id: str, filename: str) -> str:
    return f"gold/{org_id}/credit/ic_memoranda/{deal_id}/{filename}"

def gold_artifact_path(org_id: UUID, deal_id: str, filename: str) -> str:
    return f"gold/{org_id}/credit/artifacts/{deal_id}/{filename}"

def gold_portfolio_review_path(org_id: UUID, investment_id: str, filename: str) -> str:
    return f"gold/{org_id}/credit/portfolio_reviews/{investment_id}/{filename}"

def gold_credit_report_path(org_id: UUID, fund_id: str, report_type: str, filename: str) -> str:
    return f"gold/{org_id}/credit/reports/{report_type}/{fund_id}/{filename}"
```

**2. Replace blob_storage calls in each route handler:**

```python
# Before (broken — raises NotImplementedError):
from app.services.blob_storage import upload_bytes_idempotent, generate_read_link
upload_bytes_idempotent(container=_CONTAINER, blob_name=name, data=pdf_bytes, content_type="application/pdf")
url = generate_read_link(container=_CONTAINER, blob_name=name)

# After (working — async StorageClient):
from app.services.storage_client import get_storage_client
from ai_engine.pipeline.storage_routing import gold_ic_memo_path

storage = get_storage_client()
path = gold_ic_memo_path(org_id=actor.organization_id, deal_id=str(deal_id), filename=filename)
await storage.write(path, pdf_bytes, content_type="application/pdf")
url = await storage.generate_read_url(path)
```

**3. Replace list_blobs in pipeline/scanner:**

```python
# Before (broken):
from app.services.blob_storage import list_blobs
entries = list_blobs(container="extraction-source", prefix=prefix)

# After (working):
storage = get_storage_client()
files = await storage.list_files(prefix)
```

### P1 — Delete superseded code + deprecated routes

- Deleted `upload_document()` from `credit/documents/service.py` (superseded by SAS URL flow)
- Deleted 10 deprecated dataroom route endpoints + router registrations from `main.py`

### P2 — Dead code removal

- Deleted `blob_client.py`, `blob_storage.py`, `search_index.py`, `search_upsert_service.py`
- Removed Service Bus branch from `pipeline_dispatch.py`
- Cleaned `AzureSearchMetadataClient` references from `obligation_extractor.py`, `knowledge_builder.py`
- Deleted 3 test files testing deprecated code, updated 8 test files

**Net result:** 38 files changed, +454 / -3,092 lines. 7 files deleted, 3 test files deleted.

## Why This Works

1. **Root cause:** The Azure-to-R2 storage migration was executed incrementally. Wealth was migrated first (it had fewer storage touchpoints). Credit was left on the deprecated `blob_storage.py` stub whose write/list/URL functions were replaced with `NotImplementedError` placeholders. The stub's `download_bytes()` was the only function bridged to `StorageClient`, so reads worked but writes/lists/URL generation crashed.

2. **Why the solution works:** `StorageClient` is the unified abstraction (R2 in prod, LocalStorage in dev) with async methods matching all the operations the credit routes need. The `storage_routing.py` path helpers enforce the `{tier}/{org_id}/{vertical}/...` convention with `_SAFE_PATH_SEGMENT_RE` validation, preventing path traversal and ensuring tenant isolation. By converting routes to `async def` with `await storage.write(...)`, the credit vertical now uses the same pattern as the fully-migrated wealth vertical.

3. **Underlying issue:** Partial migration with a stub that raises on unused functions is a valid incremental approach, but the stub must be tracked and callers migrated before the routes go live. The audit revealed the gap between "stub created" and "callers migrated."

## Prevention

- **Storage I/O audit as gate:** Run `docs/audit/storage_io_audit.md` pattern (map all storage call paths, classify as OK/BROKEN/RISK/DEPRECATED) before declaring a storage migration complete
- **Never use f-strings for storage paths in callers:** Always use `storage_routing.py` helpers. They validate segments and enforce the tier/org/vertical convention
- **Delete stubs promptly:** Once all callers are migrated, delete the stub immediately. A stub that raises `NotImplementedError` is a time bomb if any caller is missed
- **Regression guard test:** Add AST-based import guards (e.g., `test_no_blob_storage_imports_in_credit_routes()`) that fail CI if any active code imports from deleted modules
- **Parallel agent execution:** For large migrations touching 7+ independent files, use parallel agents (one per file) to avoid sequential bottlenecks. Each agent reads the target + reference files independently

## Related Issues

- See also: [phase3-storageclient-adls-dualwrite-pattern-20260315.md](../architecture-patterns/phase3-storageclient-adls-dualwrite-pattern-20260315.md) — original StorageClient + ADLS dual-write pattern that preceded this migration
- See also: [azure-search-tenant-isolation-organization-id-filtering-20260315.md](../security-issues/azure-search-tenant-isolation-organization-id-filtering-20260315.md) — Azure Search tenant isolation that was also deprecated in this cleanup
