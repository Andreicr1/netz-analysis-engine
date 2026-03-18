---
date: 2026-03-18
topic: duckdb-data-lake-inspection-layer
---

# DuckDB Data Lake Inspection Layer

## What We're Building

A read-only DuckDB service layer (`DuckDBClient`) that queries silver/gold Parquet files in the data lake for pipeline observability and data quality inspection. This is an **operational tool**, not a product-facing analytics engine.

The framing is: **camada de inspeção do data lake** — answering operational questions that today require ad-hoc code or manual inspection of Parquet files.

## Why This Approach

### Problem

The silver layer Parquet exists (14 credit deals indexed, wealth data growing). But the only access paths today are:

- Azure Search (derived index — no operational metadata)
- `search_rebuild.py` (manual, full-scan reconstruction)
- Ad-hoc Python scripts

This means simple operational questions have no answer without writing code:

- "Quais chunks têm `embedding_model` desatualizado?"
- "Quantos documentos por deal estão no silver layer?"
- "Quais deals têm cobertura de extração abaixo de X%?"

### Approaches Considered

**Approach A: DuckDB Service Layer (CHOSEN)**
Singleton `DuckDBClient` in `app/services/duckdb_client.py`. Typed methods for each query. Receives paths from `StorageClient`. Connection-per-query for thread safety.

- Pros: Centralized, type-safe, testable, clean migration path to ADLS httpfs
- Cons: Each new query requires a new method (acceptable — queries are finite)
- Best when: Query set is finite and predictable (our case)

**Approach B: Generic Query Layer (REJECTED)**
SQL templates executed dynamically. Flexible but creates SQL injection surface, violates IP protection principles, over-engineered for 5-10 operational queries.

**Approach C: Inline DuckDB (REJECTED)**
Each caller creates its own connection. No central point for storage migration. Queries scattered across codebase. Doesn't scale.

## Key Decisions

### 1. Phased Rollout

| Phase | Scope | Storage | Consumers | Trigger |
|-------|-------|---------|-----------|---------|
| **1 (now)** | Pipeline observability | Local filesystem via StorageClient | Backend services only | Immediate value |
| **2 (Sprint 2b/3)** | Admin API endpoints | Same | Admin frontend (DataTable hardened) | Sprint 2a closes DataTable hardening |
| **3 (future)** | Cross-fund analytics | ADLS httpfs via `get_duckdb_path()` | Quant engine, wealth analytics | Single-tenant Parquet >500MB or query latency exceeds threshold |

### 2. Storage Integration: (c) now, path to (b)

Phase 1 uses `StorageClient` to resolve local paths. DuckDB reads from filesystem directly (`.data/lake/` in dev).

**Critical design decision:** `StorageClient` interface gains `get_duckdb_path()` NOW — even though Phase 1 only uses the local branch.

```python
# StorageClient interface extension (Phase 1: returns local path, Phase 3: returns abfss://)
class StorageClient(ABC):
    @abstractmethod
    def get_duckdb_path(self, tier: str, org_id: str, vertical: str) -> str:
        """Returns path readable by DuckDB — local filesystem or abfss:// URI.

        DuckDB never calls ADLS SDK directly. Credential management stays
        in StorageClient. This preserves the 'never call ADLS SDK directly' rule.
        """
        ...
```

- `LocalStorageClient.get_duckdb_path()` → returns `.data/lake/{tier}/{org_id}/{vertical}/`
- `ADLSStorageClient.get_duckdb_path()` → returns `abfss://{container}@{account}.dfs.core.windows.net/{tier}/{org_id}/{vertical}/` (Phase 3, configures httpfs credentials)

This prevents anyone from implementing httpfs directly in `DuckDBClient`, breaking StorageClient encapsulation.

### 3. Connection Strategy: connection-per-query

DuckDB here is **read-only by definition** — the pipeline writes Parquet, DuckDB only reads. Read-only connections are safe for parallel access.

- **Phase 1:** Connection-per-query. Overhead is negligible for low-frequency operational queries (~ms to create in-memory connection).
- **Phase 3 (future):** Evaluate singleton connection pool when DuckDB becomes analytics query layer with latency-sensitive paths.

```python
# Phase 1: connection-per-query — simplest, safest
def _execute(self, sql: str, params: dict | None = None) -> list[dict]:
    conn = duckdb.connect()  # in-memory, read-only Parquet scans
    try:
        result = conn.execute(sql, params or {}).fetchdf()
        return result.to_dict("records")
    finally:
        conn.close()
```

### 4. Query Catalog (Phase 1)

Finite set of typed methods — not a generic query engine:

| Method | Purpose | Source |
|--------|---------|--------|
| `stale_embeddings(org_id, model)` | Chunks with outdated `embedding_model` | silver chunks Parquet |
| `document_coverage(org_id)` | Documents per deal in silver layer | silver metadata JSON/Parquet |
| `extraction_quality(org_id, threshold)` | Deals with extraction coverage below threshold | silver metadata |
| `chunk_stats(org_id)` | Total chunks, avg size, distribution by doc_type | silver chunks Parquet |
| `embedding_dimension_audit()` | Chunks with `embedding_dim` != expected (3072) | silver chunks Parquet |

All methods enforce `WHERE organization_id = ?` — consistent with RLS everywhere.

### 5. RLS Enforcement

DuckDB queries are NOT covered by PostgreSQL RLS policies. Tenant isolation must be enforced at the application layer:

- Every query method receives `org_id` as required parameter
- Every SQL includes `WHERE organization_id = :org_id`
- No method allows querying across tenants (cross-tenant analytics is Phase 3, requires explicit `_global/` path)
- `storage_routing.py` path builders already enforce `{org_id}/{vertical}/` — DuckDB reads from tenant-scoped paths

### 6. Integration with Existing Services

| Existing Service | DuckDB Replaces | How |
|-----------------|-----------------|-----|
| `search_rebuild.py` | PyArrow Parquet reads | `DuckDBClient.stale_embeddings()` for pre-rebuild validation |
| `vector_integrity_guard.py` | Embedding dimension validation | `DuckDBClient.embedding_dimension_audit()` |
| Pipeline monitoring | Nothing (new capability) | `DuckDBClient.chunk_stats()`, `document_coverage()` |

### 7. No Product-Facing Exposure

DuckDB results are never returned directly to end-user APIs. They feed:
- Internal validation (pipeline quality gates)
- Admin observability (Phase 2 endpoints)
- Quant engine inputs (Phase 3)

This is consistent with "prompts are Netz IP" — operational metadata is internal.

## Open Questions

1. **Parquet schema evolution** — If silver Parquet schema changes (new columns), do we version the schema or let DuckDB infer? Recommendation: let DuckDB infer (it handles schema evolution natively for Parquet).
2. **Query timeout** — Should `DuckDBClient` enforce a max query duration? Recommendation: yes, 30s default for Phase 1 (operational queries should be fast).
3. **Caching** — Should results be cached? Recommendation: no for Phase 1. Parquet files change on pipeline runs, and query frequency is low.

## Next Steps

-> `/ce:plan` for implementation details (file changes, tests, integration points)
