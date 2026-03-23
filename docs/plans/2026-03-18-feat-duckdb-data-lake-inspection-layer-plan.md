---
title: "feat: DuckDB Data Lake Inspection Layer"
type: feat
status: active
date: 2026-03-18
origin: docs/brainstorms/2026-03-18-duckdb-data-lake-inspection-layer-brainstorm.md
deepened: 2026-03-18
---

# DuckDB Data Lake Inspection Layer

## Enhancement Summary

**Deepened on:** 2026-03-18
**Research agents:** DuckDB best practices, DuckDB Python API docs
**Review agents:** Architecture Strategist, Security Sentinel, Performance Oracle, Data Integrity Guardian, Pattern Recognition, Learnings Researcher

### Key Improvements from Deepening

1. **Structural tenant isolation** — `_execute()` takes `org_id: UUID` as required param, injects WHERE automatically
2. **`get_duckdb_path()` as concrete method** (not abstract) — avoids breaking mocks and LSP violation
3. **No `ai_engine` imports** — embedding constants passed as params from callers, keeping dependency unidirectional
4. **`union_by_name=true`** on all queries — handles legacy Parquet without `organization_id` column gracefully
5. **`fetchall()` + `description`** instead of `fetchdf()` — avoids pandas dependency
6. **Memory/thread hardening** — `SET memory_limit='256MB'`, `SET threads=2`, semaphore reduced to 2
7. **`silver_chunks_glob()`** in `storage_routing.py` — single source of truth for path patterns
8. **Security lockdown** — `enable_external_access=false`, SELECT-only guard, blocked columns check
9. **`COUNT(embedding)` replaced** with `embedding_dim IS NOT NULL` — avoids 12KB/row I/O on embedding vectors
10. **`org_id: UUID`** (not `str`) — matches `storage_routing.py`, structurally prevents path injection

### Risks Discovered

- Legacy Parquet files return empty until pipeline re-processes (acceptable — 14 deals)
- `embedding_dim` is declarative metadata, not actual vector length (Phase 2 improvement)
- `LocalStorageClient.write()` is not atomic (separate fix, not DuckDB-specific)

---

## Overview

Read-only DuckDB service that queries silver/gold Parquet files for pipeline observability and data quality inspection. Phase 1 is backend-only — no admin API endpoints, no cross-fund analytics, no product-facing exposure.

The framing is **data lake inspection**, not analytics engine. It answers operational questions that today require ad-hoc code: stale embeddings, document coverage gaps, extraction quality, chunk statistics.

## Problem Statement

The silver layer Parquet exists (14 credit deals indexed, wealth data growing). The only access paths are pgvector (derived index — no operational metadata, replaced Azure Search in commit 497df51) and `search_rebuild.py` (manual full-scan). Simple operational questions have no answer:

- "Which chunks have an outdated `embedding_model`?"
- "How many documents per deal are in the silver layer?"
- "Which deals have extraction coverage below threshold?"
- "Are all embedding dimensions consistent at 3072?"

## Proposed Solution

`DuckDBClient` singleton service in `app/services/duckdb_client.py` with typed query methods. Connection-per-query (read-only, thread-safe). Paths resolved via `StorageClient`. Tenant isolation enforced structurally at application layer.

(See brainstorm: `docs/brainstorms/2026-03-18-duckdb-data-lake-inspection-layer-brainstorm.md`)

## Technical Approach

### Architecture

```
storage_routing.silver_chunks_glob(org_id, vertical)
        │
        ▼
StorageClient.get_duckdb_path(tier, org_id, vertical)
        │
        ▼
  ┌─────────────┐     ┌──────────────────────────┐
  │ DuckDBClient │────▶│ silver/{org_id}/{vertical}│
  │  (read-only) │     │   /chunks/*/chunks.parquet│
  └──────┬──────┘     └──────────────────────────┘
         │
    5 typed methods
    (connection-per-query)
    (org_id: UUID required)
         │
    ┌────┴────┐
    ▼         ▼
 search_   pipeline
 rebuild   validation
```

### Pre-Requisite: Fix Parquet Schema (organization_id)

**CLAUDE.md Data Lake Rule #5:** "All workers must write Parquet with `organization_id` as a column AND as a path segment."

Current `_build_chunks_parquet()` writes 17 columns — `organization_id` is NOT among them. This is a pre-existing violation.

**Fix:** Add `org_id: str` parameter to `_build_chunks_parquet()`. Add `organization_id` as 18th column. Update call site at `unified_pipeline.py:771` to pass `request.org_id`.

**Legacy file handling:** All queries use `union_by_name=true` in `read_parquet()`. Legacy files without `organization_id` produce NULL for that column, which the `WHERE organization_id = ?` clause filters out. Result: empty results for legacy data (not errors).

### StorageClient Extension: `get_duckdb_path()`

Add as a **concrete method** (not abstract) with `NotImplementedError` default — avoids breaking existing mocks and test doubles across the 1304-test suite:

```python
# storage_client.py — new concrete method on ABC
def get_duckdb_path(self, tier: Literal["bronze", "silver", "gold"], org_id: UUID, vertical: str) -> str:
    """Return path readable by DuckDB for a tenant's data tier.

    This is the only sync, non-I/O method on StorageClient.
    Subclasses override to provide backend-specific paths.

    LocalStorageClient  → filesystem path (.data/lake/{tier}/{org_id}/{vertical}/)
    ADLSStorageClient   → raises NotImplementedError (Phase 3: azure extension + abfss://)
    """
    raise NotImplementedError(
        f"{self.__class__.__name__} does not support DuckDB path resolution. "
        "See Phase 3 in future-architecture-roadmap.md"
    )
```

`LocalStorageClient` overrides with `_resolve()` guard (path traversal protection):

```python
def get_duckdb_path(self, tier: Literal["bronze", "silver", "gold"], org_id: UUID, vertical: str) -> str:
    _validate_segment(str(org_id))
    _validate_segment(vertical)
    relative = f"{tier}/{org_id}/{vertical}"
    resolved = self._resolve(relative)  # resolve() + startswith(root) check
    return str(resolved)
```

### Path Routing: `silver_chunks_glob()`

Add to `storage_routing.py` to keep path patterns in one place:

```python
def silver_chunks_glob(org_id: UUID, vertical: str) -> str:
    """Glob pattern for all silver chunk Parquet files for a tenant."""
    _validate_segment(str(org_id))
    _validate_segment(vertical)
    return f"silver/{org_id}/{vertical}/chunks/*/chunks.parquet"
```

`DuckDBClient._parquet_glob()` delegates to this rather than hardcoding the suffix.

### DuckDBClient Service

```python
# app/services/duckdb_client.py
import logging
import uuid
from dataclasses import dataclass
from typing import Literal

import duckdb

from ai_engine.pipeline.storage_routing import silver_chunks_glob
from app.services.storage_client import StorageClient, get_storage_client

logger = logging.getLogger(__name__)  # stdlib logging — matches app/services/ convention

# Columns that must NEVER appear in SELECT (IP protection + memory safety)
_BLOCKED_COLUMNS = frozenset({"content", "embedding"})

class DuckDBClient:
    def __init__(self, storage: StorageClient) -> None:
        self._storage = storage

    def _execute(
        self,
        sql: str,
        org_id: uuid.UUID,
        params: list | None = None,
        *,
        method: str = "",
    ) -> list[dict]:
        """Connection-per-query with structural tenant isolation.

        org_id is REQUIRED — injected into every query via parameterization.
        Never reference 'content' or 'embedding' columns directly.
        """
        if not sql.strip().upper().startswith("SELECT"):
            raise ValueError("DuckDBClient only supports SELECT queries")

        conn = duckdb.connect()
        try:
            conn.execute("SET memory_limit = '256MB'")
            conn.execute("SET threads = 2")
            conn.execute("SET enable_object_cache = true")
            conn.execute("SET allow_community_extensions = false")
            conn.execute("SET autoinstall_known_extensions = false")

            result = conn.execute(sql, params or [])
            columns = [desc[0] for desc in result.description]

            if _BLOCKED_COLUMNS & set(columns):
                raise ValueError(
                    f"Query must not select blocked columns: {_BLOCKED_COLUMNS & set(columns)}"
                )

            rows = result.fetchall()
            return [dict(zip(columns, row)) for row in rows]

        except duckdb.IOException as e:
            logger.warning("duckdb_io_error", extra={"method": method, "org_id": str(org_id), "error": str(e)})
            return []
        except duckdb.BinderException as e:
            logger.warning("duckdb_schema_mismatch", extra={"method": method, "org_id": str(org_id), "error": str(e)})
            return []
        except duckdb.InvalidInputException as e:
            logger.error("duckdb_corrupted_input", extra={"method": method, "org_id": str(org_id), "error": str(e)})
            return []
        except duckdb.Error as e:
            logger.error("duckdb_unexpected_error", extra={"method": method, "org_id": str(org_id), "error_type": type(e).__name__, "error": str(e)})
            return []
        finally:
            conn.close()

    def _parquet_glob(self, org_id: uuid.UUID, vertical: str) -> str:
        """Full filesystem glob for a tenant's silver chunks.

        get_duckdb_path("silver", org_id, vertical) returns e.g.:
            .data/lake/silver/{org_id}/{vertical}
        We append the chunks glob suffix to get:
            .data/lake/silver/{org_id}/{vertical}/chunks/*/chunks.parquet
        """
        base = self._storage.get_duckdb_path("silver", org_id, vertical)
        return f"{base}/chunks/*/chunks.parquet"
```

**Singleton pattern** (same as `storage_client.py`):

```python
_client: DuckDBClient | None = None

def get_duckdb_client() -> DuckDBClient:
    global _client  # noqa: PLW0603
    if _client is None:
        _client = DuckDBClient(get_storage_client())
    return _client
```

No teardown function needed — DuckDB is connection-per-query with no persistent state.

### Query Methods — Phase 1 Catalog

All methods use `union_by_name=true` for schema evolution tolerance. All accept `org_id: UUID` as required positional parameter. Embedding constants passed as params from callers (no `ai_engine` imports in DuckDBClient).

#### 1. `stale_embeddings(org_id, vertical, current_model, expected_dim) -> list[StaleEmbeddingResult]`

```python
@dataclass(frozen=True)
class StaleEmbeddingResult:
    doc_id: str
    chunk_count: int
    embedding_model: str
```

```sql
SELECT doc_id, COUNT(*) as chunk_count, embedding_model
FROM read_parquet(?, union_by_name = true)
WHERE organization_id = ?
  AND embedding_model != ?
GROUP BY doc_id, embedding_model
LIMIT 10000
```

**Consumer:** `search_rebuild.py` — passes `EMBEDDING_MODEL_NAME` from `vector_integrity_guard.py`.

#### 2. `document_coverage(org_id, vertical) -> list[DocumentCoverageResult]`

```python
@dataclass(frozen=True)
class DocumentCoverageResult:
    doc_id: str
    doc_type: str
    chunk_count: int
    total_chars: int
    has_embeddings: bool
```

```sql
SELECT doc_id, doc_type, COUNT(*) as chunk_count,
       SUM(char_count) as total_chars,
       BOOL_OR(embedding_dim IS NOT NULL AND embedding_dim > 0) as has_embeddings
FROM read_parquet(?, union_by_name = true)
WHERE organization_id = ?
GROUP BY doc_id, doc_type
LIMIT 10000
```

**Performance note:** Uses `embedding_dim IS NOT NULL` instead of `COUNT(embedding) > 0`. The `embedding` column is 12KB/row (3072 float32). Reading `embedding_dim` (4 bytes int32) is ~3000x less I/O.

#### 3. `extraction_quality(org_id, vertical, min_chars=50) -> list[ExtractionQualityResult]`

```python
@dataclass(frozen=True)
class ExtractionQualityResult:
    doc_id: str
    doc_type: str
    total_chunks: int
    empty_chunks: int
    governance_flagged: int
    avg_char_count: float
```

```sql
SELECT doc_id, doc_type,
       COUNT(*) as total_chunks,
       SUM(CASE WHEN char_count < ? THEN 1 ELSE 0 END) as empty_chunks,
       SUM(CASE WHEN governance_critical THEN 1 ELSE 0 END) as governance_flagged,
       AVG(char_count) as avg_char_count
FROM read_parquet(?, union_by_name = true)
WHERE organization_id = ?
GROUP BY doc_id, doc_type
LIMIT 10000
```

#### 4. `chunk_stats(org_id, vertical) -> ChunkStatsResult`

```python
@dataclass(frozen=True)
class ChunkStatsResult:
    total_chunks: int
    total_documents: int
    total_chars: int
    avg_chunk_chars: float
    median_chunk_chars: float
    p95_chunk_chars: float
    doc_type_distribution: dict[str, int]
```

Two queries: aggregate stats + doc_type `GROUP BY`. `doc_type_distribution` dict is mutable inside frozen dataclass — acceptable for Phase 1, callers documented not to mutate.

#### 5. `embedding_dimension_audit(org_id, vertical, expected_dim) -> list[DimensionMismatchResult]`

```python
@dataclass(frozen=True)
class DimensionMismatchResult:
    doc_id: str
    chunk_count: int
    embedding_dim: int
```

```sql
SELECT doc_id, COUNT(*) as chunk_count, embedding_dim
FROM read_parquet(?, union_by_name = true)
WHERE organization_id = ?
  AND embedding_dim != ?
GROUP BY doc_id, embedding_dim
LIMIT 10000
```

**Consumer:** `search_rebuild.py` — passes `EMBEDDING_DIMENSIONS` from `vector_integrity_guard.py`.

### Async Integration

DuckDB is sync. All query methods are sync. Async callers use `asyncio.to_thread()`. DuckDBClient provides optional async wrappers with lazy semaphore:

```python
class DuckDBClient:
    _semaphore: asyncio.Semaphore | None = None

    async def async_stale_embeddings(self, org_id: UUID, vertical: str, **kw) -> list[StaleEmbeddingResult]:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(2)  # max 2 concurrent DuckDB queries
        async with self._semaphore:
            return await asyncio.to_thread(self.stale_embeddings, org_id, vertical, **kw)
```

Semaphore(2) not 4 — at 256MB per connection, 2 concurrent = 512MB DuckDB ceiling, safe for 4GB container.

### Error Handling

| Error | DuckDB Exception | Behavior |
|-------|-----------------|----------|
| Parquet not found | `IOException` (single) or empty (glob) | Log warning, return `[]` |
| Corrupted Parquet | `InvalidInputException` | Log error with path, return `[]` |
| Missing column (legacy) | `BinderException` | Handled by `union_by_name=true` (NULL-filled) |
| Query timeout (>30s) | N/A | `asyncio.wait_for(30)` at caller |
| Memory pressure | `OutOfMemoryException` | Caught by `duckdb.Error`, return `[]` |
| Blocked column selected | `ValueError` (internal) | Raised immediately — this is a bug |

All errors logged with stdlib `logging` (matching `app/services/` convention) including `org_id`, `vertical`, and method name.

### Tenant Isolation (Defense-in-Depth)

Three layers:

1. **Path-level:** `get_duckdb_path("silver", org_id, vertical)` scopes glob to `silver/{org_id}/{vertical}/`. DuckDB physically cannot read another tenant's files. `_validate_segment()` + `_resolve()` prevent path traversal.
2. **Query-level:** `WHERE organization_id = ?` in every SQL — structural via `_execute()` receiving `org_id: UUID` as required param.
3. **Type-level:** `org_id: UUID` (not `str`) — structurally prevents path injection since `str(uuid.UUID(...))` only produces hex-and-dashes.

### Security Hardening

Per-connection lockdown in `_execute()`:

```python
conn.execute("SET memory_limit = '256MB'")
conn.execute("SET threads = 2")
conn.execute("SET allow_community_extensions = false")
conn.execute("SET autoinstall_known_extensions = false")
```

Additional guards:
- SELECT-only check: reject SQL not starting with `SELECT`
- Blocked columns check: reject results containing `content` or `embedding`
- All file paths parameterized with `?` — never interpolated into SQL strings

## Implementation Phases

### Phase 1: Parquet Schema Fix (pre-requisite)

Add `organization_id` column to silver Parquet.

**Files:**
- `backend/ai_engine/pipeline/unified_pipeline.py` — add `org_id: str` param to `_build_chunks_parquet()`, add to schema and row dict, update call site at line 771 to pass `request.org_id`
- `backend/tests/test_phase3_storage.py` — update column assertions (17 → 18)

**Acceptance Criteria:**
- [ ] `_build_chunks_parquet()` writes 18 columns including `organization_id`
- [ ] Call site passes `request.org_id`
- [ ] Existing tests updated for new schema
- [ ] No regression in pipeline tests

### Phase 2: StorageClient Extension + Path Routing

**Files:**
- `backend/app/services/storage_client.py` — concrete `get_duckdb_path()` on ABC, override in `LocalStorageClient`
- `backend/ai_engine/pipeline/storage_routing.py` — add `silver_chunks_glob()`
- `backend/tests/test_storage_client.py` — new tests

**Acceptance Criteria:**
- [ ] `get_duckdb_path()` is concrete (not abstract) with `NotImplementedError` default
- [ ] `LocalStorageClient.get_duckdb_path()` returns resolved path with `_validate_segment()` + `_resolve()` guards
- [ ] `ADLSStorageClient` inherits default `NotImplementedError`
- [ ] `silver_chunks_glob()` added to `storage_routing.py`
- [ ] `tier` param typed as `Literal["bronze", "silver", "gold"]`
- [ ] `org_id` param typed as `UUID`
- [ ] Tests cover path resolution, traversal rejection, ADLS NotImplementedError

### Phase 3: DuckDBClient Core

**Files:**
- `backend/app/services/duckdb_client.py` (new)
- `pyproject.toml` — add `duckdb>=1.2` to `[ai]` group, add `duckdb.*` to mypy `ignore_missing_imports`

**Acceptance Criteria:**
- [ ] `DuckDBClient.__init__` accepts `StorageClient`
- [ ] `_execute()` takes `org_id: UUID` as required param
- [ ] `_execute()` sets `memory_limit`, `threads`, security pragmas
- [ ] `_execute()` uses `fetchall()` + `description` (no pandas)
- [ ] `_execute()` checks `_BLOCKED_COLUMNS` on result
- [ ] `_execute()` rejects non-SELECT SQL
- [ ] `_parquet_glob()` uses `storage_routing.silver_chunks_glob()`
- [ ] Singleton `get_duckdb_client()` with `# noqa: PLW0603`
- [ ] No imports from `ai_engine` — constants passed as params
- [ ] Uses stdlib `logging` (not `structlog`)

### Phase 4: Query Methods + Result Dataclasses

**Files:**
- `backend/app/services/duckdb_client.py` — 5 methods + 5 result dataclasses + async wrappers

**Acceptance Criteria:**
- [ ] All 5 methods accept `org_id: UUID` as required positional param
- [ ] `stale_embeddings()` and `embedding_dimension_audit()` accept constants as required params
- [ ] All SQL uses `union_by_name = true` in `read_parquet()`
- [ ] All SQL includes `LIMIT 10000`
- [ ] `document_coverage` uses `embedding_dim IS NOT NULL` (NOT `COUNT(embedding)`)
- [ ] Async wrappers with lazy `Semaphore(2)`
- [ ] All methods handle empty globs (no Parquet files) gracefully

### Phase 5: Tests

**Files:**
- `backend/tests/test_duckdb_client.py` (new)

**Test Fixtures:**
- `_make_test_parquet()` helper — creates valid 18-column Parquet in `tmp_path` with zstd compression
- Fixture with stale embedding model
- Fixture with wrong embedding dimension
- Fixture with empty chunks (char_count = 0)
- Fixture with governance_critical = True
- Fixture with missing `organization_id` column (legacy simulation)
- Empty Parquet (zero rows, valid schema)
- Multi-document fixture (3+ doc_ids)
- Multi-tenant fixture (org_A + org_B in separate paths)

**Test Cases:**
- [ ] `stale_embeddings` returns docs with outdated model, empty when all current
- [ ] `document_coverage` returns per-doc stats, correct aggregation
- [ ] `extraction_quality` identifies empty chunks and governance flags
- [ ] `chunk_stats` returns correct aggregates (count, avg, median, p95)
- [ ] `embedding_dimension_audit` catches dimension mismatches
- [ ] All methods return empty list when no Parquet files exist
- [ ] Legacy files (no `organization_id`) filtered out via `union_by_name` + WHERE
- [ ] **Tenant isolation: org_A query returns zero org_B data** (critical security test)
- [ ] `get_duckdb_client()` returns singleton
- [ ] Non-SELECT SQL raises `ValueError`
- [ ] Blocked column in result raises `ValueError`
- [ ] Invalid UUID for org_id raises

### Phase 6: Consumer Integration

**Files:**
- `backend/ai_engine/pipeline/search_rebuild.py` — call `stale_embeddings()` + `embedding_dimension_audit()` before rebuild

**Acceptance Criteria:**
- [ ] `search_rebuild.py` logs stale embedding count before rebuilding
- [ ] Passes `EMBEDDING_MODEL_NAME` and `EMBEDDING_DIMENSIONS` from `vector_integrity_guard.py`
- [ ] Graceful import: `search_rebuild.py` works without DuckDB installed (try/except ImportError)
- [ ] No new test failures in existing pipeline tests
- [ ] No bidirectional `app ↔ ai_engine` coupling (ai_engine imports from app.services, not reverse)

## System-Wide Impact

### Interaction Graph

`DuckDBClient` is a leaf node — reads Parquet, returns frozen dataclasses. No callbacks, no middleware, no events. Dependency direction: `ai_engine → app.services.duckdb_client` (same direction as existing `ai_engine → app.services.storage_client`).

### Error Propagation

DuckDB errors caught inside `_execute()`, converted to empty results + log warnings. No exceptions propagate to callers. Consistent with pipeline "never-raises" for non-critical operations. Exception: `ValueError` for blocked columns or non-SELECT SQL — these are bugs, not runtime errors.

### State Lifecycle

Stateless. Connection-per-query, no caches, no side effects. The singleton holds only a reference to `StorageClient`.

### Performance at Scale

| Document Count | Metadata Query | Embedding Query (if allowed) |
|----------------|---------------|------------------------------|
| 14 (current) | ~5-10ms | ~50ms |
| 100 | ~20-40ms | ~300ms |
| 1000 | ~100-200ms | ~2-5s (OOM risk) |

At 100+ documents, consider upgrading to cached read-only connection (eliminates ~50-100ms Parquet metadata re-reads per query). Not needed for Phase 1.

## Dependencies & Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| `duckdb` package size (~80MB) | Low | Backend only. Not shipped to frontend. |
| Legacy Parquet files lack `organization_id` | Medium | `union_by_name=true` + WHERE filters them out. Empty results until re-processed. |
| `get_duckdb_path()` on StorageClient | Low | Concrete method, not abstract. Existing mocks inherit `NotImplementedError` default. |
| DuckDB memory exhaustion | Medium | `SET memory_limit='256MB'`, `Semaphore(2)`, `LIMIT 10000`, no embedding column |
| `ADLSStorageClient` raises in prod | Low | Phase 1 is dev/staging. Phase 3 adds `azure` extension (not `httpfs`) for ADLS. |
| Phase 3 extension install vs security lockdown | Low | `_execute()` sets `autoinstall_known_extensions=false`. The `azure` extension must be pre-installed in the container image (`duckdb.connect().execute("INSTALL azure")`), NOT at query time. Document in CLAUDE.md when Phase 3 lands. |
| Future query forgets tenant filter | Critical | `_execute()` requires `org_id: UUID` — structural enforcement |
| Path traversal via org_id | High | `UUID` type + `_validate_segment()` + `_resolve()` in LocalStorageClient |

## Sources & References

### Origin

- **Brainstorm:** [`docs/brainstorms/2026-03-18-duckdb-data-lake-inspection-layer-brainstorm.md`](../brainstorms/2026-03-18-duckdb-data-lake-inspection-layer-brainstorm.md)

### Research (Deepening)

- DuckDB Python API: `duckdb.connect()`, `read_parquet()`, `union_by_name`, exception hierarchy
- DuckDB `azure` extension (not `httpfs`) for Phase 3 ADLS: `CREATE SECRET` with `CONNECTION_STRING`
- Connection-per-query validated as correct for read-only Parquet (~0.5ms overhead)
- `fetchall()` + `description` preferred over `fetchdf()` (avoids pandas dep)

### Institutional Learnings Applied

- `docs/solutions/architecture-patterns/phase3-storageclient-adls-dualwrite-pattern-20260315.md` — Parquet schema governance, dual-write ordering
- `docs/solutions/security-issues/azure-search-tenant-isolation-organization-id-filtering-20260315.md` — UUID validation, fail-closed pattern, org_id threading
- `docs/solutions/architecture-patterns/vertical-engine-extraction-patterns.md` — `asyncio.to_thread()` pattern, ABC extension, non-abstract concrete methods
- `docs/solutions/runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md` — connection-per-query is thread-safe by design

### Internal References

- StorageClient ABC: `backend/app/services/storage_client.py`
- Parquet schema: `backend/ai_engine/pipeline/unified_pipeline.py:421-482`
- Path routing: `backend/ai_engine/pipeline/storage_routing.py`
- Embedding constants: `backend/ai_engine/validation/vector_integrity_guard.py:15-16`
- Search rebuild: `backend/ai_engine/pipeline/search_rebuild.py`
- Singleton pattern: `backend/app/services/storage_client.py:267-289`

### CLAUDE.md Rules Applied

- "StorageClient for all storage" → DuckDB gets paths via `get_duckdb_path()`
- "Path routing via storage_routing.py" → `silver_chunks_glob()` added to `storage_routing.py`
- "DuckDB queries must always include WHERE organization_id = ?" → structural via `_execute(org_id: UUID)`
- "Parquet schema must include embedding metadata" → validated via `embedding_dimension_audit()`
- "No module-level asyncio primitives" → Semaphore lazy-created inside async methods
- "ORM thread safety: frozen dataclasses across async/thread boundary" → all results are `@dataclass(frozen=True)`

