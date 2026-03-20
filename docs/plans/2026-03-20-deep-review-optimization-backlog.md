# Deep Review Optimization — Comprehensive Backlog Plan

**Origin:** `docs/reference/deep-review-optimization-plan-2026-03-20.md`
**Date:** 2026-03-20
**Baseline:** E2E test on current state running before any changes.

---

## Architecture Overview

The optimization has two layers across 7 phases. Each phase is a self-contained branch and PR.

**Layer 2 — Prompt Architecture (Phases 1-3)**
Signal-aware generation: prompts adapt to evidence quality per chapter.

**Layer 1 — Retrieval & Evidence Infrastructure (Phases 4-6)**
Simplifies retrieval by removing dead code, unifying search tiers, and removing legacy blob fallbacks.

**Deferred — Phase 7**
`_pre_classify_from_corpus()` deprecation requires 50+ deal concordance data.

### Data Flow (current → target)

```
CURRENT:
  evidence.py → per-chapter result dict with "retrieval_signal" → DROPPED (never consumed)
  chapters.py → prompt_registry.render(ch_tag.j2) → static prompt → LLM

TARGET:
  evidence.py → per-chapter result dict with "retrieval_signal" → propagated via retrieval_audit
  corpus.py → _gather_deal_texts() → collects chapter signals into chapter_signals dict
  chapters.py → prompt_registry.render(ch_tag.j2, retrieval_confidence=signal) → adaptive prompt → LLM
```

---

## Phase 1 — Signal-Aware Evidence Context Block

**Branch:** `feat/deep-review-signal-aware-prompts`
**Risk:** Low — additive only, no existing logic removed
**Dependencies:** RetrievalSignal (done)

### What

1. **Propagate `retrieval_signal.confidence` from `evidence.py` through `corpus.py` to `chapters.py`**
   - `evidence.py` already computes per-chapter `RetrievalSignal` (line 268-293) and stores it in the result dict under `"retrieval_signal"` key
   - `corpus.py:_gather_deal_texts()` (line 258-386) calls `gather_chapter_evidence()` and gets results back — must extract `chapter_tag → confidence` mapping
   - `chapters.py:_get_chapter_base_prompt()` (line 38-42) renders templates — must pass `retrieval_confidence` to template context

2. **Create shared Jinja2 include: `_evidence_context.j2`**
   - Conditional block with 4 branches: HIGH / MODERATE / AMBIGUOUS / LOW
   - Placed in `backend/vertical_engines/credit/prompts/`
   - Included via `{% include '_evidence_context.j2' %}` in each chapter template

3. **Inject `{% include '_evidence_context.j2' %}` into 8 chapter templates**
   - `ch01_exec.j2` — after scope section, before "Cover:" (tone calibration)
   - `ch04_sponsor.j2` — before "Cover:" (source disagreement on titles/roles)
   - `ch06_terms.j2` — before mandatory table (contested terms handling)
   - `ch08_returns.j2` — replace MISSING-DATA FALLBACK PROTOCOL (lines 102-115) with include
   - `ch09_downside.j2` — replace fallback protocol (lines 71-76) with include
   - `ch10_covenants.j2` — before mandatory table (contested covenant values)
   - `ch05_legal.j2` — before analysis section
   - `ch07_capital.j2` — before analysis section
   - Leave unchanged: `ch02_macro.j2` (FRED deterministic), `ch03_exit.j2` (macro system data), `ch11_risks.j2` (analytical framework), `ch12_peers.j2` (benchmark framework), `ch13_recommendation.j2` (synthesis), `ch14_governance_stress.j2` (governance framework), `critic.j2` (evaluates output)

4. **Default to `"MODERATE"` when signal is unavailable**
   - Safety: if plumbing fails or chapter has no retrieval (ch02, ch03), defaults to current behavior

### Files Modified

| File | Change |
|---|---|
| `vertical_engines/credit/retrieval/evidence.py` | Already exposes signal — no change needed |
| `vertical_engines/credit/deep_review/corpus.py` | Extract `chapter_signals` dict from `gather_chapter_evidence()` results |
| `vertical_engines/credit/memo/chapters.py` | Accept `chapter_signals` param, pass `retrieval_confidence` to `prompt_registry.render()` |
| `vertical_engines/credit/memo/service.py` | Thread `chapter_signals` from corpus through to chapter generation |
| `vertical_engines/credit/prompts/_evidence_context.j2` | NEW — shared conditional block |
| `vertical_engines/credit/prompts/ch01_exec.j2` | Add include |
| `vertical_engines/credit/prompts/ch04_sponsor.j2` | Add include |
| `vertical_engines/credit/prompts/ch05_legal.j2` | Add include |
| `vertical_engines/credit/prompts/ch06_terms.j2` | Add include |
| `vertical_engines/credit/prompts/ch07_capital.j2` | Add include |
| `vertical_engines/credit/prompts/ch08_returns.j2` | Replace fallback protocol with include |
| `vertical_engines/credit/prompts/ch09_downside.j2` | Replace fallback protocol with include |
| `vertical_engines/credit/prompts/ch10_covenants.j2` | Add include |

### Tests

- Unit: `RetrievalSignal` confidence → correct template branch rendered (parametrize HIGH/MODERATE/AMBIGUOUS/LOW)
- Unit: `chapter_signals` extraction from `gather_chapter_evidence()` result shape
- Unit: default `"MODERATE"` when signal missing
- Integration: full `_gather_deal_texts()` → chapter generation with mocked evidence returns expected prompt fragments

### Acceptance Criteria

- `make check` passes (1405+ tests)
- E2E comparison: same deal produces different prompt text for HIGH vs LOW evidence chapters
- No change to memo output structure (JSON schema unchanged)
- Templates without include (`ch02`, `ch03`, `ch11-ch14`, `critic`) remain byte-identical

---

## Phase 2 — EVIDENCE_CONTESTED in Mandatory Tables

**Branch:** `feat/deep-review-evidence-contested`
**Risk:** Low — extends existing [NOT FOUND] pattern
**Dependencies:** Phase 1 (AMBIGUOUS signal must be plumbed)

### What

1. **Extend table cell vocabulary in ch06, ch08, ch10 templates**
   - Current: `value` or `[NOT FOUND IN EVIDENCE]` / `[NOT FOUND IN DEAL DOCUMENTS]` / `[DATA GAP]`
   - New third state when `retrieval_confidence == "AMBIGUOUS"`:
     `Contested: X (Source A) / Y (Source B)`
   - Template instruction: when AMBIGUOUS, present competing values with source attribution instead of silently picking one

2. **Update ch06_terms.j2 table instructions**
   - Add AMBIGUOUS block: "When sources disagree on a term value, present both: `Contested: Prime+6.25% (ACV Contract) / SOFR+4.5% (Deal Term Sheet)`"
   - Existing [NOT FOUND IN DEAL DOCUMENTS] remains for LOW signal

3. **Update ch08_returns.j2 table instructions**
   - AMBIGUOUS: "If return metrics differ across sources, present the range with attribution"
   - Affects TABLE 1 (Base Case Return Model) cells

4. **Update ch10_covenants.j2 register table**
   - AMBIGUOUS: "Contested: DSCR 1.25x (PPM) / 1.15x (Side Letter)"

5. **Frontend rendering**
   - No frontend change needed — `Contested:` prefix is rendered as markdown text in the memo viewer
   - IC committee reads it as-is — the value is informational

### Files Modified

| File | Change |
|---|---|
| `vertical_engines/credit/prompts/_evidence_context.j2` | AMBIGUOUS block already instructs on contested handling — may add table-specific guidance |
| `vertical_engines/credit/prompts/ch06_terms.j2` | Add contested cell instruction near table |
| `vertical_engines/credit/prompts/ch08_returns.j2` | Add contested cell instruction near TABLE 1 |
| `vertical_engines/credit/prompts/ch10_covenants.j2` | Add contested cell instruction near register table |

### Tests

- Unit: AMBIGUOUS signal → template contains "Contested" instruction text
- Snapshot: render ch06 with AMBIGUOUS vs HIGH → different table instructions

### Acceptance Criteria

- `make check` passes
- AMBIGUOUS deals produce memos with `Contested:` cells; HIGH deals do not
- [NOT FOUND] still appears for LOW signal chapters

---

## Phase 3 — Confidence Block 2 Migration to RetrievalSignal

**Branch:** `feat/deep-review-confidence-signal-block2`
**Risk:** Low — replaces proxy with direct signal
**Dependencies:** Phase 1 (chapter_signals must be available)

### What

1. **Replace `_block_evidence_quality()` in `confidence.py` (lines 249-293)**
   - Current: counts `unique_docs < 3` and `chunk_count < 6` per critical chapter → penalty
   - New: reads `chapter_signals[ch_key].confidence` per critical chapter
     - HIGH → 0 penalty
     - MODERATE → 1 penalty
     - AMBIGUOUS → 2 penalty (evidence exists but disagrees)
     - LOW → 3 penalty (no usable evidence)
   - Same 6 critical chapters: `ch04_sponsor`, `ch05_legal`, `ch06_terms`, `ch07_capital`, `ch08_returns`, `ch10_covenants`
   - Max score still 15, penalty still capped at 15

2. **Thread `chapter_signals` into `compute_underwriting_confidence()`**
   - Currently receives `evidence_pack_meta` and `retrieval_audit` — add `chapter_signals: dict[str, str]` param
   - Callers in `service.py` and `persist.py` pass the dict through

3. **Keep fallback path** for when `chapter_signals` is empty (backward compat with cached reviews)
   - Falls back to existing chunk-count logic — same as current behavior

### Files Modified

| File | Change |
|---|---|
| `vertical_engines/credit/deep_review/confidence.py` | Rewrite `_block_evidence_quality()`, add `chapter_signals` param to `compute_underwriting_confidence()` |
| `vertical_engines/credit/deep_review/service.py` | Pass `chapter_signals` to confidence scoring |
| `vertical_engines/credit/deep_review/persist.py` | Pass `chapter_signals` if available |

### Tests

- Unit: parametrize `_block_evidence_quality()` with all 4 signal levels → correct penalty
- Unit: fallback to chunk-count logic when `chapter_signals` is empty
- Integration: full confidence score with mixed signals (some HIGH, some LOW) → expected total

### Acceptance Criteria

- `make check` passes
- Confidence scores are more granular: HIGH evidence chapters contribute full points
- Score for same deal should be close to previous (both methods measure similar quality) but more responsive to actual retrieval discrimination

---

## Phase 3B — Policy Loader: Wire ConfigService, Remove Azure Search

**Branch:** `feat/deep-review-policy-configservice`
**Risk:** Low — ConfigService path already implemented and tested, callers already accept `policy=` param
**Dependencies:** None (independent, can run in parallel with Phases 2-3)

### Problem

`policy_loader.py` has a dual personality:
- **Path A (dead):** `load_policy_thresholds()` without `config=` → Azure Search HTTP requests to `risk-policy-index` / `fund-constitution-index` → LLM extraction → module-level cache. Azure Search was deprecated (commit 497df51). This path silently fails and falls through to hardcoded `_DEFAULTS`.
- **Path B (correct):** `load_policy_thresholds(config=dict)` → `resolve_governance_policy(config)` → `PolicyThresholds` from ConfigService JSONB. Pure function, ~100us, no cache needed.

The seed YAML (`calibration/seeds/private_credit/governance_policy.yaml`) is already implanted in PostgreSQL via migration 0007. `ConfigService.get("private_credit", "governance_policy", org_id)` returns the correct config. But all 3 callers use the dead Azure Search path:

| Caller | Location | Pattern |
|---|---|---|
| `deep_review/service.py` | line 312 | `_load_policy()` — no config, no org_id |
| `deep_review/policy.py` | line 167 | `load_policy_thresholds()` — no config |
| `concentration_engine.py` | line 191 | `load_policy_thresholds()` — no config |

All 3 have `# TODO(Sprint 3): wire ConfigService when async session migration lands`.

### What

1. **Change `load_policy_thresholds()` signature** to require ConfigService config:
   ```python
   def load_policy_thresholds(
       config: dict[str, Any] | None = None,
   ) -> PolicyThresholds:
       return resolve_governance_policy(config)
   ```
   - Remove `force_reload` param (no cache needed)
   - Remove Azure Search path entirely
   - Keep `resolve_governance_policy()` as-is (already correct)

2. **Wire callers to pass ConfigService config:**
   - `deep_review/service.py` line 309-312: has `organization_id` in scope → `ConfigService.get("private_credit", "governance_policy", org_id)`
   - `deep_review/policy.py` line 163-167: accepts `policy` param from caller — callers in `service.py` should pass it through
   - `concentration_engine.py` line 189-191: accepts `policy` param from caller — callers should pass it through

3. **Remove from `policy_loader.py`:**
   - Azure Search helpers: `_search()`, `_dedup_chunks()`, `_build_context()`, `_first_source()` (~65 lines)
   - LLM extraction: `_extract_with_llm()`, `_apply_extracted()` (~55 lines)
   - Module-level cache: `_cache`, `_CACHE_TTL_SECONDS`, `invalidate_cache()` (~8 lines)
   - Azure Search config: `SEARCH_API_VER`, `_search_endpoint()`, `_search_api_key()`, index constants (~15 lines)
   - `import httpx` (only used by `_search()`)

4. **Keep:**
   - `_DEFAULTS` dict — auditable fallback values, referenced by `resolve_governance_policy()`
   - `ThresholdEntry` model — used by `PolicyThresholds` fields
   - `PolicyThresholds` model — consumed by `policy.py`, `concentration_engine.py`
   - `resolve_governance_policy()` — the correct ConfigService resolver
   - `load_policy_thresholds()` — simplified to delegate to `resolve_governance_policy()`

5. **Also check `deep_review/policy.py`** — line 50-143 `_gather_policy_context()` uses deprecated `AzureSearchChunksClient` directly. This is the policy compliance *evidence* retrieval (separate from threshold loading). Should be migrated to pgvector search, but that's a larger change — flag with TODO for now.

### Files Modified

| File | Change |
|---|---|
| `ai_engine/governance/policy_loader.py` | Remove Azure Search + LLM extraction (~145 lines), simplify `load_policy_thresholds()` |
| `vertical_engines/credit/deep_review/service.py` | Wire ConfigService at lines 309-312, 1371-1372, 1486-1487 |
| `vertical_engines/credit/deep_review/policy.py` | Remove `load_policy_thresholds()` fallback at line 167, accept `policy` from caller |
| `ai_engine/portfolio/concentration_engine.py` | Remove `load_policy_thresholds()` fallback at line 191, accept `policy` from caller |

### Tests

- Existing tests in `test_governance_policy_config.py` already test `resolve_governance_policy()` and `load_policy_thresholds(config=...)` — should still pass
- Remove any test that tests Azure Search path (if any)
- Add test: `load_policy_thresholds(config=None)` returns defaults (no Azure Search call)
- `make check` passes

### Acceptance Criteria

- Zero `httpx` import in `policy_loader.py`
- Zero Azure Search references in `policy_loader.py`
- Zero LLM extraction in `policy_loader.py`
- All callers pass config from ConfigService
- `PolicyThresholds` values match seed YAML when no org-level override exists

---

## Phase 4 — Doc-Type Filter Dead Code Removal

**Branch:** `feat/deep-review-remove-doctype-filters`
**Risk:** Low — removing dead code
**Dependencies:** None (independent of Phases 1-3)

### What

`CHAPTER_DOC_TYPE_FILTERS` in `retrieval/models.py` (lines 123-187) defines per-chapter OData filter strings. These were used with Azure Search. After pgvector migration, the `doc_type_filter` parameter in `evidence.py` is accepted but **never applied to pgvector queries** — it's stored in the result dict but has no effect on retrieval. This is dead code.

1. **Remove `CHAPTER_DOC_TYPE_FILTERS` from `retrieval/models.py`**
2. **Remove `doc_type_filter` / `override_filter` params from `gather_chapter_evidence()`** in `evidence.py`
3. **Remove callers that pass these params** (if any)
4. **Keep `CHAPTER_DOC_AFFINITY` in `memo/prompts.py`** — different concern (evidence pack section filtering, not retrieval filtering)
5. **Keep `CRITICAL_DOC_TYPES` in `retrieval/models.py`** — used for critical document always-include logic (different from OData filtering)

### Files Modified

| File | Change |
|---|---|
| `vertical_engines/credit/retrieval/models.py` | Remove `CHAPTER_DOC_TYPE_FILTERS` dict (~65 lines) |
| `vertical_engines/credit/retrieval/evidence.py` | Remove `doc_type_filter` / `override_filter` params and result dict entries |
| Any callers passing `doc_type_filter` | Remove the kwarg |

### Tests

- Verify no test references `CHAPTER_DOC_TYPE_FILTERS` — if any do, remove them
- `make check` passes

### Acceptance Criteria

- `CHAPTER_DOC_TYPE_FILTERS` removed
- `doc_type_filter` param removed from `gather_chapter_evidence()`
- No functional change to retrieval behavior (params were already no-ops)

---

## Phase 5 — Search Tier Unification + Signal-Based Expansion

**Branch:** `feat/deep-review-uniform-search-tiers`
**Risk:** Low — parameter change, testable locally
**Dependencies:** Phase 1 (needs RetrievalSignal plumbed to retry logic)

### What

`CHAPTER_SEARCH_TIERS` in `retrieval/models.py` assigns static candidate pools: (200, 300) for 4 legal/governance chapters, (80, 150) for all others. This over-provisions for legal chapters that the reranker handles well.

1. **Unify to `DEFAULT_SEARCH_TIER = (100, 150)` for all chapters**
2. **Add signal-based expansion:** after first retrieval pass, if `RetrievalSignal.confidence` is LOW or AMBIGUOUS, retry with expanded pool `(200, 300)`
3. **Remove `CHAPTER_SEARCH_TIERS` per-chapter overrides**

### Files Modified

| File | Change |
|---|---|
| `vertical_engines/credit/retrieval/models.py` | Remove `CHAPTER_SEARCH_TIERS`, update `DEFAULT_SEARCH_TIER` to `(100, 150)` |
| `vertical_engines/credit/retrieval/evidence.py` | Add signal-based expansion retry after first pass |

### Tests

- Unit: LOW signal triggers expansion retry
- Unit: HIGH/MODERATE signal does NOT trigger retry
- Integration: verify total candidate counts for legal vs non-legal chapters converge

### Acceptance Criteria

- `make check` passes
- Average candidate pool reduced for legal chapters
- Recall maintained (validated by comparing retrieval audit stats before/after)

---

## Phase 6 — Legacy Blob Fallback Removal

**Branch:** `feat/deep-review-remove-legacy-blob`
**Risk:** Low — confirmed dead path (all data in pgvector, blob path was abandoned)
**Dependencies:** None (independent)

### What

The blob fallback paths in `corpus.py` were a safety net when retrieval was unreliable. All document data is now in pgvector — the blob path was an abandoned development approach. Remove:

1. **Remove `_gather_deal_texts_legacy()`** (corpus.py lines 390-422) — blob-scan fallback for deals
2. **Remove `_gather_investment_texts_legacy()`** (corpus.py lines 496-529) — blob-scan fallback for investments
3. **Remove `_extract_text_from_blob()`** (corpus.py lines 33-54) — blob download helper
4. **Remove fallback call in `_gather_deal_texts()`** (lines 371-386) — when corpus < 200 chars, currently falls through to legacy. Instead: return empty corpus with warning log, let downstream handle gracefully
5. **Remove fallback call in `_gather_investment_texts()`** (lines 486-493) — same pattern
6. **Remove `from app.services.blob_storage import blob_uri, download_bytes`** (line 19)
7. **Remove `from app.services.text_extract import ...`** (line 20) if only used by blob functions
8. **Update `__all__`** — remove `_load_deal_context_from_blob` only if also removed (NOTE: `_load_deal_context_from_blob` is still used in `service.py` primary path — DO NOT remove it yet, that's a separate concern)

### Files Modified

| File | Change |
|---|---|
| `vertical_engines/credit/deep_review/corpus.py` | Remove 3 functions (~140 lines), remove blob import, update fallback paths to return empty + warning |

### Tests

- Remove any tests that test legacy blob fallback behavior
- Add test: when RAG returns < 200 chars, corpus is returned as-is (no fallback)
- `make check` passes

### Acceptance Criteria

- Zero references to `_gather_deal_texts_legacy` or `_gather_investment_texts_legacy` in codebase
- `_extract_text_from_blob` removed from corpus.py
- `blob_storage` import removed from corpus.py
- `_load_deal_context_from_blob` remains (still used in primary path — separate cleanup)

---

## Phase 7 — `_pre_classify_from_corpus()` Deprecation (DEFERRED)

**Branch:** `feat/deep-review-deprecate-pre-classifier`
**Risk:** Low — monitor concordance before removing
**Status:** Concordance logging ACTIVE (added 2026-03-20 in `service.py` — both sync and async paths log `pre_classify_concordance.mismatch` / `.match`)

### Prerequisites (BOTH must be true simultaneously)

1. **CrossEncoder reranker functional** — PyTorch meta tensor error must be resolved. Without the reranker, chunks arriving at Stage 3 are less specific, making the pre-classifier a genuine safety net rather than a redundant step. Removing the classifier while the reranker is degraded stacks two risks: less specific evidence + no deterministic type hint.

2. **50+ deals with concordance ≥ 95%** — measured from production logs (`pre_classify_concordance.match` vs `.mismatch`). The 50-deal threshold provides minimum statistical confidence that Stage 3 is self-sufficient.

### Why both conditions matter

The pre-classifier costs ~0 at runtime (deterministic keyword matching, no API calls). The asymmetric risk: if it's redundant, keeping it is harmless; if it's needed, removing it means instrument misclassification propagates silently through the entire memo (wrong covenant types, wrong return analysis framework, wrong risk categories).

### What (when prerequisites are met)

- Remove `_pre_classify_from_corpus()` (~150 lines in `prompts.py` lines 40-194)
- Remove concordance logging from `service.py`
- Remove `pre_instrument_type` variable and its injection into `_build_deal_review_prompt_v2()`
- Update tests

### Acceptance Criteria

- Reranker operational (no meta tensor error)
- Concordance data from 50+ deals showing ≥ 95% agreement
- Pre-classifier removed, tests updated
- `make check` passes

---

## Phase Dependency Graph

```
Phase 1 (signal-aware prompts)
  ├── Phase 2 (EVIDENCE_CONTESTED) ── depends on Phase 1
  ├── Phase 3 (confidence Block 2) ── depends on Phase 1
  └── Phase 5 (search tier unification) ── depends on Phase 1

Phase 3B (policy ConfigService) ── independent
Phase 4 (doc-type filter dead code) ── independent
Phase 6 (legacy blob removal) ── independent

Phase 7 (pre-classifier deprecation) ── DEFERRED, needs reranker fix + 50+ deals concordance ≥95%
```

**Execution order:**
- Phases 1, 3B, 4, 6 can start in parallel (no interdependencies)
- Phases 2 and 3 after Phase 1
- Phase 5 after Phase 1
- Phase 7 deferred until: (a) reranker operational, AND (b) 50+ deals concordance ≥95%
- Concordance logging is ACTIVE — collecting data now

**Recommended sequence:** 1 → 2 → 3 → 3B → 4 → 5 → 6 (logical flow, each builds context for the next).

---

## E2E Validation Strategy

### Baseline

Captured in `docs/reference/deep-review-baseline-metrics-2026-03-20.md`. Run with **reranker DISABLED** intentionally — compares against legacy behavior (no reranking, no signal differentiation). All 14 chapters show EVIDENCE_CONTESTED uniformly.

Key baseline numbers: confidence 0.182, underwriting score 55, 1 fatal flaw (UNKNOWN instrument), 55 citations, 38K chars memo, 14/14 chapters CONTESTED.

### Reranker Fix — Required for Full Validation

The CrossEncoder reranker is disabled due to a PyTorch meta tensor error. Without it, all chapters produce AMBIGUOUS signal → uniform CONTESTED coverage. The signal-aware prompts (Phase 1) and confidence migration (Phase 3) will work correctly but won't show differentiation until the reranker is fixed.

**Reranker fix is a prerequisite for meaningful E2E comparison.** Without it:
- Phase 1: all chapters get the same AMBIGUOUS evidence context block
- Phase 2: all chapters get CONTESTED protocol (no HIGH/LOW variation)
- Phase 3: all chapters get same penalty (AMBIGUOUS=2 across the board)

The fix should be prioritized before or in parallel with Phase 1 implementation.

### Comparison Checkpoints

1. **Baseline (DONE):** `deep-review-baseline-metrics-2026-03-20.md` — reranker OFF, legacy behavior
2. **After full implementation (Phases 1-6) + reranker fix:** Same deal (BridgeInvest Credit Fund V), same DB, reranker ON → compare:
   - Coverage status distribution: should be mixed (HIGH/MODERATE/AMBIGUOUS/LOW) instead of 14/14 CONTESTED
   - Confidence score: should increase (direct signal vs proxy)
   - Memo diversity: HIGH chapters authoritative tone, LOW chapters hedged
   - Token efficiency: HIGH chapters skip fallback protocol (~15 lines saved each)
   - EVIDENCE_CONTESTED in tables: appears only where sources genuinely disagree
   - Policy thresholds: loaded from ConfigService (no Azure Search/LLM)
   - Dead code removed: blob fallback, doc-type filters, Azure Search policy loader
3. **After each phase:** `make check` passes (1405+ tests)
