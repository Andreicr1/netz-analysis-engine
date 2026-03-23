---
title: "Ingestion Path Unification — 4 divergent paths consolidated into unified_pipeline.py"
date: 2026-03-15
module: backend/ai_engine/pipeline
component: unified_pipeline
problem_type: refactoring
severity: HIGH
tags:
  - ingestion
  - pipeline
  - monolith-decomposition
  - validation-gates
  - async-patterns
  - SSE
  - tenant-isolation
  - code-review
related_files:
  - backend/ai_engine/pipeline/unified_pipeline.py
  - backend/ai_engine/pipeline/models.py
  - backend/ai_engine/pipeline/validation.py
  - backend/ai_engine/extraction/extraction_orchestrator.py
  - backend/app/domains/credit/documents/routes/ingest.py
  - backend/app/core/jobs/tracker.py
  - backend/tests/test_pipeline_components.py
---

# Ingestion Path Unification — Phase 2

## Problem

The document processing pipeline had 4 divergent ingestion paths producing inconsistent analytical quality:

1. **UI Upload** — `ingestion_worker.py` used basic pypdf with page-boundary chunking, no classification, no governance detection
2. **Batch CLI** — `extraction_orchestrator.py` routed through `prepare_pdfs_full.py` (1786 LOC monolith) with Mistral OCR, Cohere classification, LLM extraction, semantic chunking
3. **Domain** — `domain_ingest_orchestrator.py` (825 LOC) used `document_intelligence.py` with LLM-only classification
4. **Legacy** — `document_classifier.py` with keyword heuristic for 7 types (unused by pipeline)

No inter-stage validation gates existed. A 60% content loss bug in `semantic_chunker` propagated silently. Bug fixes in one path never reached the others.

## Root Cause

Organic growth from a CLI batch tool (`prepare_pdfs_full.py`) into a backend service. The UI upload path was bolted on separately with a simpler pipeline. The domain orchestrator was added as a third path. No architectural consolidation was ever performed, so each path accumulated its own logic, its own classification system, and its own quality characteristics.

## Solution

`backend/ai_engine/pipeline/unified_pipeline.py` — a single async `process()` function that all sources call. Source-agnostic: the difference between UI and batch is priority and feedback (SSE events), not analytical quality.

**Stage-gate architecture:**
```
pre-filter → OCR → [gate] → classify → [gate] → governance
→ chunk → [gate] → extract metadata → [gate] → embed → [gate]
→ index → done
```

Every document gets the same pipeline: Mistral OCR, hybrid classification, governance detection, semantic chunking, parallel metadata extraction + summarization, embedding, and Azure Search indexing. On gate failure the pipeline halts for that document; other documents in a batch continue.

**Net LOC impact:** -2143 deleted, +1403 added (net -740 LOC).

## Key Design Decisions

### Stage-gate pattern with `_check_gate()` helper

A single helper replaces 4 duplicate gate-check blocks. It aggregates warnings, emits SSE error events, writes audit trail on failure, and returns a `PipelineStageResult` on failure (caller returns it) or `None` on success.

### Lazy imports to avoid circular dependencies

All heavy imports (`mistral_ocr`, `hybrid_classifier`, `semantic_chunker`, `embed_chunks`, `search_upsert_service`, `blob_storage`, `jobs/tracker`, `db/audit`) are imported inside the function body, not at module level. This prevents circular import chains between `ai_engine/` and `app/core/`. Only `TYPE_CHECKING` guard is used for `AsyncSession`.

### `asyncio.to_thread()` for sync operations

Three sync-heavy operations are wrapped: `download_bytes` (blob download), `embed_batch` (OpenAI embedding), and `upsert_chunks` (Azure Search upsert). `pdf_bytes` is explicitly `del`'d after OCR to release potentially large PDFs from memory.

### SSE tenant isolation via Redis job ownership

Before emitting SSE events, the pipeline registers job-to-org ownership in Redis via `register_job_owner(version_id, org_id)`. The SSE endpoint enforces that the authenticated tenant owns the job before streaming events. `_emit()` is fire-and-forget (swallowed on failure) so SSE issues never halt ingestion.

### Frozen data contracts

`IngestRequest(frozen=True)` enforces that `org_id` comes from JWT `actor.organization_id` (never request body). Path traversal validation in `__post_init__` rejects `..` or leading `/` in `blob_uri`. `PipelineStageResult(frozen=True)` carries stage name, success flag, data payload, metrics dict, warnings, and errors.

### Concurrent document processing

The UI route uses `asyncio.Semaphore(3)` + `asyncio.gather()` for bounded parallelism. Documents in a batch are processed concurrently with N+1 queries eliminated via batch Document pre-fetch.

## Code Review Findings Resolved (15 total)

### P1 — 8 findings (correctness/security)

| # | Finding | Fix |
|---|---------|-----|
| 019 | Hardcoded `domain="credit"` | → `request.vertical` |
| 020 | Duplicate skip_filter + governance_detector | Deleted ingestion/ copies, use extraction/ |
| 021 | Sync `download_bytes` blocks event loop | `asyncio.to_thread()` + `del pdf_bytes` |
| 022 | `db: Any` type erasure | `AsyncSession | None` via TYPE_CHECKING |
| 023 | `asyncio.run()` per PDF in orchestrator | Documented sync-only constraint |
| 024+025 | Nil UUID `org_id` + fund_id fallback | `document_id` fallback, docs on nil UUID |
| 026 | Broken `validate_extraction` gate | Removed (checked wrong fields) |
| 028 | Gate code duplicated 4x | Extracted `_check_gate()` helper |

### P2 — 4 findings (reliability/security)

| # | Finding | Fix |
|---|---------|-----|
| 027 | Sequential processing + N+1 query | Semaphore(3) + gather + batch pre-fetch |
| 029 | Raw exception strings leaked | Sanitized to generic messages, log server-side |
| 030 | SSE without tenant auth | `register_job_owner()` + Redis ownership check |
| 010 | Stale agent system prompt | Updated prompt + `build_agent_runtime_context()` |

### P3 — 3 findings (quality)

| # | Finding | Fix |
|---|---------|-----|
| 031 | Zero unit tests | 26 tests for skip_filter, governance_detector, validation gates |
| 032 | Bare dict routes, naive datetime | Pydantic schemas + `datetime.now(UTC)` |

## Migration Pattern

Callers were rewired without breaking public APIs:

- **UI route** — `process_pending` lazy-imports `IngestRequest` and `process`, constructs frozen request from DocumentVersion + Document + JWT actor. Status updates remain in the route handler.
- **Batch CLI** — `extraction_orchestrator.py` Step 3 delegates to `unified_pipeline.process()` per PDF via `asyncio.run()` (sync entry point).
- **Hidden callers** — 3 files importing via thin wrappers migrated to import directly from `document_classifier.py`. Wrappers deleted.
- **Classification package** — `__init__.py` exports `hybrid_classifier.classify` as public API.

## Prevention Strategies

### Prevention Checklist

- **Single entry point:** Any new ingestion source MUST flow through `unified_pipeline.process()`. Extend `IngestRequest` if needed — never create a parallel pipeline.
- **Validation gates between every stage.** Any new stage MUST have a validator returning `PipelineStageResult`. Content loss thresholds exist because 60% loss went undetected for months.
- **Frozen dataclasses for cross-boundary data.** Never pass mutable dicts or ORM objects across async/thread boundaries.
- **No `db: Any`.** Always `AsyncSession | None` via TYPE_CHECKING guard.
- **No sync I/O in async functions.** All blocking calls MUST use `asyncio.to_thread()`.
- **No nil UUID sentinels.** Use `None` with `Optional` typing, or raise early.
- **No hardcoded verticals.** Use `request.vertical`, never `"credit"` literals.
- **Canonical types in one place.** `CANONICAL_DOC_TYPES` in `pipeline/models.py` only.
- **SSE streams carry tenant context.** Every SSE job must call `register_job_owner()`.
- **Error messages never leak to clients.** Sanitize to error codes, log details server-side.
- **No module duplication across packages.** Search before creating new utilities.
- **Delete, do not deprecate.** Superseded modules are deleted in the same PR.

### CI Rules to Automate

- Grep for `db:\s*Any` — CI failure
- Import boundary: `ai_engine/` must never import from `app/domains/`
- Flag known sync functions called without `asyncio.to_thread` in `async def` bodies
- `@dataclass` without `frozen=True` in `pipeline/models.py` — CI failure
- `@router.(get|post|...)` without `response_model` — CI warning
- Single `.py` file exceeding 500 LOC — CI warning

### Code Review Checklist

1. Does the change add a new ingestion path bypassing `unified_pipeline.process()`?
2. Does any new stage have a validation gate returning `PipelineStageResult`?
3. Are ORM objects or mutable dicts passed to `asyncio.to_thread()`?
4. Is `db` typed as `AsyncSession` (not `Any`)?
5. Do exception handlers return raw `str(e)` to clients?
6. Does new SSE-emitting code call `register_job_owner()`?
7. Does the PR duplicate logic already in another package?
8. Are there N+1 query patterns in route handlers?
9. Are vertical strings hardcoded (`"credit"`, `"wealth"`)?
10. Are sync calls in async functions wrapped in `asyncio.to_thread()`?

## Related Documentation

| Document | Relevance |
|----------|-----------|
| [Pipeline LLM-Deterministic Alignment Plan](../../plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md) | Master plan — Phase 2 starts at Task 2.0 |
| [prepare_pdfs_full.py Diff Analysis](../prepare-pdfs-full-diff-analysis.md) | Line-by-line monolith mapping (Task 2.0 prerequisite) |
| [Hybrid Classifier Pattern](replace-external-ml-api-with-local-hybrid-classifier-DocumentClassifier-20260315.md) | Phase 1 — three-layer classifier integrated by Phase 2 |
| [Monolith-to-Modular Package Pattern](monolith-to-modular-package-with-library-migration.md) | Same decomposition pattern applied to EDGAR (precedent) |
| [Wave 1 Credit Modularization](wave1-credit-vertical-modularization-MonolithToPackages-20260315.md) | 31 files → 12 packages — import-linter DAG patterns |
| [Vertical Engine Extraction Patterns](vertical-engine-extraction-patterns.md) | SSE progress streaming, StorageClient, upload architecture |
| [Thread-Unsafe Rate Limiter](../runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md) | threading.Lock pattern for shared mutable state |
| [RLS Subselect 1000x Slowdown](../performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md) | Subselect pattern for all tenant-scoped queries |

### GitHub PRs

| PR | Phase | Description |
|---|---|---|
| #20 | Phase 1 | Deterministic foundation replacing Cohere |
| #21 | Phase 2 | Pipeline unification + 15 review fix findings |
