# Data Architecture & Safeguards — Netz Analysis Engine

**Version:** 1.0
**Date:** 2026-03-19
**Audience:** Technical stakeholders, compliance officers, prospective clients (gestoras)

---

## 1. Overview

Netz Analysis Engine is a multi-tenant platform serving institutional investment managers (gestoras). Each gestora is a **tenant** identified by a unique `organization_id` (UUID). All client data — documents, analyses, configurations — is isolated at every layer of the stack: database, storage, search, caching, and streaming.

This document describes the complete data lifecycle from document upload through analytical output, the technology providers involved, and the safeguards that protect third-party data at each stage.

---

## 2. Technology Stack

| Layer | Provider | Purpose | Encryption |
|-------|----------|---------|------------|
| **Database** | Timescale Cloud (PostgreSQL 16 + pgvector + TimescaleDB) | Structured data, embeddings, time-series | TLS in transit, AES-256 at rest (platform-managed) |
| **Object Storage** | Cloudflare R2 (S3-compatible) | Data lake — raw documents, processed chunks, analytical outputs | TLS in transit, AES-256 at rest (platform-managed) |
| **Cache / Pub-Sub** | Upstash Redis | Job tracking, SSE event streaming, config cache invalidation | TLS enforced (rediss://) |
| **Authentication** | Clerk | JWT v2 tokens, organization management, RBAC | RS256 asymmetric signatures, JWKS key rotation |
| **LLM** | OpenAI API | Document analysis, memo generation, classification fallback | TLS in transit, data not used for training (API ToS) |
| **OCR** | Mistral API | PDF text extraction with table detection | TLS in transit |
| **Embedding** | OpenAI API (text-embedding-3-large) | 3072-dimensional document vectors for semantic search | TLS in transit |
| **Hosting** | Railway | Container hosting (FastAPI backend + SvelteKit frontends) | TLS termination at edge |

**No data leaves the tenant boundary without explicit action.** LLM and OCR calls send document content to OpenAI/Mistral for processing — these providers do not retain API data for training per their enterprise terms of service.

---

## 3. Data Lake Architecture (Bronze / Silver / Gold)

All documents flow through a three-tier data lake stored in Cloudflare R2. Each tier represents a different stage of processing maturity.

### 3.1 Path Convention

Every tenant-scoped path begins with `{tier}/{organization_id}/`, enforced by `storage_routing.py`. No caller builds paths manually — all paths are constructed via validated helper functions that reject directory traversal, null bytes, and non-alphanumeric characters.

```
netz-data-lake/                          (R2 bucket)
|
+-- bronze/                              TIER 1: Raw ingested data
|   +-- {org_id}/
|       +-- {fund_id}/
|       |   +-- documents/
|       |       +-- {version_id}/
|       |           +-- {filename.pdf}   <-- Original uploaded file
|       +-- credit/
|       |   +-- documents/
|       |       +-- {doc_id}.json        <-- Raw OCR output (JSON)
|       +-- wealth/
|           +-- documents/
|               +-- {doc_id}.json
|
+-- silver/                              TIER 2: Processed & enriched data
|   +-- {org_id}/
|       +-- credit/
|       |   +-- chunks/
|       |   |   +-- {doc_id}/
|       |   |       +-- chunks.parquet   <-- Semantic chunks + embeddings (zstd)
|       |   +-- documents/
|       |       +-- {doc_id}/
|       |           +-- metadata.json    <-- Extracted metadata + summary
|       +-- wealth/
|           +-- chunks/
|           |   +-- {doc_id}/
|           |       +-- chunks.parquet
|           +-- documents/
|               +-- {doc_id}/
|                   +-- metadata.json
|
+-- gold/                                TIER 3: Analytical outputs
|   +-- {org_id}/
|   |   +-- credit/
|   |   |   +-- memos/
|   |   |       +-- {memo_id}.json       <-- IC memos (14 chapters)
|   |   +-- wealth/
|   |       +-- dd_reports/
|   |       |   +-- {report_id}/{lang}/report.pdf
|   |       +-- fact_sheets/
|   |       |   +-- {portfolio_id}/{date}/{lang}/{file}.pdf
|   |       +-- content/
|   |           +-- {type}/{id}/{lang}/report.pdf
|   +-- _global/                         <-- Reference data (no tenant scope)
|       +-- fred_indicators/             <-- 45 FRED macro series
|       +-- benchmarks/                  <-- ETF/index benchmark data
```

### 3.2 Tier Definitions

| Tier | Content | Mutability | Retention |
|------|---------|------------|-----------|
| **Bronze** | Original uploaded PDFs + raw OCR JSON | Append-only (new versions create new paths) | Indefinite — source of truth for reprocessing |
| **Silver** | Semantic chunks (Parquet with embeddings) + extracted metadata (JSON) | Overwritten on reprocessing | Derived from bronze — can be rebuilt without OCR/LLM |
| **Gold** | IC memos, DD reports, fact sheets, analytical outputs | Versioned per generation | Business-critical outputs |
| **_global** | FRED macro indicators, ETF benchmarks | Refreshed by scheduled workers | Shared across all tenants — no client data |

### 3.3 Parquet Schema Requirements

All silver-layer Parquet files must include:

| Column | Type | Purpose |
|--------|------|---------|
| `organization_id` | UUID | Redundant tenant filter (belt-and-suspenders with path isolation) |
| `embedding_model` | string | e.g., `text-embedding-3-large` — prevents silent corruption on model upgrade |
| `embedding_dim` | int | e.g., `3072` — validated during search index rebuild |

Compression: zstd (Parquet default). The `search_rebuild.py` utility validates dimension match before upserting to pgvector — rejects entire documents on mismatch.

---

## 4. Document Ingestion Flow

### 4.1 Upload Entry Points

Documents enter the system through two paths, both converging on the same unified pipeline:

**Path A — Frontend Upload (two-step presigned URL)**

```
Client                      Backend                       R2
  |                           |                            |
  |-- POST /upload-url ------>|                            |
  |                           |-- create Document record   |
  |                           |-- generate presigned URL ->|
  |<-- { upload_url } --------|                            |
  |                           |                            |
  |-- PUT upload_url (file) -------------------------------->|
  |                           |                            |
  |-- POST /upload-complete ->|                            |
  |                           |-- mark as PROCESSING       |
  |<-- { job_id } ------------|                            |
  |                           |                            |
  |-- GET /jobs/{id}/stream ->|-- SSE progress events      |
```

**Path B — API Direct Upload (single POST)**

```
Client                      Backend                       R2
  |                           |                            |
  |-- POST /upload (file) --->|                            |
  |                           |-- create Document record   |
  |                           |-- storage.write() -------->|
  |<-- { document_id } ------|                            |
```

Both paths store the file at: `bronze/{org_id}/{fund_id}/documents/{version_id}/{filename}`

### 4.2 Unified Pipeline (10 Stages)

Once a document is in bronze storage, the unified pipeline processes it through 10 sequential stages with 5 validation gates. A gate failure halts processing for that document only — other documents in a batch continue.

```
STAGE 0   Pre-filter          Skip compliance forms (regex)
           |
STAGE 1   OCR                 Mistral API: PDF -> markdown (tables as HTML)
           |
         [GATE 1]             Min 100 chars, max 30% non-printable
           |
STAGE 2   Classification      3-layer hybrid classifier (rules -> cosine -> LLM)
           |
         [GATE 2]             doc_type in canonical list, confidence >= 0.3
           |
STAGE 3   Governance          15-pattern regex scan for red flags
           |
STAGE 4   Chunking            Semantic markdown chunking
           |
         [GATE 3]             chunk_count > 0, content loss < 25%
           |
STAGE 5   Metadata            Entity extraction + summary (parallel, LLM)
           |
STAGE 6   Embedding           OpenAI text-embedding-3-large (3072-dim)
           |
         [GATE 4]             Dimension match, no NaN values
           |
STAGE 7   Storage             Dual-write: bronze JSON + silver Parquet + silver metadata
           |
STAGE 8   Indexing             pgvector upsert (vector_chunks table)
           |
         [GATE 5]             Upsert result validation
           |
STAGE 9   Terminal             Audit event + SSE terminal event + Redis cleanup
```

### 4.3 Dual-Write Ordering

Storage writes follow strict ordering:

1. **R2 write** (source of truth) — bronze OCR JSON + silver Parquet + silver metadata
2. **pgvector upsert** (derived index) — embeddings + metadata for semantic search

If R2 succeeds but pgvector fails: data is safe in R2, warning logged, index can be rebuilt later via `search_rebuild.py` without any OCR or LLM calls.

If R2 fails: pipeline continues with warning — data not persisted to lake but pipeline state tracked for retry.

### 4.4 Classification (No External ML APIs)

The hybrid classifier uses three layers with cost escalation:

| Layer | Method | Coverage | Cost | Provider |
|-------|--------|----------|------|----------|
| 1 | 26 filename patterns + 13 content regex | ~60% | Free | Local rules |
| 2 | TF-IDF cosine similarity (37 synthetic exemplars) | ~30% | Free | scikit-learn (local) |
| 3 | LLM fallback | ~10% | API call | OpenAI |

31 canonical document types, 6 vehicle types. No external ML classification APIs — Cohere dependency was removed entirely.

### 4.5 Search Index Rebuild

The search index (pgvector `vector_chunks` table) is a **derived index**, not a source of truth. It can be fully reconstructed from silver-layer Parquet files:

```
search_rebuild.py:
  1. Acquire Redis advisory lock (prevents concurrent rebuilds)
  2. List all silver Parquet files in R2
  3. Validate embedding dimensions match current model
  4. Build search documents from Parquet columns
  5. Upsert to pgvector with organization_id
  6. Release lock
```

Zero OCR calls, zero LLM calls. Pure data movement from R2 to PostgreSQL.

---

## 5. Tenant Isolation Safeguards

### 5.1 Database Layer — Row-Level Security (RLS)

Every tenant-scoped table has a PostgreSQL RLS policy:

```sql
CREATE POLICY org_isolation ON {table}
  USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
  WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
```

**How it works:**

1. Every API request extracts `organization_id` from the Clerk JWT token
2. `get_db_with_rls()` opens a database transaction and executes `SET LOCAL app.current_organization_id = '{org_id}'`
3. `SET LOCAL` is transaction-scoped — automatically cleared on commit/rollback, safe for connection pooling
4. All subsequent queries in that transaction can only see/modify rows belonging to that organization
5. If RLS context is not set, a fail-closed PL/pgSQL function raises an exception

**Critical implementation detail:** RLS policies use `(SELECT current_setting(...))` subselect, not bare `current_setting()`. Without the subselect, PostgreSQL evaluates the function per-row instead of once per-query, causing 1000x slowdown on large tables.

**Global tables (no RLS):** `macro_data`, `allocation_blocks`, `vertical_config_defaults`, `benchmark_nav` — these contain shared reference data with no tenant-specific content.

### 5.2 Storage Layer — Path Isolation

All R2 paths are constructed by validated helper functions in `storage_routing.py`:

- `_validate_segment()` — rejects empty strings, directory traversal (`..`), special characters
- `_validate_vertical()` — allowlist: `{"credit", "wealth"}`
- `_SAFE_PATH_SEGMENT_RE` — regex `^[a-zA-Z0-9][a-zA-Z0-9._\-]*$`

**No caller builds storage paths with f-strings.** All paths go through:

```python
bronze_upload_blob_path(org_id, fund_id, version_id, filename)
bronze_document_path(org_id, vertical, doc_id)
silver_chunks_path(org_id, vertical, doc_id)
silver_metadata_path(org_id, vertical, doc_id)
gold_memo_path(org_id, vertical, memo_id)
```

The `StorageClient` abstraction adds a second layer of path validation, rejecting absolute paths, null bytes, and traversal attempts.

### 5.3 Search Layer — Parameterized Queries

All pgvector queries include `WHERE organization_id = :org_id::uuid` as a parameterized bind variable (never string interpolation):

```sql
SELECT id, content, embedding <=> :query_embedding AS distance
FROM vector_chunks
WHERE organization_id = :org_id::uuid
  AND deal_id = :deal_id
  AND embedding IS NOT NULL
ORDER BY distance
LIMIT :top_k
```

UUID validation (`validate_uuid()`) canonicalizes input before any query execution.

### 5.4 SSE / Job Streaming — Ownership Registry

Real-time progress streaming uses Redis pub/sub with tenant ownership verification:

1. `register_job_owner(job_id, org_id)` — stores `job:{id}:org = org_id` in Redis with TTL
2. Before SSE subscription: `verify_job_owner(job_id, org_id)` checks ownership — **fail-closed** (returns False if key missing or expired)
3. `publish_terminal_event()` reduces TTL to 120s grace period for final reconnect

A tenant cannot subscribe to another tenant's job stream.

### 5.5 Configuration — Scoped Overrides

ConfigService cascade: TTLCache (60s) -> DB Override (RLS-scoped) -> DB Default (global) -> YAML fallback (ERROR).

Per-tenant config overrides use explicit `WHERE organization_id = :org_id` **plus** RLS — belt-and-suspenders. Prompts and internal config types are filtered from client-facing API responses via `CLIENT_VISIBLE_TYPES` allowlist.

### 5.6 Authentication — Clerk JWT v2

| Aspect | Implementation |
|--------|---------------|
| **Algorithm** | RS256 (asymmetric) |
| **Key management** | JWKS endpoint with automatic key rotation |
| **Claims** | `o.id` (organization_id), `o.rol` (roles), `o.slg` (slug) |
| **Validation** | Signature + expiry + required claims |
| **Dev bypass** | `X-DEV-ACTOR` header, only when `APP_ENV=development` |
| **Production guard** | Startup rejects `APP_ENV=development` if production Clerk secrets are present |

### 5.7 Audit Trail

Every mutating operation records an `AuditEvent`:

| Field | Content |
|-------|---------|
| `actor_id` | User who performed the action |
| `actor_roles` | Role array at time of action |
| `action` | CREATE, UPDATE, DELETE |
| `entity_type`, `entity_id` | Target resource |
| `before_state`, `after_state` | JSONB snapshots (full diff) |
| `fund_id` | Optional fund scope |
| `request_id` | Correlation ID for request tracing |

Audit events are tenant-scoped via RLS — a tenant can only query their own audit log.

Pipeline stages emit per-stage audit events: `OCR_COMPLETE`, `CLASSIFICATION_COMPLETE`, `CHUNKING_COMPLETE`, `INDEXING_COMPLETE`, `INGESTION_COMPLETE`.

---

## 6. Data Flow Summary

```
                         EXTERNAL PROVIDERS
                    +--------+  +--------+  +-------+
                    | Mistral|  | OpenAI |  | Clerk |
                    |  (OCR) |  | (LLM)  |  | (Auth)|
                    +---+----+  +---+----+  +---+---+
                        |           |           |
    ============= TLS encrypted in transit =============
                        |           |           |
                    +---v-----------v-----------v---+
                    |         BACKEND (Railway)      |
                    |  +-------------------------+   |
                    |  | Unified Pipeline         |   |
  Upload (R2)      |  |  OCR -> Classify -> Chunk |  |
  +----------+     |  |  -> Embed -> Store -> Index| |
  | Client   |---->|  +----------+--+---+--------+  |
  | (Browser |     |             |  |   |            |
  |  or API) |     |  +----------v--v---v--------+   |
  +----------+     |  |                          |   |
                    |  |   PostgreSQL (Timescale) |   |
                    |  |   RLS per organization   |   |
                    |  |   pgvector embeddings    |   |
                    |  +--------------------------+   |
                    |                                 |
                    |  +--------------------------+   |
                    |  |   Cloudflare R2           |   |
                    |  |   bronze/ silver/ gold/   |   |
                    |  |   {org_id}/ path prefix   |   |
                    |  +--------------------------+   |
                    |                                 |
                    |  +--------------------------+   |
                    |  |   Upstash Redis           |   |
                    |  |   Job ownership registry  |   |
                    |  |   SSE pub/sub channels    |   |
                    |  +--------------------------+   |
                    +--------------------------------+
```

---

## 7. Safeguard Summary Matrix

| Threat | Safeguard | Layer | Pattern |
|--------|-----------|-------|---------|
| Cross-tenant data access | RLS policies on all tenant tables | Database | Fail-closed (`SET LOCAL` + subselect) |
| Cross-tenant storage access | `{org_id}/` path prefix + validation | Storage | Regex allowlist, no manual path construction |
| Cross-tenant search results | Parameterized `WHERE organization_id` | Search | Bind variables, UUID validation |
| Cross-tenant job streaming | Redis ownership registry | Cache | Fail-closed (`verify_job_owner`) |
| Path traversal / injection | `_SAFE_PATH_SEGMENT_RE` + `_validate_path()` | Storage | Reject `..`, null bytes, absolute paths |
| Malicious document content | 5 validation gates in pipeline | Pipeline | Per-document halt on failure |
| Corrupted embeddings | Dimension + NaN validation | Pipeline | Reject on mismatch, rebuild from Parquet |
| Stale config serving wrong tenant | PgNotifier cache invalidation + TTL | Config | Belt-and-suspenders: explicit filter + RLS |
| Unauthorized API access | Clerk JWT RS256 + role-based guards | Auth | Signature + expiry + claims validation |
| Dev bypass in production | `validate_production_secrets()` at startup | Auth | RuntimeError if dev mode with prod secrets |
| Data loss on index failure | Dual-write: R2 first, pgvector second | Storage | R2 is source of truth; index is rebuildable |
| Audit gap | `write_audit_event()` on all mutations | Audit | Before/after JSONB snapshots, RLS-scoped |

---

## 8. Provider Data Handling

| Provider | What we send | Retention policy | Training opt-out |
|----------|-------------|------------------|------------------|
| **OpenAI** | Document text (for analysis, embedding, classification L3) | Not retained per API ToS (zero-day retention on API tier) | API data not used for training |
| **Mistral** | PDF binary (for OCR extraction) | Not retained per API ToS | API data not used for training |
| **Clerk** | User identity, org membership | Retained for auth (user-managed deletion) | N/A (auth provider) |
| **Timescale Cloud** | All structured data + embeddings | Managed PostgreSQL (encrypted at rest, customer-controlled) | N/A (database provider) |
| **Cloudflare R2** | All documents + analytical outputs | Object storage (encrypted at rest, customer-controlled) | N/A (storage provider) |
| **Upstash Redis** | Job IDs, org IDs, SSE events (no document content) | Ephemeral (TTL-based, max 1 hour) | N/A (cache provider) |

**No document content is stored in Redis.** Redis holds only job metadata (job_id, org_id, event type) for real-time streaming coordination.

**No document content is sent to Clerk.** Clerk receives only authentication tokens and organization membership data.

---

## 9. Disaster Recovery

| Scenario | Recovery path | Data loss |
|----------|---------------|-----------|
| **pgvector index corruption** | `search_rebuild.py` reconstructs from silver Parquet in R2 | Zero (no OCR/LLM needed) |
| **R2 bronze data loss** | Original files must be re-uploaded | Re-upload required |
| **R2 silver data loss** | Re-run unified pipeline from bronze layer | Zero (OCR + LLM re-invoked) |
| **R2 gold data loss** | Re-generate memos/reports from silver + pipeline | Zero (LLM re-invoked) |
| **PostgreSQL failure** | Timescale Cloud automated backups (point-in-time recovery) | Per backup window |
| **Redis failure** | Ephemeral data only — SSE clients reconnect, jobs restart | Active SSE streams interrupted |

**Source of truth hierarchy:** R2 bronze > R2 silver > pgvector index. Each downstream layer can be rebuilt from its upstream source.
