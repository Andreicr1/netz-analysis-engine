# Storage & I/O Migration Audit — Azure Blob → R2 Data Lake

**Date:** 2026-03-23
**Last updated:** 2026-03-23 (post-remediation)
**Scope:** All I/O code paths between AI engine, storage providers, and LLM calls for Credit and Wealth verticals.
**Commit:** `1ae014c` — `refactor(storage): complete Azure Blob → StorageClient migration for credit vertical`

---

## 1. Executive Summary

The Azure-to-R2 storage migration is **complete**. Both Credit and Wealth verticals now use `StorageClient` exclusively for all storage operations. All deprecated Azure Blob, Azure Search, and Service Bus code paths have been removed. The `blob_storage.py` stub, `blob_client.py`, `search_index.py`, and `search_upsert_service.py` files have been deleted. Pipeline dispatch uses BackgroundTasks only (Service Bus branch eliminated).

**Totals: 33 OK | 0 BROKEN | 0 RISK | 0 DEPRECATED | 9 DELETED**

---

## 2. Findings Table

| # | File | Function/Path | Verdict | Notes |
|---|------|--------------|---------|-------|
| 1 | `credit/documents/routes/uploads.py` | `upload()` | **OK** | `StorageClient.generate_upload_url()` via `get_storage_client()` |
| 2 | `credit/documents/routes/upload_url.py` | `generate_upload_url()` | **OK** | `StorageClient.generate_upload_url()` via `get_storage_client()` |
| 3 | `credit/documents/service.py` | `upload_document()` | **DELETED** | Superseded by SAS URL flow (`create_document_pending()` + presigned upload). Function and its route removed |
| 4 | `services/azure/pipeline_dispatch.py` | `dispatch_ingest()` | **OK** | BackgroundTasks only. Service Bus branch removed |
| 5 | `ai_engine/pipeline/unified_pipeline.py` | `_write_to_lake()` | **OK** | `StorageClient.write()` |
| 6 | `ai_engine/pipeline/unified_pipeline.py` | `process()` read path | **OK** | Migrated to `StorageClient.list_files()` + `StorageClient.read()` |
| 7 | `ai_engine/pipeline/unified_pipeline.py` | extraction sources | **OK** | `StorageClient.list_files()` via `storage_prefix` config |
| 8 | `ai_engine/ingestion/pipeline_ingest_runner.py` | orchestrator | **OK** | No direct storage calls |
| 9 | `ai_engine/ingestion/document_scanner.py` | `scan_document_registry()` | **OK** | Migrated to `StorageClient.list_files()` |
| 10 | `ai_engine/ingestion/document_scanner.py` | `_read_text_content()` | **OK** | Migrated to `StorageClient.read()` |
| 11 | `ai_engine/ingestion/document_scanner.py` | Azure Search upsert | **DELETED** | `AzureSearchMetadataClient` reference removed entirely |
| 12 | `credit/modules/ai/memo_chapters.py` | `get_deal_im_pdf()` | **OK** | `StorageClient.exists/write/generate_read_url` via `gold_ic_memo_path()` |
| 13 | `credit/modules/ai/memo_chapters.py` | `rebuild_deal_im_pdf()` | **OK** | Same StorageClient pattern, force overwrite |
| 14 | `credit/modules/ai/artifacts.py` | `generate_fact_sheet()` | **OK** | `StorageClient.exists/write/generate_read_url` via `gold_artifact_path()` |
| 15 | `credit/modules/ai/artifacts.py` | `get_fact_sheet_pdf()` | **OK** | `StorageClient.list_files/generate_read_url` via `gold_artifact_path()` |
| 16 | `credit/modules/ai/artifacts.py` | `generate_marketing_presentation()` | **OK** | Same as fact sheet pattern |
| 17 | `credit/modules/ai/artifacts.py` | `get_marketing_presentation_pdf()` | **OK** | Same as fact sheet PDF pattern |
| 18 | `credit/modules/ai/portfolio.py` | `get_periodic_review_pdf()` | **OK** | `StorageClient.exists/write/generate_read_url` via `gold_portfolio_review_path()` |
| 19 | `credit/dataroom/routes/routes.py` | 10 deprecated endpoints | **DELETED** | All deprecated routes removed. Router registrations removed from `main.py` |
| 20 | `credit/modules/deals/routes.py` | `create_deal()` | **OK** | `StorageClient.write()` via `bronze_deal_path()` for context JSON + `.keep` markers |
| 21 | `credit/modules/deals/routes.py` | `upload_deal_document()` | **OK** | `StorageClient.write()` via `bronze_deal_path()` |
| 22 | `credit/modules/deals/routes.py` | `patch_deal_context()` | **OK** | `StorageClient.read()` + `StorageClient.write()` via `bronze_deal_path()` |
| 23 | `credit/reporting/routes/reports.py` | `generate_monthly_pack()` | **OK** | `StorageClient.write()` via `gold_credit_report_path(report_type="monthly")` |
| 24 | `credit/reporting/routes/reports.py` | `generate_investor_statement()` | **OK** | `StorageClient.write()` via `gold_credit_report_path(report_type="investor_statements")` |
| 25 | `credit/reporting/routes/reports.py` | `download_monthly_pack()` | **OK** | `StorageClient.read()` directly (shim removed) |
| 26 | `credit/reporting/routes/reports.py` | `download_investor_statement()` | **OK** | `StorageClient.read()` directly (shim removed) |
| 27 | `wealth/routes/documents.py` | upload + presigned URL | **OK** | `StorageClient.generate_upload_url()` + `StorageClient.write()` |
| 28 | `wealth/routes/fact_sheets.py` | write/read/list | **OK** | `StorageClient.write()`, `read()`, `list_files()` |
| 29 | `wealth/services/document_service.py` | `upload_document()` | **OK** | `StorageClient.write()` injected |
| 30 | `wealth/workers/brochure_ingestion.py` | download + extract | **OK** | `StorageClient.exists()`, `read()`, `write()` |
| 31 | `wealth/workers/fact_sheet_gen.py` | PDF generation | **OK** | `StorageClient.write()` with `gold_fact_sheet_path()` |
| 32 | `ai_engine/openai_client.py` | LLM calls | **OK** | Direct OpenAI API |
| 33 | `ai_engine/extraction/embedding_service.py` | embeddings | **OK** | `text-embedding-3-large` (3072 dims) via `openai_client.py` |
| 34 | `ai_engine/extraction/mistral_ocr.py` | OCR | **OK** | Direct Mistral API |
| 35 | `ai_engine/cache/provider_cache.py` | pipeline cache | **OK** | Local SQLite |
| 36 | `ai_engine/extraction/pgvector_search_service.py` | search + upsert | **OK** | pgvector with `organization_id` filter |
| 37 | `ai_engine/extraction/search_upsert_service.py` | Azure Search upsert | **DELETED** | File deleted. Replaced by `pgvector_search_service.py` |
| 38 | `ai_engine/pipeline/search_rebuild.py` | index rebuild | **OK** | Silver Parquet → pgvector |
| 39 | `services/search_index.py` | `AzureSearchMetadataClient` | **DELETED** | File deleted. Replaced by pgvector |
| 40 | `credit/global_agent/agent.py` | RAG retrieval | **OK** | pgvector + `openai_client.create_completion()` |
| 41 | `services/azure/blob_client.py` | Azure Blob client | **DELETED** | File deleted. Zero remaining callers |
| 42 | `services/blob_storage.py` | Legacy stub | **DELETED** | File deleted. All callers migrated to StorageClient |

---

## 3. Critical Path Analysis

### Credit Vertical

```
Upload (UI) --> StorageClient.generate_upload_url()     [OK]
           \--> pipeline_dispatch (BackgroundTasks)      [OK]
                  \--> unified_pipeline.process()
                         |--> StorageClient.list_files() [OK — migrated from list_blobs]
                         |--> StorageClient.read()       [OK — migrated from blob_uri+download_bytes]
                         |--> OCR (Mistral direct)       [OK]
                         |--> classify (hybrid, local)   [OK]
                         |--> chunk + embed (OpenAI)     [OK]
                         |--> _write_to_lake() (SC)      [OK]
                         \--> pgvector upsert            [OK]

Deal create   --> StorageClient.write() via bronze_deal_path()        [OK]
Deal doc      --> StorageClient.write() via bronze_deal_path()        [OK]
Deal context  --> StorageClient.read() + write() via bronze_deal_path [OK]

IC Memo PDF   --> StorageClient.write/exists/generate_read_url        [OK]
Fact Sheet    --> StorageClient.write/list_files/generate_read_url     [OK]
Marketing PDF --> StorageClient.write/list_files/generate_read_url     [OK]
Review PDF    --> StorageClient.write/exists/generate_read_url         [OK]

Monthly Pack  --> StorageClient.write() via gold_credit_report_path   [OK]
Inv Statement --> StorageClient.write() via gold_credit_report_path   [OK]
Pack Download --> StorageClient.read()                                [OK]
Stmt Download --> StorageClient.read()                                [OK]

Dataroom      --> DELETED (10 deprecated routes removed)
Doc Scanner   --> StorageClient.list_files() + read()                 [OK]

Global Agent  --> pgvector + OpenAI                                   [OK]
```

### Wealth Vertical

```
Upload (UI)   --> StorageClient.generate_upload_url()    [OK]
Upload (API)  --> StorageClient.write()                  [OK]
Download      --> StorageClient.read()                   [OK]
Fact Sheets   --> StorageClient.write/read/list           [OK]
Brochures     --> StorageClient.exists/read/write         [OK]
Pipeline      --> unified_pipeline (StorageClient)       [OK]
Search        --> pgvector                               [OK]
Embeddings    --> OpenAI direct                          [OK]
OCR           --> Mistral direct                         [OK]
```

**Both verticals fully migrated. Zero Azure storage dependencies remain.**

---

## 4. Deleted Files

| File | Reason | Deleted in |
|------|--------|-----------|
| `backend/app/services/azure/blob_client.py` | Deprecated Azure Blob SDK wrapper, zero callers | P2 |
| `backend/app/services/blob_storage.py` | Legacy stub (7/8 functions raised `NotImplementedError`) | P2 |
| `backend/app/services/search_index.py` | `AzureSearchMetadataClient`, replaced by pgvector | P2 |
| `backend/ai_engine/extraction/search_upsert_service.py` | Azure Search upsert, replaced by `pgvector_search_service.py` | P2 |
| `backend/tests/test_search_metadata_client.py` | Tested deleted `AzureSearchMetadataClient` | P2 |
| `backend/tests/test_search_tenant_isolation.py` | Tested deleted Azure Search OData isolation | P2 |
| `backend/tests/test_search_upsert_degraded.py` | Tested deleted `search_upsert_service` | P2 |
| `credit/documents/service.py` → `upload_document()` | Function deleted, superseded by SAS URL flow | P1 |
| `credit/documents/routes/ingest.py` → `POST /documents/upload` | Route deleted, only caller of `upload_document()` | P1 |

---

## 5. Remediation Log

### P0 — Broken endpoints (all resolved)

| # | File | Functions | Resolution |
|---|------|-----------|-----------|
| 1 | `credit/modules/deals/routes.py` | `create_deal`, `upload_deal_document`, `patch_deal_context` | Migrated to `StorageClient` + `bronze_deal_path()` |
| 2 | `credit/modules/ai/memo_chapters.py` | `get_deal_im_pdf`, `rebuild_deal_im_pdf` | Migrated to `StorageClient` + `gold_ic_memo_path()`. Converted to async |
| 3 | `credit/modules/ai/artifacts.py` | `generate_fact_sheet`, `get_fact_sheet_pdf`, `generate_marketing_presentation`, `get_marketing_presentation_pdf` | Migrated to `StorageClient` + `gold_artifact_path()`. Converted to async |
| 4 | `credit/modules/ai/portfolio.py` | `get_periodic_review_pdf` | Migrated to `StorageClient` + `gold_portfolio_review_path()`. Converted to async |
| 5 | `credit/reporting/routes/reports.py` | `generate_monthly_pack`, `generate_investor_statement` | Migrated to `StorageClient` + `gold_credit_report_path()` |
| 6 | `ai_engine/pipeline/unified_pipeline.py` | `process()` read path, extraction sources | `list_blobs` → `StorageClient.list_files()`, `blob_uri` → storage paths |
| 7 | `ai_engine/ingestion/document_scanner.py` | `scan_document_registry`, `_read_text_content` | `list_blobs` → `StorageClient.list_files()`, `blob_uri` → `StorageClient.read()` |

### P1 — Risk items (all resolved)

| # | File | Resolution |
|---|------|-----------|
| 8 | `credit/reporting/routes/reports.py` — downloads | Migrated from `download_bytes()` shim to `StorageClient.read()` directly |
| 9 | `credit/documents/service.py` — `upload_document()` | Confirmed superseded by SAS URL flow. Function + route deleted |
| 10 | `credit/dataroom/routes/routes.py` — deprecated endpoints | 10 deprecated routes deleted. Router registrations removed from `main.py` |
| 11 | `ai_engine/ingestion/document_scanner.py` — Azure Search | `AzureSearchMetadataClient` reference removed |

### P2 — Dead code cleanup (all resolved)

| # | Action | Resolution |
|---|--------|-----------|
| 12 | Delete `blob_client.py` | Deleted + 3 remaining callers migrated to StorageClient |
| 13 | Delete `search_index.py` | Deleted + 7 files cleaned, 3 test files deleted |
| 14 | Delete `search_upsert_service.py` | Deleted + references removed from extraction, knowledge |
| 15 | Remove Service Bus from `pipeline_dispatch.py` | Simplified to BackgroundTasks-only |
| 16 | Delete `blob_storage.py` | Deleted (all callers migrated in P0) |
| 17 | Remove `AZURE_STORAGE_*` settings | No settings declarations existed; references already cleaned |
| 18 | Remove Azure imports from `documents/service.py` | Resolved via function deletion in P1 |

---

## 6. Storage Path Helpers

Credit-specific path helpers added to `ai_engine/pipeline/storage_routing.py`:

| Helper | Pattern | Tier |
|--------|---------|------|
| `bronze_deal_path(org_id, deal_id, filename)` | `bronze/{org_id}/credit/pipeline/deals/{deal_id}/{filename}` | bronze |
| `gold_ic_memo_path(org_id, deal_id, filename)` | `gold/{org_id}/credit/ic_memoranda/{deal_id}/{filename}` | gold |
| `gold_artifact_path(org_id, deal_id, filename)` | `gold/{org_id}/credit/artifacts/{deal_id}/{filename}` | gold |
| `gold_portfolio_review_path(org_id, investment_id, filename)` | `gold/{org_id}/credit/portfolio_reviews/{investment_id}/{filename}` | gold |
| `gold_credit_report_path(org_id, fund_id, report_type, filename)` | `gold/{org_id}/credit/reports/{report_type}/{fund_id}/{filename}` | gold |

All paths validated with `_SAFE_PATH_SEGMENT_RE`. Never use f-strings in callers.

---

## 7. Remaining Stale References (non-blocking)

These are informational references in agent prompt templates, not code paths:

- `backend/app/domains/credit/global_agent/agent_context.py` — references `/api/v1/credit/dataroom/search` in agent prompt context
- `backend/app/domains/credit/global_agent/prompt_templates.py` — references `/api/v1/credit/dataroom/folders` in agent prompt context

These do not call the deleted routes and can be cleaned up when the global agent prompts are next revised.
