# Test Coverage Expansion Plan

**Date:** 2026-03-23
**Current state:** 2069 tests, 14% coverage, 2067 passing
**Target:** 40%+ coverage across critical business logic

## Priority Tiers

### Tier 1 — Core Business Logic (Week 1)
Highest risk, pure logic, no external dependencies. Mock-friendly.

| File | Stmts | Coverage | Test Strategy |
|------|-------|----------|---------------|
| `ai_engine/classification/hybrid_classifier.py` | 143 | 0% | Unit test each layer (rules → cosine → LLM fallback) with fixture docs |
| `ai_engine/extraction/semantic_chunker.py` | 234 | 0% | Test chunking strategies with sample text, boundary conditions |
| `ai_engine/pipeline/unified_pipeline.py` | 378 | 7% | Test each stage gate independently with mocked I/O |
| `ai_engine/pipeline/validation.py` | 76 | 9% | Test validation gates with edge-case payloads |
| `ai_engine/pipeline/storage_routing.py` | 60 | 26% | Test path generation for all route types |
| `ai_engine/governance/policy_loader.py` | 190 | 0% | Test policy resolution, fallback chains |
| `ai_engine/governance/authority_resolver.py` | 86 | 16% | Test permission checks with various roles |
| `vertical_engines/credit/pipeline/screening.py` | 117 | 7% | Test screening filters with sample deal data |
| `vertical_engines/credit/pipeline/intelligence.py` | 192 | 9% | Test scoring/ranking logic with fixtures |
| `vertical_engines/wealth/screener/layer_evaluator.py` | 100 | 0% | Test 3-layer screening (eliminatory → mandate → quant) |
| `vertical_engines/wealth/screener/quant_metrics.py` | 98 | 0% | Test metric computation with synthetic NAV series |

**Estimated tests:** ~150 new tests
**Expected coverage lift:** 14% → 22%

### Tier 2 — Vertical Engines (Week 2)
Domain-specific analysis logic. Mock LLM calls, test data transformations.

| File | Stmts | Coverage | Test Strategy |
|------|-------|----------|---------------|
| `vertical_engines/credit/deep_review/service.py` | 790 | 3% | Test evidence assembly, scoring, decision paths (mock LLM) |
| `vertical_engines/credit/deep_review/confidence.py` | 202 | 9% | Test confidence scoring formula with edge cases |
| `vertical_engines/credit/deep_review/corpus.py` | 153 | 8% | Test corpus building/filtering |
| `vertical_engines/credit/deep_review/decision.py` | 102 | 5% | Test decision logic (approve/decline/escalate) |
| `vertical_engines/credit/memo/service.py` | 248 | 0% | Test memo generation flow (mock LLM) |
| `vertical_engines/credit/memo/chapters.py` | 318 | 0% | Test chapter rendering with fixtures |
| `vertical_engines/credit/memo/tone.py` | 103 | 0% | Test tone normalization transforms |
| `vertical_engines/credit/market_data/snapshot.py` | 134 | 0% | Test snapshot assembly from DB fixtures |
| `vertical_engines/credit/quant/service.py` | 167 | 7% | Test quant analysis pipeline |
| `vertical_engines/wealth/dd_report/dd_report_engine.py` | 107 | 0% | Test DD report orchestration (mock LLM) |
| `vertical_engines/wealth/correlation/service.py` | 18 | 0% | Test correlation computation |
| `vertical_engines/wealth/attribution/service.py` | 74 | 0% | Test Brinson-Fachler attribution |

**Estimated tests:** ~200 new tests
**Expected coverage lift:** 22% → 30%

### Tier 3 — Workers & Data Providers (Week 3)
Background jobs and external API integrations. Mock HTTP + DB.

| File | Stmts | Coverage | Test Strategy |
|------|-------|----------|---------------|
| `app/domains/wealth/workers/risk_calc.py` | 323 | 11% | Test CVaR, momentum, risk metric computation |
| `app/domains/wealth/workers/portfolio_eval.py` | 152 | 15% | Test breach detection, cascade logic |
| `app/domains/wealth/workers/benchmark_ingest.py` | 136 | 0% | Test dedup, NAV normalization |
| `app/domains/wealth/workers/treasury_ingestion.py` | 143 | 0% | Test parsing, upsert logic (mock HTTP) |
| `app/domains/wealth/workers/ofr_ingestion.py` | 137 | 0% | Test OFR data parsing |
| `data_providers/esma/firds_service.py` | 126 | 0% | Test FIRDS XML parsing, ISIN extraction |
| `data_providers/esma/register_service.py` | 92 | 0% | Test manager/fund parsing from Solr docs |
| `data_providers/sec/adv_service.py` | 424 | 0% | Test ADV parsing, brochure extraction |
| `data_providers/sec/thirteenf_service.py` | 319 | 0% | Test 13F XML parsing, diff computation |
| `ai_engine/ingestion/pipeline_ingest_runner.py` | 373 | 0% | Test pipeline orchestration (mock stages) |

**Estimated tests:** ~180 new tests
**Expected coverage lift:** 30% → 38%

### Tier 4 — Routes & Integration (Week 4)
API contract tests. TestClient + mocked DB/services.

| Area | Files | Current Coverage |
|------|-------|-----------------|
| Credit routes | 15 files | 15-30% |
| Wealth routes | 18 files | 14-25% |
| Admin routes | 10 files | 18-35% |

**Strategy:** Test request/response contracts, auth enforcement, error handling.
**Estimated tests:** ~120 new tests
**Expected coverage lift:** 38% → 42%+

## Execution Rules

1. **No mocking business logic** — only mock I/O boundaries (DB, HTTP, LLM, filesystem)
2. **Frozen dataclass fixtures** — use `@pytest.fixture` with realistic data shapes
3. **One test file per source file** — `test_{module_name}.py` naming convention
4. **Test edge cases** — empty inputs, None values, boundary conditions
5. **No integration tests requiring live services** — all tests must pass offline
6. **Each PR ≤ 30 new tests** — reviewable chunks, not monolithic test dumps

## How to Execute

Each tier can be executed as a self-contained session:

```
Start with Tier 1. For each file in the table:
1. Read the source file to understand the logic
2. Identify pure functions and decision branches
3. Write tests covering happy path + edge cases
4. Run tests to confirm they pass
5. Check coverage delta with: pytest --cov=backend/{path} tests/test_{name}.py
```
