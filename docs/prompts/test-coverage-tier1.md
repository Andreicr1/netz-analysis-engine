# Test Coverage Expansion — Tier 1: Core Business Logic

## Context

You are working on `netz-analysis-engine`, a multi-tenant investment analysis platform. The backend has 2069 tests at 14% coverage. Your job is to write tests for **Tier 1 — Core Business Logic** to bring coverage from 14% to ~22%.

Read `CLAUDE.md` at the repo root for full architecture context.
Read `docs/plans/2026-03-23-test-coverage-expansion-plan.md` for the full plan.

## Your Task

Write unit tests for the 11 files listed below. Work through them **one file at a time**, in order. For each file:

1. **Read the source file** completely to understand all functions, classes, and decision branches
2. **Read any existing tests** for that module (if they exist) to avoid duplicating coverage
3. **Write a test file** at `backend/tests/test_{module_name}.py` (or add to existing)
4. **Run the tests** with `make test ARGS="-k {test_file} -v"` to confirm all pass
5. **Check coverage** with `python -m pytest backend/tests/test_{name}.py --cov=backend/{source_path} --cov-report=term-missing --tb=short` — aim for >60% per file
6. **Move to the next file** only after all tests pass

## Files to Test (in order)

### 1. `backend/ai_engine/pipeline/storage_routing.py` (60 stmts, 26% → 80%+)
- Test `bronze_document_path()`, `silver_chunks_path()`, `silver_metadata_path()`, `gold_memo_path()`, `global_reference_path()`
- Test `_SAFE_PATH_SEGMENT_RE` validation rejects path traversal (`../`, spaces, special chars)
- Test with various organization_id + vertical combinations
- Test edge cases: empty strings, None values, UUID formats

### 2. `backend/ai_engine/pipeline/validation.py` (76 stmts, 9% → 70%+)
- Test each validation gate function with passing and failing payloads
- Test gate chaining behavior
- Test edge cases: missing fields, wrong types, empty content

### 3. `backend/ai_engine/governance/authority_resolver.py` (86 stmts, 16% → 60%+)
- Test permission resolution for each role type
- Test `CLIENT_VISIBLE_TYPES` allowlist enforcement
- Test fallback behavior when config is missing

### 4. `backend/ai_engine/governance/policy_loader.py` (190 stmts, 0% → 50%+)
- Mock `ConfigService.get()` calls
- Test policy resolution chain: org-specific → vertical default → global default
- Test governance policy types and their structures
- Test error handling for missing/malformed policies

### 5. `backend/ai_engine/classification/hybrid_classifier.py` (143 stmts, 0% → 60%+)
- Test Layer 1: filename + keyword rules with various document names
- Test Layer 2: TF-IDF + cosine similarity with sample text
- Test Layer 3: LLM fallback (mock the LLM call, test prompt assembly + response parsing)
- Test the cascade: L1 match → skip L2/L3, L1 miss → L2 match → skip L3
- Test classification confidence thresholds
- Test with ambiguous documents that fall through to each layer

### 6. `backend/ai_engine/extraction/semantic_chunker.py` (234 stmts, 0% → 50%+)
- Test chunking with various text lengths (short, medium, long)
- Test chunk overlap behavior
- Test metadata preservation in chunks
- Test with edge cases: empty text, single sentence, all whitespace
- Test chunk size limits and boundary conditions

### 7. `backend/ai_engine/pipeline/unified_pipeline.py` (378 stmts, 7% → 40%+)
- Mock each stage (pre-filter, OCR, classify, governance, chunk, extract, embed, store, index)
- Test pipeline continues on non-critical failures (storage write fails → warning, continues)
- Test pipeline halts on critical gate failures
- Test dual-write ordering: StorageClient before pgvector
- Test stage skip logic based on document properties

### 8. `backend/vertical_engines/credit/pipeline/screening.py` (117 stmts, 7% → 60%+)
- Test screening filters with sample deal data matching/not matching criteria
- Test filter composition (AND/OR logic)
- Test with edge case deal data (missing fields, zero values)

### 9. `backend/vertical_engines/credit/pipeline/intelligence.py` (192 stmts, 9% → 50%+)
- Test scoring functions with fixture deal data
- Test ranking logic with multiple deals
- Test intelligence signal extraction
- Mock any LLM calls, test prompt assembly

### 10. `backend/vertical_engines/wealth/screener/layer_evaluator.py` (100 stmts, 0% → 60%+)
- Test eliminatory layer (hard disqualification)
- Test mandate fit layer (constraint matching)
- Test quant layer (metric thresholds)
- Test the 3-layer cascade: fail in L1 → skip L2+L3
- Use synthetic fund data fixtures

### 11. `backend/vertical_engines/wealth/screener/quant_metrics.py` (98 stmts, 0% → 60%+)
- Test metric computation with synthetic NAV time series
- Test Sharpe, Sortino, max drawdown, volatility calculations
- Test with edge cases: flat series, single data point, negative returns only
- Test NaN/None handling in input data

## Rules

- **Only mock I/O boundaries**: DB sessions, HTTP clients, LLM calls, filesystem. Never mock the business logic you're testing.
- **Use `@pytest.fixture`** for reusable test data. Prefer frozen dataclasses for type safety.
- **Realistic fixtures**: use data shapes that match production (UUIDs, ISO dates, proper numeric ranges).
- **Test file naming**: `backend/tests/test_{module_name}.py`. If a file already exists, add new test classes to it.
- **No `# type: ignore`** or `# noqa` in test code.
- **All tests must pass offline** — no live DB, no live API, no network calls.
- **Run `make lint` after writing each test file** to ensure ruff compliance.
- **DO NOT modify source files** — only write/edit test files. If you find a bug, document it as a skipped test with `@pytest.mark.skip(reason="BUG: ...")`.
- **Commit after each file** with message pattern: `test({module}): add unit tests for {description} ({N} tests)`

## Verification

After completing all 11 files, run the full test suite to confirm nothing broke:

```bash
make test
```

Then check overall coverage delta:

```bash
python -m pytest backend/tests/ --cov=backend --cov-report=term --tb=no -q 2>&1 | tail -5
```

Expected: ~150 new tests, overall coverage 14% → 22%+, zero regressions.
