---
title: "Dead Code Audit — 6 Legacy ai_engine Modules Deleted (-2,105 LOC)"
date: 2026-03-15
module: "backend/ai_engine, backend/app/domains/credit/modules, worker_app"
problem_type: architecture-patterns
severity: MEDIUM
tags:
  - dead-code
  - technical-debt
  - refactoring
  - broken-imports
  - legacy-modules
  - code-cleanup
  - pipeline-consolidation
status: resolved
---

# Dead Code Audit — 6 Legacy ai_engine Modules Deleted (-2,105 LOC)

## Problem

Six modules accumulated as dead code in `ai_engine/` after the unified pipeline (Phase 2, PRs #20-#22) and hybrid classifier replaced them. The Phase 2 plan listed 7 files for deletion but only 5 were actually deleted — `document_classifier.py` and `domain_ingest_orchestrator.py` survived because their callers were never migrated.

Additionally, `deal_intelligence_repo.py` was imported by `registry_bridge.py` and `pipeline/persistence.py` but **never existed** in the repo's git history. This caused Stage 3 and Stage 4 of `pipeline_ingest_runner.py` to crash silently at runtime, hidden by lazy imports and broad exception handling.

### Symptoms

1. **Silent pipeline failures** — Stage 4 (batch ingestion) always failed with `ModuleNotFoundError` from `deal_intelligence_repo.py`, caught by `except Exception` handler
2. **1,917 LOC of unreachable code** — 6 modules with zero callers or broken dependencies
3. **Stale worker functions** — 3 Azure Functions workers in `function_app.py` referenced deleted operational modules (`compliance`, `portfolio`, `reporting`)
4. **CLAUDE.md drift** — architecture listing referenced deleted modules

## Root Cause

The Phase 2 pipeline consolidation (PRs #20-#22) replaced 4 divergent ingestion paths with `unified_pipeline.process()` and replaced the keyword classifier with `hybrid_classifier.py`. However:

1. **Incomplete caller migration** — 3 callers of `document_classifier.py` (`monitoring.py`, `document_scanner.py`, `documents.py`) were documented as "migrated" in the solution doc but actually still imported from the old module
2. **Phantom module** — `deal_intelligence_repo.py` was referenced in the orchestrator and registry bridge but never created. Lazy imports inside function bodies hid the `ImportError` from the test suite (337 tests pass because no test exercises these specific code paths)
3. **Product scope reduction** — operational modules (`compliance`, `portfolio`, `reporting`) were intentionally removed but `function_app.py` worker handlers weren't updated

## Solution

### Files Deleted (6 files, -2,105 LOC)

| File | LOC | Why Dead |
|------|-----|----------|
| `classification/document_classifier.py` | 463 | Superseded by `hybrid_classifier.py`; 3 callers migrated |
| `ingestion/domain_ingest_orchestrator.py` | 825 | Superseded by `unified_pipeline.py`; imported non-existent module |
| `extraction/chunking.py` | 214 | Thin wrapper around `semantic_chunker.py`; only caller was orchestrator |
| `ingestion/ingest_runner.py` | 157 | CLI wrapper; zero callers, never registered |
| `knowledge/knowledge_ingest_runner.py` | 524 | Zero callers anywhere in codebase |
| `pdf/ic_cover.py` | 14 | Stub with explicit "DELETE THIS FILE" comment |

### Caller Migrations

**Batch classification functions** (`classify_documents`, `classify_registered_documents`) moved from `document_classifier.py` into `document_scanner.py` — the natural home since scanner already owns the `DocumentRegistry` lifecycle:

```python
# Before (3 callers):
from ai_engine.classification.document_classifier import classify_documents

# After (same 3 callers, new source):
from ai_engine.ingestion.document_scanner import classify_documents
```

**`reanalyze_deal` endpoint** inlined from orchestrator into `extraction.py` — was a 3-line convenience wrapper:

```python
# Before:
from ai_engine.ingestion.domain_ingest_orchestrator import reanalyze_deal
reanalyze_deal(session, pipeline_deal_id=deal_id)

# After (inlined):
from app.domains.credit.modules.deals.ai_mode import resolve_ai_mode
from vertical_engines.credit.domain_ai import run_deal_ai_analysis

ctx = resolve_ai_mode(session, pipeline_deal_id=deal_id)
run_deal_ai_analysis(
    session,
    deal_id=ctx.entity_id,
    fund_id=ctx.fund_id,
    domain=ctx.mode.value,
    deal_name=ctx.deal_name,
    sponsor_name=ctx.sponsor_name,
)
```

**Pipeline Stage 4** removed from both sync and async paths in `pipeline_ingest_runner.py` — was already a runtime crash:

```python
# Before: Stage 4 called orchestrator (always crashed)
from ai_engine.ingestion.domain_ingest_orchestrator import run_ingest_for_unindexed_documents

# After: Stage 4 skipped with explanatory comment
logger.info("[Stage 4/5] Skipped — document ingestion handled by unified pipeline per-upload")
```

### Broken Import Fix

Created `deal_intelligence_repo.py` (90 LOC) with two idempotent functions that `registry_bridge.py` and `persistence.py` had been importing from a non-existent module:

- `register_deal_document()` — idempotent DealDocument creation via `(deal_id, blob_path)` unique constraint
- `update_deal_ai_output()` — write AI screening output (`ai_summary`, `ai_risk_flags`, `ai_key_terms`) to `PipelineDeal`

### Worker Cleanup

Removed 3 dead worker functions from `function_app.py` referencing deleted operational modules:
- `compliance_worker` — referenced `app.domain.compliance` (out of scope)
- `obligation_monitor` — referenced `app.domain.portfolio` (out of scope)
- `report_schedule_runner` — referenced `app.domain.reporting` (out of scope)
- `memo_worker` `ai_review_analysis` branch — referenced `app.domain.documents` (out of scope)

## Verification

- **337 tests pass** — no regressions
- **5 import-linter contracts maintained** — no DAG violations
- **Zero remaining imports** to any deleted module (verified via codebase-wide grep)
- **CLAUDE.md updated** — removed stale references, added `registry_bridge` to ingestion listing

## Prevention Checklist

For future refactor PRs that delete modules:

1. **Pre-deletion caller audit** — `grep -r "from.*<module>" backend/ worker_app/` to find ALL callers including lazy imports
2. **Import validation test** — add `test_all_imports_valid()` that imports every module to catch phantom dependencies
3. **Worker app inclusion** — extend import checks to `worker_app/` (not just `backend/`)
4. **CLAUDE.md sync** — update architecture listing in the same commit as module deletion
5. **Plan vs. reality check** — after completing a plan, verify all planned deletions actually happened
6. **Delete, do not deprecate** — superseded modules should be deleted in the same PR, not left as stubs (per unified pipeline consolidation pattern)

## Key Insight: Lazy Imports Hide Broken Dependencies

The `deal_intelligence_repo.py` bug survived because:
- `registry_bridge.py:25` was a top-level import, but `pipeline_ingest_runner.py` imported `bridge_registry_to_deal_documents` inside a `try/except` block (lazy) — the `ImportError` was caught and logged as a "stage failure"
- `persistence.py:86` was a deferred import inside a function body — only crashes when that function is called
- No test ever exercises these code paths, so 337 tests pass despite the broken import

**Lesson:** Tests that pass don't mean code works. Lazy imports with broad exception handling can hide `ModuleNotFoundError` indefinitely. An import-time validation test catches this pattern.

## Related Documentation

- [Unified Pipeline Ingestion Path Consolidation (Phase 2)](unified-pipeline-ingestion-path-consolidation-Phase2-20260315.md) — the refactor that superseded the orchestrator
- [Replace External ML API with Local Hybrid Classifier](replace-external-ml-api-with-local-hybrid-classifier-DocumentClassifier-20260315.md) — the refactor that superseded document_classifier
- [Wave 1 Credit Vertical Modularization](wave1-credit-vertical-modularization-MonolithToPackages-20260315.md) — established the "delete, do not deprecate" pattern
- [Wave 2 Deep Review Modularization](wave2-deep-review-modularization-MonolithToDAGPackage-20260315.md) — staged extraction pattern for complex monoliths
