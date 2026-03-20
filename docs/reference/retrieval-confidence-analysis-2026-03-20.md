# Retrieval Confidence Analysis — 2026-03-20

## Origin

Analysis conducted over the Pipeline Quality Validation Report (2026-03-19) to assess retrieval readiness for production use across different confidence tiers. This document records the findings, the identified gaps, and the architectural decisions taken.

---

## Assessment of Current State

### What is working well

**Embedding + pgvector semantic separation is solid.** The synthetic corpus test (5 hand-written chunks, 10 queries) achieved 10/10 rank-1 accuracy with a diagonally dominant similarity matrix and an average gap of 0.273 between top-1 and top-2. This confirms that the vector space is not collapsing representations and that document types are well-separated when the corpus is clean.

**Cross-encoder reranker discrimination is excellent.** On synthetic data, the reranker produced a logit gap of ~15 points between the correct chunk (4.558) and irrelevant candidates (-10 to -11). Inference runs in 99ms for 50 documents on CPU. The two-stage pipeline (broad cosine recall → precise cross-encoder rerank) is architecturally correct and performant.

**Infrastructure is reliable.** 540/540 upserts succeeded, HNSW index with halfvec(3072) is operational, the CAST(:param AS type) fix eliminated asyncpg parse ambiguity, and tenant isolation was confirmed with 0 cross-org results. The retrieval layer is not being undermined by storage, indexing, or multi-tenant bugs.

**Real corpus results are better than the headline number suggests.** The reported 5/8 (62%) accuracy on BridgeInvest PDFs refers to source document match, not semantic relevance. All three "misses" returned semantically correct content from a different document in the same dataroom — a consequence of informational overlap between PPM, LPA, and Investment Memo for the same fund/deal. This is not a retrieval failure; it is a ground truth labeling limitation when documents share content about the same entities.

**Score distribution is healthy.** Real corpus top-1 scores averaged 0.577 (range 0.487–0.681), which is reasonable for long heterogeneous financial documents. Critical queries (deal structure, LTV, conflicts, withdrawals, portfolio performance) consistently surfaced substantive passages, not surface-level keyword matches.

### Where gaps remain

**Reranker is validated only on synthetic data.** The logit gap of 15 points was measured on 5 deliberately distinct chunks. The real corpus (540 chunks, many semantically overlapping) has no reported reranker logit analysis. The claim that the reranker "cleans false positives" is well-founded in principle but not yet evidenced on production-like data.

**Corpus is small and homogeneous.** 5 PDFs from a single fund, single gestora, single vertical. This validates direction but does not prove robustness across gestora styles, document structures (term sheets, side letters, Excel-to-PDF), or corpus sizes (50+ PDFs, 5000+ chunks). Score distributions may shift materially as the corpus diversifies.

**No confidence signal exists for downstream consumers.** The pipeline returns ranked results but provides no metadata about how confident the ranking is. A caller receiving 10 chunks cannot distinguish "one chunk is clearly dominant" from "10 chunks are essentially tied." This matters most for IC evidence assembly, where contested evidence should be flagged differently from clear evidence.

**No BM25 hybrid search.** The pipeline uses pure vector similarity. For keyword-heavy queries — specific clause numbers, defined terms, covenant formulas, exact siglas, threshold values — embedding-based search generalizes where the user wants literalism. This is an accepted limitation, not a defect, but it bounds the system's precision on lexical queries.

---

## Key Insight: Absolute Score Thresholds Are Wrong for This System

Score distributions in retrieval systems are not stable properties. They shift with:

- **Corpus size** — more chunks compress the score range as more near-neighbors appear
- **Document homogeneity** — a dataroom of 30 credit memos will have tighter score bands than a mixed dataroom
- **Chunk length** — longer chunks dilute cosine similarity; shorter chunks inflate it
- **Embedding model** — any model upgrade changes the absolute scale

A threshold like `score > 0.6` calibrated on 540 chunks from 5 PDFs will not transfer to 5000 chunks from 50 PDFs. It will either over-filter (rejecting relevant results in a compressed distribution) or under-filter (accepting noise in an inflated distribution).

The correct approach is **relative confidence**: measuring the relationship between candidates within a single query's result set, not their position on a global scale.

---

## Decision: Relative Confidence Signals

### Three complementary signals

| Signal | Definition | What it captures |
|---|---|---|
| **Rank position** | Ordinal position in sorted results | Useful when the consumer just needs "best available" without quality judgment |
| **Delta top-1 vs top-2** | Score gap between rank-1 and rank-2 | Whether the system has a clear answer or is choosing between tied candidates |
| **Percentile within query** | Top-1 score relative to the full result distribution | Whether the best result is an outlier (strong signal) or part of the pack (weak signal) |

### How these map to product use cases

| Use case | Current behavior | Decided behavior |
|---|---|---|
| **Copilot RAG** (exploratório) | Returns top-K, user judges | Same, but surface confidence level in response so frontend can indicate certainty |
| **Pipeline screening** | Returns top-80, LLM assesses | Same, but flag ambiguous retrieval so the LLM prompt can hedge |
| **Portfolio monitoring** | Returns top-20, LLM summarizes | Same, but prepend caveat when evidence is thin |
| **IC evidence pack** (auditável) | Saturation based on chunk count + doc diversity | Add EVIDENCE_CONTESTED status when retrieval confidence is ambiguous — contested evidence must be flagged to the analyst, not silently treated as confirmed |
| **IC coverage rerank** | Coverage bonus on top of semantic score | Pass through signal, do not recompute |

### What the signal is NOT

- It is **not a gate**. No downstream flow should block on low confidence. The signal is advisory.
- It is **not a score**. It is metadata about the score distribution, not a replacement for it.
- It is **not a quality judgment on the content**. High retrieval confidence means the system found a clearly dominant result, not that the content itself is correct or complete.

---

## Production Readiness Tiers

Based on the analysis, the retrieval system's readiness is tiered by use case:

### Ready for production use

- Semantic content discovery
- RAG exploratório (copilot, assisted search)
- Pre-selection of evidence candidates
- Pipeline screening (with human review downstream)
- Conceptual queries (theme, risk, structure, performance)

### Ready with caveats (validate further as corpus grows)

- Exact term extraction (covenants, defined terms, thresholds)
- Auditable evidence assembly (IC memos, compliance)
- Cross-document comparison within homogeneous datarooms
- Queries with strong lexical dependence (clause numbers, formulas)

### Not yet ready (requires BM25 hybrid or additional infrastructure)

- Literal search for specific strings, section numbers, or exact phrases
- Regulatory citation lookup (specific clause of specific regulation)
- Full-text keyword search as a user-facing feature

---

## Implementation Reference

The architectural decisions above are specified for implementation in `docs/reference/retrieval-confidence-signals-spec.md`. Key components:

- `RetrievalSignal` dataclass in `ai_engine/extraction/` (domain-agnostic, no vertical imports)
- `RerankedResult` wrapper replacing raw `list[dict]` return from `search_and_rerank_*` functions
- Per-caller behavioral integration (copilot, screening, domain_ai, evidence, corpus)
- Confidence thresholds as tunable constants, not hardcoded business rules
- Detection heuristic for reranker logit scale vs cosine scale (negative scores → logit)

---

## Related Documents

- `docs/reference/pipeline-quality-validation-2026-03-19.md` — validation data this analysis is based on
- `docs/reference/retrieval-confidence-signals-spec.md` — implementation specification
- `docs/reference/dual-mode-pipeline-architecture.md` — pipeline architecture context
