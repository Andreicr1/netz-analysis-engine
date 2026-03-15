---
title: "Phase 3: StorageClient + ADLS Bronze/Silver/Gold Dual-Write Pattern"
date: 2026-03-15
module: "Document ingestion pipeline"
problem_type: "architecture-pattern"
severity: "medium"
tags:
  - data-lake-integration
  - dual-write-pattern
  - storage-routing
  - search-index-rebuild
  - tenant-isolation
  - feature-flagging
  - async-parallelization
  - parquet
related_files:
  - backend/ai_engine/pipeline/storage_routing.py
  - backend/ai_engine/pipeline/unified_pipeline.py
  - backend/ai_engine/pipeline/search_rebuild.py
  - backend/ai_engine/extraction/search_upsert_service.py
  - backend/app/services/storage_client.py
  - backend/app/core/config/settings.py
pr: "https://github.com/Andreicr1/netz-analysis-engine/pull/22"
---

# Phase 3: StorageClient + ADLS Bronze/Silver/Gold Dual-Write Pattern

## Problem Statement

The ingestion pipeline wrote chunk embeddings directly to Azure AI Search as the sole storage layer. This created:

1. **No persistent source of truth** — Search corruption or schema changes meant permanent data loss
2. **No rebuild capability** — embedding model upgrades required full OCR re-processing (~30-60s per document)
3. **Tight coupling** — pipeline logic bound to Search upsert, no way to swap or rebuild independently
4. **Tenant isolation gap** — Azure Search documents lacked `organization_id` for filtering (Security F4)
5. **Missing settings** — `prefixed_index()`, `SEARCH_CHUNKS_INDEX_NAME` were referenced but never defined in Settings

## Solution

Three-component architecture: path routing + dual-write pipeline + search rebuild.

### 1. Path Routing (`storage_routing.py`)

Pure functions build deterministic ADLS paths with `{org_id}/{vertical}/` prefix:

```python
bronze_document_path(org_id, vertical, doc_id)  # → bronze/{org_id}/{vertical}/documents/{doc_id}.json
silver_chunks_path(org_id, vertical, doc_id)     # → silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet
silver_metadata_path(org_id, vertical, doc_id)   # → silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json
gold_memo_path(org_id, vertical, memo_id)        # → gold/{org_id}/{vertical}/memos/{memo_id}.json
global_reference_path(dataset, filename)         # → gold/_global/{dataset}/{filename}
```

Path validation via `_SAFE_PATH_SEGMENT_RE` (`^[a-zA-Z0-9][a-zA-Z0-9._\-]*$`) rejects traversal, injection, empty segments. Vertical validated against `{"credit", "wealth"}`.

### 2. Dual-Write Pipeline (`unified_pipeline.py`)

**Stage 8 — ADLS write (source of truth):**

```python
# Build all payloads first
bronze_payload = json.dumps({"ocr_text": ocr_text, ...}).encode()
parquet_bytes = await asyncio.to_thread(_build_chunks_parquet, chunks, doc_id_str)
meta_payload = json.dumps({"doc_type": ..., "summary": ..., ...}).encode()

# Write all three in parallel (~60% latency reduction vs sequential)
bronze_ok, silver_ok, meta_ok = await asyncio.gather(
    _write_to_lake(bronze_path, bronze_payload),
    _write_to_lake(silver_path, parquet_bytes, content_type="application/octet-stream"),
    _write_to_lake(meta_path, meta_payload),
)
```

**Stage 9 — Azure Search upsert (derived index):**

Search upsert happens AFTER ADLS write. If ADLS succeeds but Search fails, data is safe and can be rebuilt.

**Fire-and-forget pattern:** `_write_to_lake()` returns `bool`, logs failure as warning, does not halt pipeline. Failures surfaced in `PipelineStageResult.warnings`.

**Parquet schema** includes `embedding_model`, `embedding_dim`, `governance_critical`, `governance_flags` for lossless rebuild.

### 3. Search Rebuild (`search_rebuild.py`)

Reconstructs Azure Search from silver Parquet without reprocessing PDFs:

```python
async def rebuild_search_index(org_id, vertical, *, doc_ids=None) -> RebuildResult:
    # Reads chunks.parquet from silver layer
    # Validates embedding_dim matches current model (rejects mismatches)
    # Upserts to Azure Search via build_search_document()
    # Per-document error isolation — one failure doesn't abort batch
```

### 4. Security F4 — `organization_id` in Search Documents

```python
# In build_search_document():
if organization_id is not None:
    doc["organization_id"] = str(organization_id)
# filterable=True, retrievable=False in Azure Search schema
# All RAG queries MUST include $filter=organization_id eq '{org_id}'
```

### 5. Settings Additions

```python
SEARCH_CHUNKS_INDEX_NAME: str = "global-vector-chunks-v2"
NETZ_ENV: str = "dev"
OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"

def prefixed_index(self, base_name: str) -> str:
    """dev-global-vector-chunks-v2 in dev, unprefixed in prod."""
    if self.NETZ_ENV in ("prod", "production"):
        return base_name
    return f"{self.NETZ_ENV}-{base_name}"
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| ADLS before Search (dual-write ordering) | Search failures don't lose data; rebuild recovers |
| Parquet for chunks (zstd compression) | Columnar, self-describing schema, efficient rebuild |
| JSON for bronze/metadata | Human-readable, simple debugging |
| `asyncio.gather()` for parallel writes | ~60% latency reduction on storage stage |
| `_write_to_lake()` fire-and-forget | Pipeline completes even if ADLS has transient failure |
| Embedding dim in Parquet schema | Prevents silent corruption on model upgrade |
| `_global/` paths (no org_id) | FRED, ETF benchmarks shared across all tenants |

## Code Review Findings Resolved

7 findings from 7 review agents (kieran-python-reviewer, security-sentinel, performance-oracle, architecture-strategist, pattern-recognition-specialist, code-simplicity-reviewer, learnings-researcher):

| # | Finding | Fix |
|---|---------|-----|
| F1 (P1) | 3 sequential `_write_to_lake()` calls | `asyncio.gather()` parallelization |
| F2 (P1) | `for i in range(len(table))` anti-pattern | `table.to_pylist()` |
| F3 (P2) | ADLS failures not surfaced as warnings | Added to `warnings` list |
| F4 (P2) | Missing governance fields in Parquet | Added `governance_critical` + `governance_flags` |
| F5 (P2) | Duplicate import block | Merged into single import |
| F6 (P2) | Dead `_VALID_TIERS` frozenset | Removed |
| F7 (P2) | Shadowed `import uuid` | Removed, use module-level `UUID` |

## Prevention Strategies

### Parallel I/O Enforcement
Flag sequential `await` calls on independent operations during review. Require explicit justification if writes must be sequential.

### PyArrow Access Patterns
Use `table.to_pylist()` or `table.to_pydict()` for row access. Never `for i in range(len(table))` — O(rows * columns) scalar access on columnar format.

### Silent Failure Surfacing
Every cloud operation fallback must: (1) log at WARNING level with `exc_info=True`, (2) surface in pipeline result warnings, (3) track as boolean metric.

### Parquet Schema Governance
Include `embedding_model` + `embedding_dim` in all Parquet files. Rebuild service validates before upsert. Any schema addition requires: backward compat test, migration plan, documentation update.

### Dual-Write Consistency
Source of truth (ADLS) writes before derived index (Search). Test write ordering. Test partial failure (ADLS succeeds, Search fails → data safe, warning logged).

## Test Coverage

18 tests in `test_phase3_storage.py`:
- Path routing: correct paths, traversal rejection, invalid vertical
- Search document: `organization_id` included/omitted correctly
- Parquet: round-trip fidelity with embeddings, governance fields
- Storage: LocalStorageClient write/read, directory creation
- Rebuild: embedding dimension mismatch rejection, correct dim acceptance

## Related Documents

- [Pipeline Plan (Phase 3)](../../plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md) — Tasks 3.1-3.4 acceptance criteria
- [Pipeline Brainstorm](../../brainstorms/2026-03-15-pipeline-llm-deterministic-alignment-brainstorm.md) — Decision 5 (path routing), Decision 7 (ADLS source of truth)
- [Phase 2: Ingestion Path Unification](unified-pipeline-ingestion-path-consolidation-Phase2-20260315.md) — Stage-gate pattern, frozen dataclasses
- [Vertical Engine Extraction Patterns](vertical-engine-extraction-patterns.md) — StorageClient implementation, `asyncio.to_thread()` pattern
- [Prepare PDFs Diff Analysis](../prepare-pdfs-full-diff-analysis.md) — Metadata fields preserved through pipeline
