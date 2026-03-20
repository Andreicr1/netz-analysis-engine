# Retrieval Confidence Signals — Delta/Rank-Based Decision Layer

## Context

Read these files first:

- `docs/reference/pipeline-quality-validation-2026-03-19.md` (validation report)
- `backend/ai_engine/extraction/local_reranker.py` (cross-encoder reranker)
- `backend/ai_engine/extraction/pgvector_search_service.py` (search + rerank wrappers)
- `backend/vertical_engines/credit/retrieval/corpus.py` (ic_coverage_rerank)
- `backend/vertical_engines/credit/retrieval/models.py` (constants, ChapterEvidenceThreshold)
- `backend/vertical_engines/credit/retrieval/evidence.py` (evidence assembly, _best_score)
- `backend/vertical_engines/credit/retrieval/saturation.py` (confidence levels)
- `backend/vertical_engines/credit/pipeline/screening.py` (pipeline screening)
- `backend/vertical_engines/credit/domain_ai/service.py` (portfolio monitoring)
- `backend/app/domains/credit/modules/ai/copilot.py` (fund copilot RAG)

## Problem

The retrieval pipeline currently returns results sorted by rank (reranker_score or cosine score) but provides NO signal about retrieval confidence to downstream consumers. Callers have no way to distinguish "the system found one clearly dominant result" from "the system is guessing between 5 equally-scored candidates."

Absolute score thresholds (e.g., `score > 0.6`) are fragile — they shift with corpus size, document heterogeneity, and chunk length. The correct approach is relative: rank-based, delta-based, and percentile-based signals that are intrinsic to each query's result distribution.

### Why relative over absolute

| Approach | Failure mode |
|---|---|
| `score > 0.6` threshold | Breaks when corpus grows (score distribution shifts), when chunk length changes (longer chunks dilute similarity), or when document homogeneity increases (all scores compress into a narrow band) |
| `delta top-1 vs top-2` | Stable across corpus size because it measures separation within the query, not absolute position on a global scale |
| `percentile within query` | Self-calibrating — adapts to whatever score distribution the query produces |

In financial/legal document retrieval, the question is never "is this score high enough?" but rather "does this result clearly separate from the alternatives?"

## Design

### 1. RetrievalSignal dataclass

New file: `backend/ai_engine/extraction/retrieval_signal.py`

Create a frozen dataclass that captures confidence metadata for a query's result set:

```python
@dataclasses.dataclass(frozen=True)
class RetrievalSignal:
    top1_score: float           # best score (reranker_score preferred, else cosine)
    top2_score: float | None    # second-best score (None if only 1 result)
    delta_top1_top2: float      # gap between rank-1 and rank-2 (0.0 if <=1 result)
    percentile_top1: float      # top1 score as percentile within result set (0-1)
    result_count: int           # total results returned
    confidence: str             # "HIGH" | "MODERATE" | "LOW" | "AMBIGUOUS"
```

Confidence classification (starting heuristics, tunable — constants at top of file):

| Level | Reranker logits condition | Cosine condition | Additional |
|---|---|---|---|
| HIGH | `delta > 2.0` | `delta > 0.08` | AND `result_count >= 3` |
| MODERATE | `delta > 0.5` | `delta > 0.03` | — |
| AMBIGUOUS | `delta <= 0.5` | `delta <= 0.03` | AND `result_count >= 5` |
| LOW | — | — | `result_count < 3` OR `top1 < median(all scores)` |

Add a `from_results()` classmethod:

```python
@classmethod
def from_results(
    cls,
    results: list[dict[str, Any]],
    score_key: str = "reranker_score",
    fallback_key: str = "score",
) -> "RetrievalSignal":
    ...
```

This method extracts scores from the result dicts (trying `score_key` first, then `fallback_key`, then `0.0`), computes all fields, and classifies confidence. It must detect whether scores are reranker logits (can be negative, typical range -12 to +6) or cosine similarity (0-1 range) and apply the corresponding threshold scale.

**Detection heuristic:** if any score in the result set is negative, assume reranker logit scale; otherwise assume cosine scale.

### 2. RerankedResult wrapper

Enrich the return type of the `search_and_rerank_*` functions in `pgvector_search_service.py`:

```python
@dataclasses.dataclass
class RerankedResult:
    chunks: list[dict[str, Any]]
    signal: RetrievalSignal
```

The 5 `search_and_rerank_*` functions currently return `list[dict]`. Change them to return `RerankedResult`. This is a breaking interface change — update all callers.

### 3. Caller integration

For each caller, integrate the signal appropriately to its use case:

#### a) copilot.py — RAG exploratório

Pass signal through to API response. Add `retrieval_confidence: str` field to the copilot response schema so the frontend can show confidence indicators. No filtering — copilot always returns results, user judges.

#### b) screening.py — pipeline screening

Log signal. If confidence is `AMBIGUOUS`, add a `_retrieval_ambiguous: true` flag to the screening context so the LLM prompt can hedge its assessment. Do NOT block screening on low confidence.

#### c) domain_ai/service.py — portfolio monitoring

Log signal. If confidence is `LOW`, prepend a caveat to the LLM context: `"Note: limited documentary evidence was found for this query."` No blocking.

#### d) evidence.py — IC evidence pack (most critical consumer)

Add signal to the evidence audit metadata (the saturation dict). When confidence is `AMBIGUOUS` for a chapter query, mark the chapter coverage as `EVIDENCE_CONTESTED` (new status alongside `SATURATED`/`PARTIAL`/`MISSING`). The IC memo generator can then flag contested evidence to the analyst.

#### e) corpus.py — ic_coverage_rerank

Pass through signal. `ic_coverage_rerank` receives already-reranked chunks, so it should accept and forward the `RetrievalSignal`, not recompute it.

### 4. Tests

New file: `backend/tests/test_retrieval_signal.py`

| Test | Assertion |
|---|---|
| `test_high_confidence` | One dominant result with large gap -> HIGH |
| `test_ambiguous` | Top 5 results within tight score band -> AMBIGUOUS |
| `test_low_result_count` | Only 1-2 results -> LOW |
| `test_moderate` | Clear but not dominant gap -> MODERATE |
| `test_from_results_uses_reranker_score_first` | Verifies score_key fallback chain |
| `test_from_results_empty` | Empty list -> LOW with zeros |
| `test_cosine_vs_reranker_thresholds` | Different threshold scales applied based on detected score range |

### 5. NOT in scope

- No BM25 hybrid search (separate initiative)
- No changes to embedding model or pgvector index
- No changes to chunking or classification
- No absolute score thresholds anywhere
- No blocking of results based on signal (signal is advisory, never gate)
- Do not modify the reranker model or its parameters

## Constraints

- `RetrievalSignal` lives in `ai_engine/` (domain-agnostic). It must NOT import from `vertical_engines/` or `app/domains/`.
- The confidence thresholds must be constants at the top of `retrieval_signal.py`, clearly labeled as tunable heuristics.
- All existing tests must continue passing. Run `make check` before committing.
- Branch: `feat/retrieval-confidence-signals`
- Single PR with clear commit message.

## Architecture summary

```
pgvector cosine search (candidates=50-120)
    |
    v
cross-encoder rerank (top_k=10-80)
    |
    v
RetrievalSignal.from_results(chunks)  <-- NEW
    |
    v
RerankedResult { chunks, signal }     <-- NEW return type
    |
    +---> copilot:     signal.confidence in API response
    +---> screening:   _retrieval_ambiguous flag if AMBIGUOUS
    +---> domain_ai:   caveat prefix if LOW
    +---> evidence:    EVIDENCE_CONTESTED status if AMBIGUOUS
    +---> corpus:      pass-through signal
```
