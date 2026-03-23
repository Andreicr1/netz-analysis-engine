---
title: "Dead Code Audit — Post-Pipeline-Refactor ai_engine Cleanup (-851 LOC)"
category: architecture-patterns
component: "backend/ai_engine/"
subcomponents:
  - "extraction/"
  - "governance/"
  - "prompts/"
  - "validation/"
problem_type: "architecture-patterns"
severity: "medium"
tags:
  - dead-code
  - post-refactor-cleanup
  - sync-async-mismatch
  - session-injection
  - api-surface-reduction
  - modularization
discovered: "2026-03-16"
resolved: "2026-03-16"
related_prs: ["#20", "#21", "#22"]
---

# Dead Code Audit — Post-Pipeline-Refactor ai_engine Cleanup

## Problem Statement

After the pipeline LLM-deterministic alignment refactor (PRs #20-#22) and Wave 1-2 credit modularization (12 PRs), `backend/ai_engine/` accumulated ~851 LOC of dead code across 10+ files: entire scaffold files with no callers, sync wrapper functions superseded by async equivalents, unused helper functions whose callers had been deleted, and internal functions with public visibility.

A multi-agent review pass after the initial audit discovered additional dead code AND a critical latent bug: `deep_review_validation_runner.py:118` referenced `async_session_factory` (never imported) and used it with a synchronous `with` context manager — an async/sync mismatch that would crash at runtime when the validation runner processed deals.

## Root Cause

Five distinct failure modes contributed:

1. **Deferred sync wrapper deletion** — async replacements were merged in PRs #20-#22, but sync wrappers were left "for later cleanup"
2. **Orphaned scaffolding** — `evidence_throttle.py` and `local_reranker.py` were created as forward-looking modules that were never integrated
3. **Lazy import hiding NameError** — `async_session_factory` was used but never imported; the error was hidden because it was inside a function body and caught by broad `except Exception`
4. **Missing `_` prefix on internal functions** — 16 functions in `entity_bootstrap.py` and `semantic_chunker.py` were only called internally but had public visibility
5. **Superseded prompt system** — `prompts/loader.py` (str.format) was fully replaced by `prompts/registry.py` (Jinja2 SandboxedEnvironment) but never deleted

## Solution

### Methodology

5 parallel Explore agents audited all `ai_engine/` sub-packages. For each `.py` file, grepped all callers across `backend/` and `worker_app/`. Classified every exported function as Active / Test-only / Dead / Internal-only.

6 review agents (kieran-python-reviewer, architecture-strategist, pattern-recognition-specialist, security-sentinel, code-simplicity-reviewer, learnings-researcher) then reviewed the changes and caught additional dead code + the P1 session bug.

### Files Deleted (0 production callers)

| File | LOC | Why dead |
|---|---|---|
| `governance/evidence_throttle.py` | 58 | Scaffolding for evidence limiting — never integrated |
| `prompts/loader.py` | 86 | Superseded by `registry.py` Jinja2 system (21 callers) |
| `extraction/local_reranker.py` | 148 | Cross-encoder reranker — integration never wired |

### Dead Functions Deleted Within Active Files

| File | Function(s) | LOC | Why dead |
|---|---|---|---|
| `validation/vector_integrity_guard.py` | 6 guard functions (B1-B5 + runner) | ~248 | Never wired into app startup. Constants kept. |
| `extraction/document_intelligence.py` | 5 sync wrappers + batch + `doc_type_matches_affinity` | ~170 | Async replacements exist; affinity matcher had 0 callers |
| `extraction/mistral_ocr.py` | `extract_pdf_with_mistral` | ~10 | Sync wrapper; all callers use async version |
| `extraction/text_extraction.py` | `extract_text_from_bytes` + `extract_text_from_blob` | ~49 | Sync versions; all callers use async versions |
| `extraction/semantic_chunker.py` | `print_chunk_summary` | ~26 | Debug utility with 0 callers |

### Bug Fix (P1): async/sync Session Mismatch

```python
# BEFORE (broken — would crash at runtime):
# Line 118: async_session_factory was never imported
SessionLocal = async_session_factory  # NameError
for deal_id in selected_ids:
    with SessionLocal() as session:   # sync 'with' on AsyncSession — TypeError
        result = _benchmark_single_deal(session, ...)
        session.commit()              # sync commit on AsyncSession — coroutine error

# AFTER (session injection pattern):
for deal_id in selected_ids:
    result = _benchmark_single_deal(
        db,           # caller-provided Session
        fund_id=fund_id,
        deal_id=deal_id,
        actor_id=actor_id,
    )
    deal_results.append(result)
```

### API Surface Reduction (16 functions privatized)

`entity_bootstrap.py` — 11 functions prefixed with `_`:
`filename_vehicle_hint`, `extract_entities_regex`, `extract_fund_metadata`, `filter_lines_by_embedding`, `extract_entities_gpt`, `validate_vehicle_type`, `ocr_pdf_bootstrap`, `merge_discoveries`, `load_seed`, `write_enriched`, `cosine_similarity`

`semantic_chunker.py` — 5 functions prefixed with `_`:
`get_chunk_sizes`, `classify_section_type`, `has_financial_figures`, `parse_markdown_blocks`, `chunk_markdown`

### Results

| Metric | Value |
|---|---|
| Lines removed | 851 |
| Files deleted | 3 |
| Dead functions removed | ~15 |
| Functions privatized | 16 |
| Bug fixes | 1 (P1 session injection) |
| Tests passing | 407/407 |
| Import-linter contracts | 5/5 kept |

## Prevention Strategies

### 1. Same-PR Deletion Rule for Async Migration

When replacing a sync function with an async equivalent, delete the sync version in the same PR if it has zero remaining callers. If callers remain, annotate:
```python
# TODO(delete-after): PR-{N} — last caller migrated there
def sync_wrapper(...):
    return asyncio.run(async_version(...))
```

### 2. Scaffolding Expiry Dates

Every new file with zero importers at merge time must include:
```python
# SCAFFOLDING: integrate by 2026-04-01 or delete. Tracking: #069
```
Periodic sweep: `rg "# SCAFFOLDING:" --glob "*.py" -n`

### 3. Lazy Imports Must Be Smoke-Tested

If a function uses a lazy import, the test suite must call that function at least once — even with mock args that cause an early return. This catches `NameError` and `ImportError` that hide behind function bodies.

### 4. Internal Functions Use `_` Prefix

Any function called only within its own module must use `_` prefix. Enforced at code review time. Reduces false public API surface.

### 5. Multi-Agent Review for Audits

For PRs touching 10+ files or 500+ LOC of deletions, run multi-perspective review:
- Dead code lens (zero-caller grep)
- Error handling lens (broad except handlers)
- Import integrity lens (lazy imports resolve)

The initial audit missed `local_reranker.py`, `doc_type_matches_affinity()`, dead sync wrappers in `text_extraction.py`, and the session bug — all caught by review agents.

## Related Documentation

- **Prior dead code audit:** `docs/solutions/architecture-patterns/dead-code-audit-ai-engine-legacy-cleanup-20260315.md` — deleted 6 modules (-2,105 LOC). Found phantom imports hidden by lazy imports.
- **Pipeline refactor (created the dead code):** `docs/solutions/architecture-patterns/unified-pipeline-ingestion-path-consolidation-Phase2-20260315.md` — consolidated 4 ingestion paths into unified_pipeline.
- **Wave 2 modularization:** `docs/solutions/architecture-patterns/wave2-deep-review-modularization-MonolithToDAGPackage-20260315.md` — decomposed 5430-LOC monolith with sync/async duplication.
- **Prompt registry migration:** `docs/solutions/architecture-patterns/prompt-registry-distributed-search-paths-PromptRelocation-20260315.md` — relocated 31 templates, left dead `loader.py`.
