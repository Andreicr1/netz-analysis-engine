# Execution Prompt: Retrieval Confidence Signals

## Instruction

Implement the retrieval confidence signals layer as specified in `docs/reference/retrieval-confidence-signals-spec.md`. Read that spec fully before starting. Read CLAUDE.md for project conventions.

This is a two-part delivery on a single branch `feat/retrieval-confidence-signals`.

## Part 1 — RetrievalSignal + RerankedResult (core)

### Step 1: Read all files listed in the spec's Context section

These are the files you will modify. Understand the current interfaces before changing anything.

### Step 2: Create `backend/ai_engine/extraction/retrieval_signal.py`

- Frozen dataclass `RetrievalSignal` with fields: `top1_score`, `top2_score`, `delta_top1_top2`, `percentile_top1`, `result_count`, `confidence`
- Classmethod `from_results(results, score_key="reranker_score", fallback_key="score")` that computes all fields from a list of result dicts
- Detection heuristic: if any score is negative → reranker logit scale thresholds; otherwise → cosine scale thresholds
- Confidence thresholds as named constants at top of file, commented as tunable heuristics
- Dataclass `RerankedResult` with fields: `chunks: list[dict]`, `signal: RetrievalSignal`
- Zero imports from `vertical_engines/` or `app/domains/`

### Step 3: Modify `pgvector_search_service.py`

Change the 5 `search_and_rerank_*` functions to return `RerankedResult` instead of `list[dict]`:
- `search_and_rerank_deal` (async)
- `search_and_rerank_fund_policy` (async)
- `search_and_rerank_deal_sync` (sync)
- `search_and_rerank_fund_sync` (sync)
- `search_and_rerank_fund_policy_sync` (sync)

After the rerank call in each function, compute `RetrievalSignal.from_results(reranked)` and return `RerankedResult(chunks=reranked, signal=signal)`.

### Step 4: Update all callers to destructure RerankedResult

Each caller currently does `chunks = search_and_rerank_*(...)`. Change to `result = search_and_rerank_*(...)` and use `result.chunks` where chunks were used before. Then integrate `result.signal` per the spec:

**copilot.py** — Add `retrieval_confidence: str` to the response schema. Populate from `result.signal.confidence`. No filtering change.

**screening.py** — If `result.signal.confidence == "AMBIGUOUS"`, add `_retrieval_ambiguous: True` to the context dict passed to the LLM. Log the signal. No blocking.

**domain_ai/service.py** — If `result.signal.confidence == "LOW"`, prepend `"Note: limited documentary evidence was found for this query.\n\n"` to the context string. Log the signal. No blocking.

**evidence.py** — Add signal to the evidence audit metadata. When confidence is `AMBIGUOUS` for a chapter query, set coverage status to `"EVIDENCE_CONTESTED"` (new status). This is the most critical integration — read the existing saturation logic carefully before modifying.

**corpus.py** (`ic_coverage_rerank`) — Accept an optional `signal: RetrievalSignal | None` parameter. Pass it through without recomputing. The function already receives reranked results; the signal describes the pre-coverage-rerank distribution.

### Step 5: Tests

Create `backend/tests/test_retrieval_signal.py` with these tests:
- `test_high_confidence` — large gap, 3+ results → HIGH
- `test_ambiguous` — tight band, 5+ results → AMBIGUOUS
- `test_low_result_count` — 1-2 results → LOW
- `test_moderate` — moderate gap → MODERATE
- `test_from_results_uses_reranker_score_first` — dict has both keys, reranker_score wins
- `test_from_results_empty` — empty list → LOW with zeros
- `test_cosine_vs_reranker_thresholds` — positive-only scores use cosine thresholds; negative scores use reranker thresholds

### Step 6: Validate

Run `make check` (lint + typecheck + architecture + tests). All must pass, including the existing 1405+ tests. Fix any breakage from the interface change before committing.

## Part 2 — Commit

Single commit on branch `feat/retrieval-confidence-signals`. Commit message:

```
Add retrieval confidence signals (delta/rank-based)

- RetrievalSignal dataclass with from_results() classmethod
- RerankedResult wrapper for search_and_rerank_* functions
- Copilot: retrieval_confidence in API response
- Screening: _retrieval_ambiguous flag on AMBIGUOUS
- Domain AI: evidence caveat on LOW confidence
- Evidence: EVIDENCE_CONTESTED status on AMBIGUOUS
- ic_coverage_rerank: signal pass-through
- 7 new tests for signal classification
```

Do NOT create a PR. Leave the branch ready for review.

## Constraints

- Do not introduce absolute score thresholds anywhere. The signal is relative and advisory.
- Do not block any downstream flow based on signal. It is metadata, not a gate.
- Do not modify the reranker model, its parameters, or the embedding model.
- Do not add BM25/hybrid search — that is a separate initiative.
- Respect import-linter contracts: `ai_engine/` must not import from `vertical_engines/` or `app/domains/`.
