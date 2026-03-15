---
title: "refactor: Credit Vertical Modular Alignment — Wave 1"
type: refactor
status: active
date: 2026-03-15
origin: docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md
---

# refactor: Credit Vertical Modular Alignment — Wave 1

## Enhancement Summary

**Deepened on:** 2026-03-15
**Review agents used:** architecture-strategist, code-simplicity-reviewer, pattern-recognition-specialist, performance-oracle, kieran-python-reviewer, security-sentinel, best-practices-researcher

### Key Improvements from Review

1. **Tiered PEP 562 adoption** — Only 3 engines (kyc, market_data, memo) need lazy imports; the other 8 use standard `__init__.py` re-exports. Eliminates ~350 lines of unnecessary `__getattr__` boilerplate.
2. **Simplified small engines** — sponsor/, deal_conversion/, underwriting/, domain_ai/ collapsed to 2-3 files each. Eliminates 10+ unnecessary files.
3. **retrieval/ consolidated** — 10 modules → 6 (merged provenance→evidence, reranker→corpus). Minimum module size ~150 LOC (matching edgar floor).
4. **quant/ consolidated** — 12 modules → 8 (merged migration→parser, 3 single-function modules→profile.py). Preserves existing golden tests.
5. **Never-raises is conditional** — Applied to orchestration engines (critic, sponsor, market_data, pipeline, portfolio, memo). NOT applied to transactional engines (deal_conversion — raises ValueError on validation gates) or pure computation (quant, underwriting).
6. **Critical missing exports fixed** — memo/ `__init__.py` must export `generate_chapter`, `select_chapter_chunks`. quant/ must export `CVStrategy`. Pattern-recognition caught these before they became runtime breaks.
7. **10 unmapped test callers added** — `test_phase_a_integration.py` has 10 import sites for quant/ absorbed files not in original plan.
8. **Dataclass conventions** — `@dataclass(frozen=True, slots=True)` for all return-type models. Custom `_to_dict()` at service boundary (not blanket `asdict()`).
9. **Security finding** — Never-raises must include `status: 'NOT_ASSESSED'` field so callers distinguish clean results from failed analyses. Critical for kyc/ and market_data/.
10. **import-linter** — Add DAG enforcement to CI (`make architecture`). Locks the layer hierarchy post-refactor.

### Findings Requiring Human Decision

- **retrieval/ raises domain exceptions** (`EvidenceGapError`, `RetrievalScopeError`, `ProvenanceError`) that callers catch. Converting to never-raises changes control flow. See Phase 4 notes.
- **Premature dataclass formalization** — sponsor/ and deal_conversion/ currently use plain dicts. Creating typed models during a structural refactor is scope creep. Keep dicts now, formalize when callers need type safety.

## Overview

Modularize all 11 non-deep_review credit vertical engines from monolithic flat files into edgar-style packages. Each engine becomes a directory with `models.py` (leaf) → domain modules → `service.py` (orchestrator) → `__init__.py`. PEP 562 lazy imports applied only to engines with heavy dependencies (kyc, market_data, memo); lightweight engines use standard imports. Standardization: structlog, golden tests, and error contracts appropriate to each engine type.

**Scope:** PR #0 (import-linter setup) + 12 engine PRs, strictly serial. ~14,500 LOC restructured.

**Reference implementation:** `backend/vertical_engines/credit/edgar/` (see brainstorm: `docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md`)

## Problem Statement

31 monolithic `.py` files in `backend/vertical_engines/credit/` were moved as-is from the legacy Private Credit OS. Only `edgar/` follows the modular package pattern. The remaining engines have:
- Mixed concerns in single files (parsing + orchestration + constants)
- No explicit public API contracts (`__init__.py`, `__all__`)
- Inconsistent error handling (some raise, some return dicts, some swallow)
- No structlog (using stdlib `logging`)
- No golden tests for regression safety

## Proposed Solution

Apply the 8-pattern edgar architecture (see `docs/solutions/architecture-patterns/monolith-to-modular-package-with-library-migration.md`) to every credit engine, in a strict sequence of 11 PRs.

## Technical Approach

### Architecture

Every engine follows this DAG:

```
engine_name/
  __init__.py        # PEP 562 lazy imports + TYPE_CHECKING + __all__
  models.py          # dataclasses + enums + constants (LEAF — zero sibling imports)
  [domain_a].py      # imports only models.py
  [domain_b].py      # imports only models.py
  service.py         # orchestrator — imports all domain modules
```

### Conventions (from brainstorm + review agent refinements)

1. **No backward-compat shims** — all callers updated in same PR
2. **Error contract per engine type:**
   - **Never-raises** (orchestration engines called during deep review): critic, sponsor, kyc, market_data, pipeline, portfolio, memo, retrieval. Return `result['warnings']` list + `status: 'NOT_ASSESSED'` on failure. `exc_info=True` in structlog.
   - **Raises-on-failure** (transactional/validation engines): deal_conversion (ValueError on invalid state gates), underwriting (pure deterministic), quant (math errors should propagate). Document error contract in `__init__.py` docstring.
3. **Dict return at API boundary** — typed `@dataclass(frozen=True, slots=True)` internally. Custom `_to_dict()` helper at service boundary (not blanket `dataclasses.asdict()` — gives control over key names and nested handling). `asdict()` only for flat leaf dataclasses with 1:1 field mapping.
4. **PEP 562 lazy imports — conditional:**
   - **Use PEP 562** (`__getattr__` + `TYPE_CHECKING`): kyc (httpx), market_data (httpx), memo (openai), pipeline (openai/ai_engine)
   - **Use standard imports**: critic, sponsor, retrieval, quant, portfolio, deal_conversion, underwriting, domain_ai (stdlib + sqlalchemy only — already warm in `sys.modules`)
5. **Golden tests** — capture current outputs before restructuring, assert after. Use `rtol=1e-6` for numerics. Skip golden tests for trivial pure functions (<10 LOC, <4 branches) — standard unit tests suffice.
6. **Dataclass conventions** — `@dataclass(frozen=True, slots=True)` for return-type models that cross module boundaries. Mutable only for accumulator objects built incrementally within a single function. Do NOT formalize plain dicts into dataclasses during this refactor (scope creep) — keep existing return types, add typed models when callers need type safety.
7. **Scientific skills** — applied opportunistically per engine, scoped to the same PR only when improvement is small
8. **Domain module imports** — each imports `models.py` or lower-tier sibling modules within the same package. No domain module imports `service.py`. Cross-package imports are documented in the phase description. (This matches what edgar actually does — `entity_extraction.py` imports from `cik_resolver.py`.)

### Constraints

- **Strictly serial PRs.** `deep_review.py` is modified by every PR (import path updates). Parallel branches cause merge conflicts. Each PR merges before the next branch starts.
- **Wave 2 files are touched during Wave 1.** `deep_review.py`, `deep_review_prompts.py`, `deep_review_corpus.py` get import-path-only updates in Wave 1 PRs. This is necessary since there are no backward-compat shims.
- **`test_vertical_engines.py::EXPECTED_MODULES`** must be updated in every PR (lines 39-67).
- **`credit/prompts/` has 30 `.j2` files** (not empty as previously assumed). These stay in place during Wave 1. Wave 2 handles relocation.

### `domain_ai_engine.py` — Resolved as Standalone

SpecFlow analysis confirmed: `domain_ai_engine.py` is called by `ai_engine/ingestion/domain_ingest_orchestrator.py` (3 sites), NOT by deep_review. It dispatches to `pipeline_engine.generate_pipeline_intelligence`. Absorbing into `deep_review/` would create incorrect architectural dependency. **Decision: standalone `domain_ai/` package**, sequenced after `pipeline/` (depends on pipeline imports).

## System-Wide Impact

### Interaction Graph

Every Wave 1 engine is consumed by `deep_review.py` via lazy function-level imports. The import path change is the only modification to `deep_review.py` — no behavioral change.

External callers affected per PR:
- `ai_engine/__init__.py` — lazy imports of `run_pipeline_ingest`, `run_portfolio_ingest`
- `ai_engine/ingestion/pipeline_ingest_runner.py` — `discover_pipeline_deals`
- `ai_engine/ingestion/domain_ingest_orchestrator.py` — `run_deal_ai_analysis`
- `app/domains/credit/modules/ai/extraction.py` — `run_pipeline_ingest`
- `app/domains/credit/modules/ai/portfolio.py` — `run_portfolio_ingest`
- `app/domains/credit/modules/ai/memo_chapters.py` — `generate_memo_book`, retrieval governance

### Error Propagation

All engines adopt never-raises contract. `deep_review.py` currently wraps engine calls in `try/except`. After migration, these become no-op safety nets (engine never raises). Leave them in place during Wave 1 — cleanup in Wave 2.

### State Lifecycle Risks

Pure structural refactor. No schema changes, no new tables, no data flow changes. The only risk is import path breakage, mitigated by:
1. Golden tests run before AND after restructuring
2. `make check` (lint + typecheck + test) gate on every PR
3. `test_vertical_engines.py` structural test validates all modules are importable

### API Surface Parity

Each package's `__init__.py` exports exactly the symbols currently imported by external callers. No more, no less. The `__all__` for each package is derived from the caller grep in this plan.

## Implementation Phases

### Phase 1: critic/ (PR #1) ✅

**Source:** `ic_critic_engine.py` (766 LOC)

**Package structure:** (standard imports — no heavy deps)
```
critic/
  __init__.py        # exports: critique_intelligence, build_critic_packet, classify_instrument_type, CriticVerdict, INSTRUMENT_TYPE_PROFILES
  models.py          # CriticVerdict dataclass (frozen=True, slots=True), INSTRUMENT_TYPE_PROFILES dict
  classifier.py      # classify_instrument_type (was _classify_instrument_type — now public API)
  macro_checks.py    # _run_macro_consistency_checks — rule-based macro flags
  prompt_builder.py  # _build_critic_prompt, _build_critic_input
  parser.py          # _parse_critic_response, _clamp
  service.py         # critique_intelligence, build_critic_packet
```

**Callers to update:**
- `deep_review.py:365` — `from vertical_engines.credit.ic_critic_engine import critique_intelligence` → `from vertical_engines.credit.critic import critique_intelligence`
- `deep_review.py:505` — `_classify_instrument_type` → `classify_instrument_type` (renamed to public)
- `deep_review.py:1647` — update all 3 imports to `critic` package
- `deep_review_prompts.py:28` — `from vertical_engines.credit.ic_critic_engine import INSTRUMENT_TYPE_PROFILES` → `from vertical_engines.credit.critic import INSTRUMENT_TYPE_PROFILES`
- `test_vertical_engines.py:41` — update `EXPECTED_MODULES`
- Delete: `ic_critic_engine.py`

**Scientific skills:** hypothesis-generation — evaluate for structured devil's advocate hypothesis framework.

**Golden tests:** Capture `critique_intelligence()` output for 2-3 instrument types.

---

### Phase 2: sponsor/ (PR #2) ✅

**Source:** `sponsor_engine.py` (390 LOC)

**Package structure:** (standard imports — stdlib only)
```
sponsor/
  __init__.py        # exports: analyze_sponsor, extract_key_persons_from_analysis
  person_extraction.py  # extract_key_persons_from_analysis, _looks_like_person_name, _extract_names_from_text
  service.py         # analyze_sponsor (keeps existing dict returns — no premature dataclass formalization)
```

> **No models.py** — sponsor currently returns plain dicts and has no typed models. Adding dataclasses during a structural refactor is scope creep. Formalize when callers need type safety.

**Callers to update:**
- `deep_review.py:373,1658` — `from vertical_engines.credit.sponsor_engine import analyze_sponsor`
- `kyc_pipeline_screening.py:51` — `from vertical_engines.credit.sponsor_engine import extract_key_persons_from_analysis`
- `test_vertical_engines.py:44` — update `EXPECTED_MODULES`
- Delete: `sponsor_engine.py`

**Golden tests:** Capture `extract_key_persons_from_analysis()` output for sample analysis dict.

---

### Phase 3: kyc/ (PR #3) ✅

**Source:** `kyc_pipeline_screening.py` (621 LOC) + `kyc_models.py` (30 LOC) + `kyc_client.py` (70 LOC)

**Package structure:**
```
kyc/
  __init__.py        # exports: run_kyc_screenings, build_kyc_appendix, persist_kyc_screenings_to_db
  models.py          # KYCScreening, KYCScreeningMatch (from kyc_models.py)
  client.py          # KYCSpiderClient (from kyc_client.py)
  entity_extraction.py  # _extract_persons_from_analysis, _extract_orgs_from_analysis
  screening.py       # _run_person_screening, _run_org_screening
  appendix.py        # build_kyc_appendix
  persistence.py     # persist_kyc_screenings_to_db
  service.py         # run_kyc_screenings
```

**Callers to update:**
- `deep_review.py:680,1939,2021` — kyc imports
- `test_vertical_engines.py:62-64` — update 3 entries to 1 package
- **Cross-package:** `kyc/entity_extraction.py` imports from `sponsor.person_extraction` (was `sponsor_engine`). Sponsor must be package first (Phase 2 ✓).

**Golden tests:** Capture `build_kyc_appendix()` output format.

---

### Phase 4: retrieval/ (PR #4) ✅

**Source:** `retrieval_governance.py` (1326 LOC)

**Package structure:** (standard imports — stdlib only)
```
retrieval/
  __init__.py        # exports: gather_chapter_evidence, build_ic_corpus, enforce_evidence_saturation, build_retrieval_audit, retrieve_market_benchmarks, build_chapter_query_map, ic_coverage_rerank, validate_provenance
  models.py          # EvidenceGapError, RetrievalScopeError, ProvenanceError, ChapterEvidenceThreshold, DEPTH_FREE, LAMBDA, CHAPTER_DOC_TYPE_FILTERS
  query_map.py       # build_chapter_query_map (~190 LOC)
  evidence.py        # gather_chapter_evidence + validate_provenance (~185 LOC) — provenance is a precondition of evidence gathering
  corpus.py          # build_ic_corpus + ic_coverage_rerank (~195 LOC) — reranking is a step in corpus assembly
  saturation.py      # enforce_evidence_saturation + build_retrieval_audit (~160 LOC) — audit reports on saturation gaps
  benchmarks.py      # retrieve_market_benchmarks (~120 LOC)
```

> **No service.py** — retrieval functions are independently callable, not orchestrated. `__init__.py` exports directly. `build_ic_corpus` orchestrates `gather_chapter_evidence` + `enforce_evidence_saturation` internally.

> **BEHAVIORAL CHANGE — never-raises migration:** Current code raises `EvidenceGapError`, `RetrievalScopeError`, `ProvenanceError`. Callers that catch these must be updated:
> - `deep_review_corpus.py` catches `EvidenceGapError` — must switch to checking `result['warnings']`
> - `app/domains/credit/modules/ai/memo_chapters.py` catches retrieval exceptions — same treatment
> - Keep exception classes in `models.py` for backward compat during Wave 1; deprecate in Wave 2

**Callers to update:**
- `deep_review.py:473,1741` — `retrieve_market_benchmarks`
- `deep_review_corpus.py:342` — `from vertical_engines.credit.retrieval_governance import ...`
- `app/domains/credit/modules/ai/memo_chapters.py:518-521` — retrieval governance imports (`build_ic_corpus`, `gather_chapter_evidence`)
- `test_vertical_engines.py:50` — update `EXPECTED_MODULES`
- Delete: `retrieval_governance.py`

**Golden tests:** Capture `build_chapter_query_map()` output for sample deal name.

---

### Phase 5: pipeline/ (PR #5) ✅

**Source:** `pipeline_engine.py` (1030 LOC) + `pipeline_intelligence.py` (385 LOC)

**Package structure:**
```
pipeline/
  __init__.py        # exports: generate_pipeline_intelligence, run_pipeline_ingest, discover_pipeline_deals, aggregate_deal_documents, run_pipeline_monitoring, compute_completeness_score
  models.py          # STATUS_* constants, PIPELINE_CONTAINER, RISK_ORDER, RISK_BAND_ORDER, DOC_TYPE_MAP, _REQUIRED_DD_DOCUMENTS
  screening.py       # _retrieve_deal_context, _compute_missing_documents, compute_completeness_score
  validation.py      # _validate_output, _validate_memo
  persistence.py     # _set_intelligence_status, _write_research_output, _write_derived_fields
  discovery.py       # discover_pipeline_deals, aggregate_deal_documents (from pipeline_intelligence.py)
  monitoring.py      # run_pipeline_monitoring (from pipeline_intelligence.py)
  intelligence.py    # generate_pipeline_intelligence (was pipeline_engine.py main fn)
  service.py         # run_pipeline_ingest (from pipeline_intelligence.py — orchestrator)
```

**Callers to update:**
- `ai_engine/__init__.py:26` — `from vertical_engines.credit.pipeline_intelligence import run_pipeline_ingest`
- `ai_engine/ingestion/pipeline_ingest_runner.py:200,416` — `discover_pipeline_deals`
- `domain_ai_engine.py:128` — `from vertical_engines.credit.pipeline_engine import generate_pipeline_intelligence`
- `app/domains/credit/modules/ai/extraction.py:15` — `run_pipeline_ingest`
- `deep_review.py` — no direct pipeline imports (uses domain_ai_engine)
- `test_vertical_engines.py:47-48` — update 2 entries to 1 package

**Golden tests:** Capture `compute_completeness_score()` output.

---

### Phase 6: quant/ (PR #6) ✅

**Source:** `ic_quant_engine.py` (~950 LOC) + `credit_scenarios.py` (130 LOC) + `credit_sensitivity.py` (110 LOC) + `credit_backtest.py` (200 LOC)

**Package structure:** (standard imports — stdlib only; numpy in backtest only)
```
quant/
  __init__.py        # exports: compute_quant_profile, QuantProfile, CVStrategy, build_deterministic_scenarios, build_sensitivity_2d, build_sensitivity_3d_summary, BacktestInput, CreditBacktestResult, backtest_pd_model
  models.py          # QuantProfile (keep existing manual to_dict()), BacktestInput, CreditBacktestResult, CVStrategy (frozen=True, slots=True)
  parser.py          # all _v2_* helpers + _migrate_v1_to_v2 + _ensure_v2 (merged: parser + migration)
  profile.py         # compute_maturity_years, compute_rate_decomposition, _extract_liquidity_hooks, _compute_risk_adjusted_return_v2 (merged: 4 single-function modules → 1)
  scenarios.py       # build_deterministic_scenarios (was credit_scenarios.py)
  sensitivity.py     # build_sensitivity_2d, build_sensitivity_3d_summary (was credit_sensitivity.py)
  backtest.py        # backtest_pd_model (was credit_backtest.py)
  service.py         # compute_quant_profile
```

> **Raises-on-failure** — quant functions are pure computation. Math errors (division by zero, invalid inputs) should propagate, not be silently folded into warnings.

**Callers to update:**
- `deep_review.py:366,1651` — `compute_quant_profile`
- `test_ic_quant_golden.py:14` — imports from `ic_quant_engine`
- `test_phase_a_integration.py:43,71` — imports from `ic_quant_engine`
- `test_phase_a_integration.py:22,31` — imports from `credit_sensitivity` (absorbed)
- `test_phase_a_integration.py:59` — imports from `credit_scenarios` (absorbed)
- `test_phase_a_integration.py:255,278,292,304,318,330,342` — imports from `credit_backtest` (7 call sites: `BacktestInput`, `CVStrategy`, `backtest_pd_model`)
- `test_vertical_engines.py:42` — update `EXPECTED_MODULES`
- Delete old flat files: `ic_quant_engine.py`, `credit_scenarios.py`, `credit_sensitivity.py`, `credit_backtest.py`

**Golden tests:** Already exist (`test_ic_quant_golden.py`). Update import paths only.

---

### Phase 7: market_data/ (PR #7) ✅

**Source:** `market_data_engine.py` (1031 LOC)

**Package structure:**
```
market_data/
  __init__.py        # exports: get_macro_snapshot, compute_macro_stress_severity, compute_macro_stress_flag, resolve_metro_key, fetch_regional_case_shiller
  models.py          # FRED_SERIES_REGISTRY, CASE_SHILLER_METRO_MAP, GEOGRAPHY_TO_METRO
  fred_client.py     # _fetch_fred_series, _fetch_latest_strict, _latest_value, _latest_two_values
  computed_fields.py # _compute_yield_curve_2s10s, _compute_cpi_yoy, _compute_gdp_growth
  regional.py        # resolve_metro_key, fetch_regional_case_shiller
  stress.py          # compute_macro_stress_severity, compute_macro_stress_flag
  snapshot.py        # _build_macro_snapshot_legacy, _build_macro_snapshot_expanded, _build_macro_snapshot
  service.py         # get_macro_snapshot
```

**CRITICAL:** Imports from quant_engine must use the package paths established in Phase 6:
- `from quant_engine.fred_service import apply_transform` (unchanged — quant_engine/ is a different package)
- `from quant_engine.stress_severity_service import compute_stress_severity` (unchanged)

**Callers to update:**
- `deep_review.py:452,1730,1799` — `get_macro_snapshot`, `compute_macro_stress_severity`
- `test_market_data_golden.py:10` — update import
- `test_vertical_engines.py:43` — update `EXPECTED_MODULES`

**Scientific skills:** fred-economic-data — evaluate for direct FRED API patterns. polars — evaluate for faster DataFrame ops in snapshot building.

**Golden tests:** Already exist (`test_market_data_golden.py`). Update import paths only.

---

### Phase 8: portfolio/ (PR #8) ✅

**Source:** `portfolio_intelligence.py` (797 LOC)

**Package structure:**
```
portfolio/
  __init__.py        # exports: run_portfolio_ingest, discover_active_investments, extract_portfolio_metrics, detect_performance_drift, build_covenant_surveillance, reclassify_investment_risk, build_board_monitoring_briefs
  models.py          # PORTFOLIO_CONTAINER constant, type aliases
  discovery.py       # discover_active_investments
  metrics.py         # extract_portfolio_metrics
  drift.py           # detect_performance_drift
  covenants.py       # build_covenant_surveillance
  risk.py            # reclassify_investment_risk
  briefs.py          # build_board_monitoring_briefs
  service.py         # run_portfolio_ingest (orchestrator)
```

**Callers to update:**
- `ai_engine/__init__.py:32` — `from vertical_engines.credit.portfolio_intelligence import run_portfolio_ingest`
- `app/domains/credit/modules/ai/portfolio.py:55` — `run_portfolio_ingest`
- `test_vertical_engines.py:49` — update `EXPECTED_MODULES`

**Scientific skills:** aeon — evaluate for time series anomaly detection in `detect_performance_drift`.

**Golden tests:** Capture `detect_performance_drift()` output for sample data.

---

### Phase 9: deal_conversion/ (PR #9) ✅

**Source:** `deal_conversion_engine.py` (316 LOC)

**Package structure:** (standard imports — stdlib only)
```
deal_conversion/
  __init__.py        # exports: convert_pipeline_to_portfolio, ConversionResult
  models.py          # ConversionResult dataclass (frozen=True, slots=True)
  normalization.py   # _normalize_amount, _title_case_strategy, _derive_deal_type (was "helpers.py" — descriptive name per edgar convention)
  service.py         # convert_pipeline_to_portfolio
```

> **Raises-on-failure** — `convert_pipeline_to_portfolio` raises `ValueError` on validation gates ("Deal already converted", "Intelligence status must be READY"). These are domain assertions, not warnings.
> **Possible dead code** — no external callers found. Flag for verification during implementation.

**Callers to update:**
- `test_vertical_engines.py:66` — update `EXPECTED_MODULES`
- Delete: `deal_conversion_engine.py`

**Golden tests:** Standard unit tests for `ConversionResult` and validation gates. No golden test needed for a 5-line dataclass.

---

### Phase 10: underwriting/ (PR #10)

**Source:** `underwriting_artifact.py` (249 LOC)

**Package structure:** (standard imports — 249 LOC, minimal split)
```
underwriting/
  __init__.py        # exports: persist_underwriting_artifact, get_active_artifact, get_artifact_history, derive_risk_band, confidence_to_level, compute_evidence_pack_hash
  derivation.py      # derive_risk_band, confidence_to_level, compute_evidence_pack_hash (pure functions)
  persistence.py     # persist_underwriting_artifact, get_active_artifact, get_artifact_history (DB access)
```

> **No models.py** — do NOT formalize string returns ("HIGH"/"MEDIUM"/"LOW") into enums during this refactor. Callers expect strings. Enum migration is a separate behavioral change.
> **No service.py** — there is no orchestration logic. `__init__.py` re-exports directly.
> **Raises-on-failure** — pure deterministic functions. Standard exceptions for truly exceptional cases.

**Callers to update:**
- `deep_review.py:1341,1375,2537,2540` — underwriting imports
- `test_vertical_engines.py:52` — update `EXPECTED_MODULES`
- Delete: `underwriting_artifact.py`

**Golden tests:** Standard unit tests for `derive_risk_band()` and `confidence_to_level()` boundary values. These are <20 LOC pure functions — golden tests are overkill.

---

### Phase 11: domain_ai/ (PR #11) — NEW (was TBD)

**Source:** `domain_ai_engine.py` (270 LOC)

**Package structure:** (standard imports — 270 LOC dispatcher)
```
domain_ai/
  __init__.py        # exports: run_deal_ai_analysis
  engine.py          # everything from domain_ai_engine.py (270 LOC doesn't justify further splitting)
```

> **No models.py** — no dedicated constants or type aliases worth extracting. `_ALLOWED_JSONB_TARGETS` is used only by `_write_jsonb_column`, a private function.
> **Cross-layer imports:** `engine.py` imports from `ai_engine/` and `app/domains/credit/`. These are inherited dependencies — document for Wave 2 cleanup.

**CRITICAL:** Imports from `pipeline_engine.generate_pipeline_intelligence` must use the package path established in Phase 5: `from vertical_engines.credit.pipeline import generate_pipeline_intelligence`.

**Callers to update:**
- `ai_engine/ingestion/domain_ingest_orchestrator.py:355,763,815` — `run_deal_ai_analysis`
- `test_vertical_engines.py:59` — update `EXPECTED_MODULES`
- Delete: `domain_ai_engine.py`

---

### Phase 12: memo/ (PR #12)

**Source:** `memo_book_generator.py` (900 LOC) + `memo_chapter_engine.py` (773 LOC) + `memo_chapter_prompts.py` (1550 LOC) + `memo_evidence_pack.py` (364 LOC) + `tone_normalizer.py` (315 LOC, absorbed) + `batch_client.py` (301 LOC, absorbed)

**Package structure (per brainstorm DAG — mandatory):**
```
memo/
  __init__.py        # exports: generate_memo_book, async_generate_memo_book, generate_chapter, select_chapter_chunks, CHAPTER_REGISTRY, build_evidence_pack, validate_evidence_pack, persist_evidence_pack, run_tone_normalizer, ToneReviewResult
  models.py          # CallOpenAiFn (Protocol), CHAPTER_REGISTRY, ChapterResult, MemoOutput, ToneReviewEntry, ToneReviewResult (LEAF)
  prompts.py         # All from memo_chapter_prompts.py — imports models only
  evidence.py        # build_evidence_pack, validate_evidence_pack, persist_evidence_pack, compress_to_budget — imports models only
  tone.py            # run_tone_normalizer — imports models only
  batch.py           # build_chapter_request, submit_chapter_batch, poll_batch, parse_batch_results — imports models only
  chapters.py        # generate_chapter, generate_recommendation_chapter, select_chapter_chunks, build_evidence_summary, filter_evidence_pack, regenerate_chapter_with_critic — imports models, prompts, evidence
  service.py         # generate_memo_book, async_generate_memo_book — imports ALL above (sole orchestrator)
```

**DAG enforcement:** The import hierarchy is strictly:
```
models.py → (prompts | evidence | tone | batch) → chapters.py → service.py
```
No reverse imports. `chapters.py` may import `prompts` and `evidence` but NOT `service`. `service.py` is the only file that imports `chapters`.

**Callers to update:**
- `deep_review.py:367,1025,1166,1652,2278,2406` — memo_book, memo_chapter, memo_evidence, tone imports
- `deep_review_corpus.py:341` — `CHAPTER_REGISTRY` from memo_book_generator
- `app/domains/credit/modules/ai/memo_chapters.py:477` — memo_book imports
- `test_vertical_engines.py:45-46,51,58,60,65` — update 6 entries to 1 package
- Delete absorbed flat files: `tone_normalizer.py`, `batch_client.py`

**Golden tests:** Capture `CHAPTER_REGISTRY` structure, `build_evidence_pack()` output format.

## Per-PR Checklist

Every PR must satisfy all items before merge:

```
[ ] models.py (if applicable) — @dataclass(frozen=True, slots=True), zero sibling imports (leaf node)
[ ] Domain modules — each imports models.py or lower-tier siblings within the package; no module imports service.py
[ ] service.py (if applicable) — sole orchestrator, fans out to domain modules. Skip if no orchestration logic exists.
[ ] __init__.py — __all__ defined. PEP 562 lazy imports only for heavy-dep packages (kyc, market_data, memo, pipeline); standard imports for lightweight packages.
[ ] Error contract documented — never-raises with status field for orchestration engines; raises-on-failure for transactional/pure-computation engines
[ ] structlog — logger = structlog.get_logger() in every module. Log at function boundaries only (no logging in numeric loops).
[ ] Dict return at API boundary — custom _to_dict() or dataclasses.asdict() for flat leaves. Keep existing manual to_dict() methods (e.g., QuantProfile).
[ ] Golden tests — for complex functions with many output fields. Standard unit tests for trivial pure functions (<10 LOC).
[ ] All callers updated — grep confirms zero remaining old import paths
[ ] deep_review.py imports updated — function-level import paths changed
[ ] test_vertical_engines.py::EXPECTED_MODULES updated
[ ] Dependency DAG verified — no circular imports (python -c "import vertical_engines.credit.{package}")
[ ] Old flat file(s) deleted
[ ] make check passes — lint + typecheck + test
```

## deep_review.py — Complete Caller Map

Each Wave 1 PR modifies specific lines in `deep_review.py`. This map prevents missed updates:

| Line(s) | Current Import | Target Package | PR # |
|---|---|---|---|
| 365, 505, 1647 | `ic_critic_engine` | `critic` | 1 |
| 373, 1658 | `sponsor_engine` | `sponsor` | 2 |
| 680, 1939, 2021 | `kyc_pipeline_screening` | `kyc` | 3 |
| 473, 1741 | `retrieval_governance` | `retrieval` | 4 |
| _(none directly)_ | `pipeline_engine` | `pipeline` | 5 |
| 366, 1651 | `ic_quant_engine` | `quant` | 6 |
| 452, 1730, 1799 | `market_data_engine` | `market_data` | 7 |
| _(none directly)_ | `portfolio_intelligence` | `portfolio` | 8 |
| _(none directly)_ | `deal_conversion_engine` | `deal_conversion` | 9 |
| 1341, 1375, 2537, 2540 | `underwriting_artifact` | `underwriting` | 10 |
| _(none directly)_ | `domain_ai_engine` | `domain_ai` | 11 |
| 367, 1025, 1166, 1652, 2278, 2406 | `memo_*`, `tone_normalizer` | `memo` | 12 |

## Acceptance Criteria

### Functional Requirements

- [ ] All 11 engines are packages with edgar-style structure
- [ ] All callers import from package `__init__.py` paths
- [ ] No flat engine files remain in `credit/` root (except deep_review cluster — Wave 2)
- [ ] `credit/prompts/*.j2` files untouched (Wave 2 handles relocation)
- [ ] `credit/__init__.py` updated with accurate entry points docstring

### Non-Functional Requirements

- [ ] Zero behavioral change — golden tests prove output parity
- [ ] `make check` passes after every PR
- [ ] No new external dependencies introduced
- [ ] structlog replaces stdlib `logging` in all migrated engines
- [ ] Error contract documented per engine (never-raises for orchestration engines, raises-on-failure for transactional/pure-computation)

### Quality Gates

- [ ] Multi-agent review (`/ce:review`) on each PR
- [ ] Golden tests with `rtol=1e-6` for numeric outputs
- [ ] Import DAG verified (no circular imports)
- [ ] `test_vertical_engines.py` passes with updated `EXPECTED_MODULES`

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Merge conflicts in `deep_review.py` | High if parallel | High | Strictly serial PRs. Each merges before next branch. |
| Missing a caller during import migration | Medium | Medium | Grep-verified caller maps per phase. `make check` catches. |
| Breaking prompt template resolution | Low | High | `.j2` files and `prompt_registry` untouched in Wave 1. |
| Golden test false negatives (tests too loose) | Low | Medium | Use `rtol=1e-6` for numerics, exact match for strings. |
| Scientific skill integration scope creep | Medium | Medium | Skills scoped to same PR only if small. Large upgrades = separate PR. |
| retrieval/ never-raises changes caller control flow | Medium | High | Document all catch sites. Keep exception classes in models.py during Wave 1. |
| Premature dataclass formalization (scope creep) | Medium | Low | Do NOT formalize dicts → dataclasses during this refactor. Keep existing types. |

## Dependencies & Prerequisites

- **PR #7 (Macro Intelligence Suite) MUST be merged before Wave 1 PR #1.** PR #7 modifies `deep_review.py`. Starting Wave 1 before that merge creates an immediate conflict on PR #1. Sequence: Macro Suite merge → Wave 1 PR #1. These are NOT parallel.
- **PR #0 (preparatory): Add import-linter to `make check` BEFORE PR #1.** Install `import-linter`, add contracts to `pyproject.toml`, add `make architecture` target to Makefile. This ensures ALL 12 Wave 1 PRs pass the DAG enforcement gate — not just the later ones. Contracts should include: vertical independence, no-domain-imports-service, no-circular-within-packages. Start with `ignore_imports` for any pre-existing violations.
- `make check` must pass on current `main` before starting

## Research Insights

### Best Practices (from best-practices-researcher)

**PEP 562 lifecycle:** PEP 810 (accepted November 2025) introduces native `lazy import` syntax in Python 3.15 (October 2026). Until then, manual `__getattr__` or `lazy_loader` are the standard approaches. Set `EAGER_IMPORT=1` in CI to catch deferred ImportErrors early.

**structlog configuration:** Use `cache_logger_on_first_use=True` for performance. Log at function boundaries (entry/exit + errors), never inside tight numerical loops. Use `structlog.contextvars` for async context propagation.

**Import DAG enforcement — import-linter:** Add to `make check` to lock the architecture post-refactor:
```ini
# .importlinter or pyproject.toml
[importlinter:contract:vertical-independence]
name = Verticals must not import each other
type = independence
modules =
    backend.vertical_engines.credit
    backend.vertical_engines.wealth

[importlinter:contract:engine-internal-dag]
name = No domain module imports service
type = forbidden
source_modules = backend.vertical_engines.credit.*.models
forbidden_modules = backend.vertical_engines.credit.*.service
```

**dataclasses.asdict() alternatives:** For flat dataclasses (QuantProfile, 30+ fields), manual `to_dict()` is faster. `asdict()` does recursive `deepcopy` which is expensive for nested structures. `msgspec.Struct` is 4x faster for creation, but adds a dependency — defer to post-refactor evaluation.

### Security Insights (from security-sentinel)

**PromptRegistry uses non-sandboxed Jinja2** (`Environment` instead of `SandboxedEnvironment`) — violates CLAUDE.md rule. Pre-existing issue, not blocking Wave 1. Track as separate fix: `backend/ai_engine/prompts/registry.py:57`.

**Never-raises status field:** Failed analyses MUST set `status: 'NOT_ASSESSED'` or `status: 'ERROR'` in the result dict, so callers distinguish clean results from failed analyses. Critical for kyc/ (Phase 3) where screening failure should be visible in IC memo.

## Sources & References

### Origin

- **Brainstorm:** [docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md](docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md) — Key decisions: edgar pattern canonical, no backward-compat shims, full standardization, serial PRs, absorption criteria

### Internal References

- Architecture pattern: `docs/solutions/architecture-patterns/monolith-to-modular-package-with-library-migration.md`
- Extraction patterns: `docs/solutions/architecture-patterns/vertical-engine-extraction-patterns.md`
- Thread safety: `docs/solutions/runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md`
- Golden test boundaries: `docs/solutions/logic-errors/credit-stress-grading-boundary-StressSeverity-20260315.md`
- Pydantic config: `docs/solutions/runtime-errors/fred-api-key-case-mismatch-MarketDataEngine-20260315.md`
- Unused params: `docs/solutions/logic-errors/window-days-ignored-InsiderSignals-20260315.md`
- Reference implementation: `backend/vertical_engines/credit/edgar/`
- Structural test: `backend/tests/test_vertical_engines.py:39-67`

### Related Work

- Quant parity refactor: commit `bdabdc8`
- EDGAR upgrade: PR #5
