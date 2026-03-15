---
title: "refactor: Pipeline LLM-Deterministic Alignment"
type: refactor
status: active
date: 2026-03-15
origin: docs/brainstorms/2026-03-15-pipeline-llm-deterministic-alignment-brainstorm.md
---

# refactor: Pipeline LLM-Deterministic Alignment

## Enhancement Summary

**Deepened on:** 2026-03-15
**Review agents used:** Architecture Strategist, Performance Oracle, Security Sentinel, Data Integrity Guardian, Code Simplicity Reviewer, Pattern Recognition Specialist, Best Practices Researcher, Framework Docs Researcher

### Critical Fixes Applied

1. **AI analysis trigger gap** — `run_deal_ai_analysis()` post-batch triggering added to Task 2.3 (Architecture review)
2. **Audit trail preservation** — `write_audit_event()` calls added to unified pipeline requirements (Data Integrity + Architecture)
3. **ClassificationResult renamed** to `HybridClassificationResult` to avoid name collision with existing class in `document_intelligence.py` (Pattern review)
4. **3 hidden callers** of `classification/` package added to import graph: `document_scanner.py`, `monitoring.py`, `credit/modules/ai/documents.py` (Pattern review)
5. **entity_bootstrap.py Cohere calls** — independent HTTP calls to Cohere endpoint added to Phase 1 scope (Pattern review)
6. **CrossEncoder thread safety** — `asyncio.Lock` required for `predict()` serialization (Framework Docs + Best Practices)
7. **Content retention threshold** — loosened from 10% to 25% to accommodate legitimate header/footer/whitespace stripping (Data Integrity)
8. **Layer 2 algorithm** — replaced `NearestCentroid` with direct `cosine_similarity` on `TfidfVectorizer` output (Best Practices + Framework Docs)
9. **Security: IngestRequest.org_id** must be derived from JWT `actor.organization_id`, never from request body (Security review — HIGH)
10. **Security: SSE tenant authorization** — pre-existing vulnerability, document must be owned by authenticated tenant (Security review — HIGH)
11. **OCR text window** — Layer 2 uses head+tail (5000+2000 chars) instead of first 2000 only (Performance review)
12. **Batch throughput** — `asyncio.Semaphore` + `asyncio.gather` replaces `ThreadPoolExecutor` for async pipeline (Performance review — 5-8x improvement)
13. **fund_context on IngestRequest** — required for metadata extraction quality (Architecture + Pattern review)

### Simplification Opportunities (flagged, not all applied)

- **Phase 3 could be a separate plan** — architecturally independent, `FEATURE_ADLS_ENABLED` defaults to false (Simplicity review). Kept in plan per brainstorm scope decision, but marked as independently deployable.
- **Start with 3 critical validation gates** (OCR, content retention, chunk count), add others as needed — validation overhead is negligible per Performance review, so all 7 are kept but the 3 critical ones are flagged.
- **`priority` field removed** from `IngestRequest` — no priority queue exists (Simplicity review).

## Overview

Three-phase refactor of the document processing pipeline to replace unnecessary LLM calls with deterministic Python, unify divergent ingestion paths, and migrate storage to the ADLS bronze/silver/gold architecture via StorageClient.

**Origin:** All architectural decisions were made in the [brainstorm](docs/brainstorms/2026-03-15-pipeline-llm-deterministic-alignment-brainstorm.md). This plan translates those 7 decisions into implementable tasks with file paths, function signatures, and acceptance criteria.

## Problem Statement

The pipeline inherited from Private Credit OS has five structural issues (see brainstorm: "Why This Approach"):

1. **LLM overuse** — Classification uses Cohere Rerank (a ranking model repurposed for classification) + gpt-4.1-mini fallback for 31 doc_types. 80%+ are deterministically classifiable.
2. **Ingestion quality gap** — UI uploads get basic pypdf + page-boundary chunking (no classification, no governance). Batch gets full Mistral OCR + Cohere + LLM extraction + semantic chunking.
3. **No inter-stage validation** — Zero quality gates between pipeline stages. The 60% content loss bug from `semantic_chunker` propagated silently.
4. **StorageClient bypass** — Both pipelines use Azure Blob SDK directly. No bronze/silver/gold, no `{org_id}` path isolation.
5. **Monolith duplication** — `prepare_pdfs_full.py` (1786 LOC) duplicates logic from modular components. Bug fixes don't propagate.

## Proposed Solution

Three phases, each independently deployable (see brainstorm: Decisions 1-7):

- **Phase 1:** Deterministic foundation — hybrid classifier, local cross-encoder reranker, validation gates
- **Phase 2:** Ingestion path unification — single pipeline for all sources, delete monolith
- **Phase 3:** StorageClient + ADLS bronze/silver/gold + dual-write (ADLS source of truth, Azure Search derived index)

## Technical Approach

### Architecture

**Current state (4 pipelines, 3 classification systems):**

```
UI Upload → ingestion_worker.py → pypdf → page-chunks → Azure Search (NO classification)
Batch CLI → extraction_orchestrator.py → prepare_pdfs_full.py → Mistral OCR → Cohere → chunks → Azure Search
Domain    → domain_ingest_orchestrator.py → document_intelligence.py → LLM-only → chunks → Azure Search
Legacy    → document_classifier.py → keyword heuristic → 7 types (unused by pipeline)
```

**Target state (1 pipeline, 1 classification system):**

```
Any Source → IngestRequest → unified_pipeline.py
  → Mistral OCR → [gate] → Hybrid Classifier → [gate]
  → Semantic Chunker → [gate] → LLM Extraction → [gate]
  → Embed → [gate] → StorageClient (ADLS) → Azure Search upsert
```

### File Impact Summary

| File | Action | Phase | LOC |
|---|---|---|---|
| `ai_engine/classification/hybrid_classifier.py` | CREATE | 1 | ~300 |
| `ai_engine/extraction/local_reranker.py` | CREATE | 1 | ~80 |
| `ai_engine/pipeline/validation.py` | CREATE | 1 | ~200 |
| `ai_engine/pipeline/models.py` | CREATE | 1 | ~60 |
| `ai_engine/pipeline/unified_pipeline.py` | CREATE | 2 | ~350 |
| `ai_engine/pipeline/__init__.py` | CREATE | 2 | ~5 |
| `ai_engine/extraction/document_intelligence.py` | MODIFY | 1,2 | 766 |
| `ai_engine/extraction/cohere_rerank.py` | DELETE | 1 | 406 |
| `ai_engine/extraction/prepare_pdfs_full.py` | DELETE | 2 | 1786 |
| `ai_engine/ingestion/domain_ingest_orchestrator.py` | DELETE | 2 | 825 |
| `ai_engine/classification/document_classifier.py` | DELETE | 2 | ~200 |
| `ai_engine/classification/classifier.py` | DELETE | 2 | ~40 |
| `ai_engine/classification/doc_classifier.py` | DELETE | 2 | ~40 |
| `app/domains/credit/documents/services/ingestion_worker.py` | DELETE | 2 | 254 |
| `ai_engine/extraction/extraction_orchestrator.py` | MODIFY | 2 | 650→~150 |
| `ai_engine/ingestion/pipeline_ingest_runner.py` | MODIFY | 2 | — |
| `app/domains/credit/modules/ai/extraction.py` | MODIFY | 2 | — |
| `worker_app/function_app.py` | MODIFY | 2 | — |
| `app/services/storage_client.py` | — | 3 | 289 (exists) |

### Import Graph (callers that need updating)

```
cohere_rerank.py
  └── document_intelligence.py (async_run_full_intelligence, line 612)

document_intelligence.py
  └── domain_ingest_orchestrator.py (line 122, 485)

prepare_pdfs_full.py
  └── extraction_orchestrator.py (line 41, process_folder)

extraction_orchestrator.py
  ├── worker_app/function_app.py (line 82)
  ├── app/services/azure/pipeline_dispatch.py (line 130)
  └── app/domains/credit/modules/ai/extraction.py (lines 92, 121, 130, 143)

domain_ingest_orchestrator.py
  ├── ai_engine/ingestion/pipeline_ingest_runner.py (line 248, 544)
  ├── ai_engine/ingestion/ingest_runner.py (line 34)
  └── app/domains/credit/modules/ai/extraction.py (line 300)

ingestion_worker.py
  └── app/domains/credit/documents/routes/ingest.py

classification/classifier.py (DISCOVERED BY REVIEW — not in original graph)
  ├── ai_engine/ingestion/monitoring.py (line 10)
  └── app/domains/credit/modules/ai/documents.py (line 11)

classification/doc_classifier.py
  └── ai_engine/ingestion/document_scanner.py (line 11)

entity_bootstrap.py (DISCOVERED BY REVIEW — independent Cohere calls)
  └── Direct HTTP to Cohere endpoint (lines 700-742, not via cohere_rerank.py)

tests/test_upload_architecture.py (DISCOVERED BY REVIEW)
  └── imports ingestion_worker (lines 66, 68, 78, 81)
```

### Implementation Phases

---

#### Phase 1: Deterministic Foundation

**Goal:** Replace Cohere with hybrid classifier + local cross-encoder. Add validation gates. No existing pipeline behavior changes — new components built alongside, then switched in.

##### Task 1.1: Pipeline Models (`ai_engine/pipeline/models.py`)

Core data contracts used by all subsequent tasks.

```python
# ai_engine/pipeline/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

CANONICAL_DOC_TYPES: frozenset[str] = frozenset({
    "legal_lpa", "legal_side_letter", "legal_subscription", "legal_agreement",
    "legal_amendment", "legal_poa", "legal_term_sheet", "legal_credit_agreement",
    "legal_security", "legal_intercreditor",
    "financial_statements", "financial_nav", "financial_projections",
    "regulatory_cima", "regulatory_compliance", "regulatory_qdd",
    "fund_structure", "fund_profile", "fund_presentation", "fund_policy",
    "strategy_profile", "capital_raising", "credit_policy",
    "operational_service", "operational_insurance", "operational_monitoring",
    "investment_memo", "risk_assessment", "org_chart", "attachment", "other",
})
# ↑ Single source of truth — all classifier layers + validation gates import from here.

CANONICAL_VEHICLE_TYPES: frozenset[str] = frozenset({
    "standalone_fund", "fund_of_funds", "feeder_master",
    "direct_investment", "spv", "other",
})

@dataclass(frozen=True)
class PipelineStageResult:
    stage: str                    # "ocr", "classification", "chunking", "extraction", "embedding"
    success: bool
    data: Any                     # Stage output payload (None on failure — forces callers to check success)
    metrics: dict[str, Any]       # char_count, chunk_count, confidence, duration_ms, etc.
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

# Named HybridClassificationResult to avoid collision with existing
# document_intelligence.ClassificationResult (which uses int confidence 0-100).
@dataclass(frozen=True)
class HybridClassificationResult:
    doc_type: str
    vehicle_type: str
    confidence: float             # 0.0–1.0 unified scale
    layer: int                    # 1=rules, 2=cosine_similarity, 3=LLM

@dataclass(frozen=True)
class IngestRequest:
    """Frozen — may cross async/thread boundaries per CLAUDE.md rules.

    SECURITY: org_id MUST be derived from actor.organization_id (JWT claim),
    NEVER from request body. Use IngestRequest.for_ui_upload() or
    IngestRequest.for_batch() factory methods to enforce this binding.
    """
    source: Literal["ui", "batch", "api"]
    org_id: UUID                  # FROM JWT actor.organization_id ONLY
    vertical: str                 # "credit" | "wealth" — validated against allowlist
    document_id: UUID
    blob_uri: str
    filename: str
    fund_id: UUID | None = None
    deal_id: UUID | None = None
    version_id: UUID | None = None  # For SSE channel (UI source only)
    fund_context: dict | None = None  # Entity bootstrap aliases for metadata extraction.
    # ORIGIN: prepare_pdfs_full.py uses _CONTEXT_DEAL_NAME + _FUND_ALIASES as global
    # mutable state. Task 2.0 diff analysis maps these to fund_context fields.
    # POPULATED BY: batch wrapper (extraction_orchestrator.py) which runs entity_bootstrap
    # before calling unified_pipeline.process(). UI path: populated from fund record in DB.
    # If None, metadata extraction proceeds without alias enrichment (degraded but functional).

    def __post_init__(self):
        if self.vertical not in {"credit", "wealth"}:
            raise ValueError(f"Invalid vertical: {self.vertical!r}")
```

**Acceptance criteria:**
- [x] Frozen dataclass for `PipelineStageResult` (data=None on failure)
- [x] `HybridClassificationResult` (renamed to avoid collision with `document_intelligence.ClassificationResult`)
- [x] `CANONICAL_DOC_TYPES` + `CANONICAL_VEHICLE_TYPES` as `frozenset` — single source of truth for all layers + gates
- [x] `IngestRequest` frozen, with `vertical` allowlist validation in `__post_init__`
- [x] `IngestRequest.org_id` docstring mandates JWT-only sourcing
- [x] `fund_context` field for entity bootstrap aliases

##### Task 1.2: Hybrid Classifier (`ai_engine/classification/hybrid_classifier.py`)

Three-layer classifier replacing Cohere + LLM for doc_type and vehicle_type (see brainstorm: Decision 1).

**Layer 1 — Deterministic rules:**
- Port the 14 filename patterns from `cohere_rerank.py:233-248` (`_FILENAME_HINT_TABLE`)
- Port the richer patterns from `prepare_pdfs_full.py:652+` (`filename_hint()`)
- Add first-500-chars content rules for unambiguous types (e.g., "AUDITED FINANCIAL STATEMENTS" header)
- Target: ~40 rules covering 80% of documents
- Skip patterns (W-8BEN, W-9, FATCA) applied as pre-OCR filter, not part of classifier

**Layer 2 — TF-IDF cosine similarity (replaces NearestCentroid per best-practices review):**
- Use `TfidfVectorizer` + `cosine_similarity` from `scikit-learn` (already in `[quant]` deps)
- **Why not NearestCentroid:** with 1 exemplar per class, NearestCentroid degenerates to 1-nearest-neighbor with Euclidean distance, which is suboptimal for sparse TF-IDF vectors. Direct cosine similarity is simpler, more transparent, and avoids the L2 normalization gotcha.
- Training data: the 31 `DOC_TYPE_CANDIDATES` descriptions from `prepare_pdfs_full.py` (richer than `cohere_rerank.py` versions) serve as synthetic exemplars
- Each description is TF-IDF vectorized → becomes a reference vector
- **Input: head+tail window** — first 5000 chars + last 2000 chars of OCR text (matches existing `_rerank_ocr_window` pattern in `cohere_rerank.py`). Tail chars contain critical signals like signature blocks and entity declarations.
- `TfidfVectorizer` config: `sublinear_tf=True`, `ngram_range=(1, 2)`, `max_features=5000`, `stop_words="english"`. Bigrams capture "credit agreement" vs "side letter".
- Confidence = cosine similarity score (naturally 0.0–1.0 for TF-IDF)
- **Rejection rules (escalate directly to Layer 3, NO retry):**
  - Top-1 similarity < 0.05 → no match at all
  - Ratio of top-1 / top-2 similarity < 1.3 → ambiguous
- **Known weakness:** financial docs with shared vocabulary across close classes ("credit agreement" vs "loan agreement") produce similar vectors (see brainstorm: Decision 1 caveat)
- Vectorizer fitted once at startup (lazy init, not module-level)
- sklearn `predict()` / `transform()` IS thread-safe on fitted estimators — no lock needed

**Layer 3 — LLM fallback (gpt-4.1-mini):**
- Reuse existing `async_classify_document()` from `document_intelligence.py`
- Uses existing Jinja2 templates (`extraction/classification_system.j2`, `extraction/classification_user.j2`)
- JSON mode output normalized to `ClassificationResult`
- Only for ~5% genuinely ambiguous cases

**vehicle_type (6 classes):** Same pattern. Layer 1 rules cover 90%+ — vehicle_type is trivial.

```python
# Public API
async def classify(
    text: str,
    filename: str,
    *,
    title: str = "",
    container: str = "",
) -> HybridClassificationResult:
    """Three-layer hybrid classification. Returns doc_type + vehicle_type."""
```

**Acceptance criteria:**
- [x] `hybrid_classifier.py` with `classify()` async function
- [x] Layer 1: ≥40 filename + content rules ported from `cohere_rerank.py` and `prepare_pdfs_full.py`
- [x] Layer 2: `TfidfVectorizer(sublinear_tf=True, ngram_range=(1,2))` + `cosine_similarity` with 31 synthetic exemplars
- [x] Layer 2 uses head+tail OCR window (5000+2000 chars), not just first 2000
- [x] Layer 3: delegates to existing `async_classify_document()`
- [x] All layers return `HybridClassificationResult` with unified 0.0–1.0 confidence + layer indicator
- [x] All layers validate `doc_type in CANONICAL_DOC_TYPES` (imported from `models.py`)
- [x] Escalation chain: Layer 1 (confidence=1.0) → Layer 2 (ratio ≥ 1.3 AND sim ≥ 0.05) → Layer 3 (LLM)
- [x] No retry logic — rejection always escalates forward
- [x] Lazy init for vectorizer (not module-level)
- [ ] **Functional validation with rollback criteria:** 3 real documents from deal room:
  1. LPA → must classify as `legal_lpa` via Layer 1
     - If fails → bug in Layer 1 rules. Fix rules. Do NOT merge until passing.
  2. Audited financial statement → must classify via Layer 1 or Layer 2
     - If fails → adjust Layer 2 threshold (ratio or minimum similarity)
     - If still fails after adjustment → accept that this doc type routes to Layer 3. Document the exception.
  3. Ambiguous document (research report) → must escalate to Layer 3 (LLM)
     - If fails (Layer 2 incorrectly accepts) → Layer 2 rejection path is broken. Debug the ratio calculation.
     - If Layer 3 is not being activated at all → bug in escalation chain, not threshold.

##### Task 1.3: Local Cross-Encoder Reranker (`ai_engine/extraction/local_reranker.py`)

Replaces Cohere Rerank for RAG chunk relevance scoring only. NOT for classification (see brainstorm: Decision 2).

```python
# Public API — drop-in replacement for Cohere rerank in RAG pipeline
async def rerank(
    query: str,
    documents: list[str],
    *,
    top_n: int | None = None,
) -> list[RerankResult]:
    """Rerank documents by relevance to query using local cross-encoder."""

@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float        # 0.0–1.0 (sigmoid-normalized)
    text: str
```

- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` via `sentence-transformers`
- 22MB weights, ~250-350MB total RSS with PyTorch runtime
- **Critical: `CrossEncoder.predict()` is NOT thread-safe** — shared state in tokenizer can collide. Serialize with `asyncio.Lock` (created lazily per CLAUDE.md).
- Inference via `asyncio.to_thread()` inside the lock — cross-encoder blocks event loop otherwise (from learnings: Pattern D)
- Lazy model loading on first call with double-checked locking pattern
- **Score normalization:** raw logits (range ~-11 to +11) → numerically stable sigmoid → 0.0–1.0. Do NOT use `apply_softmax=True` (single-label model returns 1.0 always).
- **Threshold guidance for IC memo evidence:** >0.8 = high confidence, 0.5-0.8 = include with caveats, <0.3 = filter out. These differ from Cohere scales — recalibrate downstream consumers.
- Pin model to specific commit hash in production: `CrossEncoder("...", revision="<sha>")`
- Latency benchmark: ~1-3s for 80 pairs on CPU (well within 5s budget)

**Acceptance criteria:**
- [x] `local_reranker.py` with `rerank()` async function
- [x] `asyncio.Lock` serializing `predict()` calls (lazy-init, not module-level)
- [x] `asyncio.to_thread()` wrapping synchronous `CrossEncoder.predict()` inside the lock
- [x] Lazy model loading with double-checked locking (not module-level)
- [x] Numerically stable sigmoid normalization (handle both positive and negative logits)
- [ ] `sentence-transformers>=3.0,<4.0` added to `[reranker]` optional deps in `pyproject.toml`
- [ ] `torch>=2.2` pinned as floor dependency

##### Task 1.4: Validation Gates (`ai_engine/pipeline/validation.py`)

Inter-stage validators that return `PipelineStageResult` (see brainstorm: Decision 3).

```python
# Validators per stage transition
def validate_ocr_output(text: str, filename: str) -> PipelineStageResult
def validate_classification(result: ClassificationResult) -> PipelineStageResult
def validate_chunks(chunks: list, input_char_count: int) -> PipelineStageResult
def validate_extraction(metadata: dict) -> PipelineStageResult
def validate_embeddings(embeddings: list, chunk_count: int) -> PipelineStageResult
```

**Validation rules:**

| Transition | Check | Threshold | On Failure |
|---|---|---|---|
| OCR → Classification | text length | > 100 chars | FAILED + reason |
| OCR → Classification | non-printable ratio | < 30% | FAILED + reason |
| Classification → Chunking | doc_type validity | in `CANONICAL_DOC_TYPES` | FAILED + reason |
| Classification → Chunking | confidence | ≥ 0.3 (any layer) | WARNING (proceed with low confidence) |
| Chunking → Extraction | chunk count | > 0 | FAILED + reason |
| Chunking → Extraction | **content retention** | reduction < 25% of input | **FAILED + reason** (prevents 60% loss) |
| Chunking → Extraction | max chunk size | ≤ configured max | WARNING |
| Extraction → Embedding | metadata schema | validates against Pydantic model | FAILED + reason |
| Extraction → Embedding | text non-empty | each chunk has text | FAILED + reason |

**On validation failure:**
- Document marked `FAILED` with structured reason code and message
- SSE `error` event emitted (if UI source)
- `ingest_error` JSON persisted on DocumentVersion (mirrors current `ingestion_worker.py` behavior)
- Pipeline halts for this document — no retry, no quarantine
- Other documents in batch continue processing

**Acceptance criteria:**
- [x] `validation.py` with typed validators for each transition
- [x] Content retention check: `(input_chars - sum(chunk_chars)) / input_chars < 0.25` (one-directional — expansion is a separate WARNING, not FAILURE). 25% threshold accommodates legitimate stripping of headers/footers/TOC/boilerplate while catching catastrophic loss (60%+).
- [x] Return `PipelineStageResult` with success/warnings/errors
- [x] Thresholds as module constants (not hardcoded inline)

##### Task 1.5: Wire Hybrid Classifier into document_intelligence.py

Modify `async_run_full_intelligence()` (line 593-766) to use `hybrid_classifier.classify()` instead of `async_classify_doc_type()` from `cohere_rerank.py`.

**Changes:**
1. Replace `cohere_rerank.async_classify_doc_type()` call (line ~612) with `hybrid_classifier.classify()`
2. Replace `cohere_rerank.async_classify_vehicle_type()` call (line ~730) with `hybrid_classifier.classify()` vehicle_type output
3. Remove Cohere fallback logic (score < 0.35 → LLM) — hybrid classifier handles escalation internally
4. Map `HybridClassificationResult` to existing `FullIntelligenceResult` fields (confidence float→int normalization: `int(result.confidence * 100)`)

**Do NOT change:** metadata extraction, summarization, governance detection. Those are untouched.

**Acceptance criteria:**
- [x] `async_run_full_intelligence()` uses `hybrid_classifier.classify()` for both doc_type and vehicle_type
- [x] No imports from `cohere_rerank.py` remain in `document_intelligence.py`
- [x] `FullIntelligenceResult` populated correctly with new classifier output
- [x] Confidence scale mapped: `HybridClassificationResult.confidence` (0.0–1.0 float) → `FullIntelligenceResult` fields (float 0.0-1.0, same scale)
- [ ] Existing tests pass (classification results may differ but schema is compatible)

##### Task 1.5b: Eliminate Cohere from entity_bootstrap.py

**DISCOVERED BY REVIEW:** `entity_bootstrap.py` has its own Cohere dependency — direct HTTP calls to the Cohere Rerank endpoint (line 53: `COHERE_MODEL`, lines 700-742: `validate_vehicle_type_rerank`). This bypasses `cohere_rerank.py` and would survive Task 1.5's changes.

**Changes:**
- Replace `validate_vehicle_type_rerank()` with `hybrid_classifier.classify()` vehicle_type output
- Remove Cohere HTTP calls and `COHERE_MODEL` constant

**Acceptance criteria:**
- [x] No Cohere HTTP calls in `entity_bootstrap.py`
- [x] Vehicle type validation uses hybrid classifier

##### Task 1.6: Wire Local Reranker into IC Memo Pipeline

Find where Cohere Rerank is used for RAG chunk reranking (not classification) and replace with `local_reranker.rerank()`.

**Search for callers:** grep for `cohere` imports and usages outside of `document_intelligence.py`. The IC memo evidence selection pipeline calls Cohere to rerank candidate chunks.

**Changes:**
- Replace Cohere rerank call with `local_reranker.rerank()`
- Update score thresholds — cross-encoder sigmoid scores differ from Cohere scores
- Verify IC memo quality is maintained (same chapters, similar evidence selection)

**Acceptance criteria:**
- [ ] No Cohere API calls remain anywhere in the codebase
- [ ] `cohere_rerank.py` can be deleted
- [ ] IC memo pipeline produces comparable evidence selection
- [ ] No `httpx` calls to `netzai.services.ai.azure.com` Cohere endpoint

##### Task 1.7: Delete `cohere_rerank.py` and Update Dependencies

- Delete `backend/ai_engine/extraction/cohere_rerank.py`
- Verify no remaining imports (import graph: only `document_intelligence.py` imported it, updated in Task 1.5)
- Remove Cohere Azure endpoint from environment config if present
- Add `sentence-transformers>=3.0` to `[ai]` optional deps in `pyproject.toml`

**Acceptance criteria:**
- [ ] `cohere_rerank.py` deleted
- [ ] No broken imports
- [ ] `make check` passes

---

#### Phase 2: Ingestion Path Unification

**Goal:** Single pipeline for all sources. Delete monolith. Difference between UI/batch is priority and feedback, not analytical quality.

##### Task 2.0: PREREQUISITE — Diff Analysis of prepare_pdfs_full.py

**This task MUST complete before any deletion in Phase 2** (see brainstorm: Phase 2 prerequisite).

Compare `prepare_pdfs_full.py` (1786 LOC) line-by-line against modular components:

| prepare_pdfs_full.py section | Modular equivalent | Status |
|---|---|---|
| `DOC_TYPE_CANDIDATES` (lines 114-300) | `cohere_rerank.py` (deleted by Phase 1) → absorbed into `hybrid_classifier.py` Layer 2 | Verify descriptions migrated |
| `VEHICLE_TYPE_CANDIDATES` | Same as above | Verify |
| `filename_hint()` (line 652+) | `hybrid_classifier.py` Layer 1 | Verify rules ported |
| Governance patterns (lines 441-476) | `governance_detector.py` | Verify patterns match |
| Semantic chunking orchestration | `semantic_chunker.py` | Verify |
| Mistral OCR window logic | `mistral_ocr.py` | Verify |
| `is_skippable()` / skip patterns | `skip_filter.py` | Verify |
| Global mutable state (`_CONTEXT_DEAL_NAME`, `_FUND_ALIASES`) | Entity bootstrap logic in `extraction_orchestrator.py` | **UNIQUE — document where this goes** |
| `process_folder()` orchestration | Will become `unified_pipeline.py` | N/A |

**Output:** Document findings in `docs/solutions/prepare-pdfs-full-diff-analysis.md`

**Acceptance criteria:**
- [ ] Every section of `prepare_pdfs_full.py` mapped to a modular equivalent or documented as unique
- [ ] Any unique logic identified and a plan for where it moves
- [ ] Document saved in `docs/solutions/`
- [ ] **Blocks all subsequent Phase 2 tasks**

##### Task 2.1: Unified Pipeline Orchestrator (`ai_engine/pipeline/unified_pipeline.py`)

Single async pipeline that processes one document at a time, source-agnostic.

```python
# Public API
async def process(request: IngestRequest) -> PipelineStageResult:
    """Process a single document through the full pipeline.

    Stages: OCR → [gate] → Classify → [gate] → Chunk → [gate]
            → Extract → [gate] → Embed → [gate] → Write

    Returns final PipelineStageResult with aggregated metrics.
    """
```

**Pipeline stages (sequential, each gated):**

1. **Pre-filter** — `skip_filter.is_skippable(filename)` → skip W-8BEN, W-9, FATCA before OCR
2. **OCR** — `mistral_ocr.async_extract(blob_uri)` → raw text + pages
3. **Gate: validate_ocr_output()** → reject if < 100 chars or > 30% non-printable
4. **Classify** — `hybrid_classifier.classify(text, filename)` → doc_type + vehicle_type
5. **Gate: validate_classification()** → reject if doc_type not in canonical set
6. **Governance** — `governance_detector.detect_governance(text)` → flags (pure regex, always runs)
7. **Chunk** — `semantic_chunker.chunk_document(text, doc_type)` → chunks with breadcrumbs
8. **Gate: validate_chunks()** → reject if content retention < 90%
9. **Extract** — `document_intelligence.async_extract_metadata()` + `async_summarize_document()` in parallel
10. **Gate: validate_extraction()** → reject if metadata schema invalid
11. **Embed** — `embed_chunks.async_embed(chunks)` → vectors
12. **Gate: validate_embeddings()** → reject if dimension mismatch or NaN
13. **Write** — StorageClient (Phase 3) or current storage (Phase 2)
14. **Index** — Azure Search upsert

**SSE events emitted at each stage (if `request.version_id` is set):**
- `processing` (stage start)
- `ocr_complete`
- `classification_complete` (new event — UI ignores unknown events safely)
- `chunking_complete`
- `extraction_complete` (new)
- `indexing_complete`
- `ingestion_complete` (terminal)
- `error` (terminal, on any gate failure)

SSE failures are swallowed — log and continue (from learnings: Pattern E).

**Audit trail (DISCOVERED BY REVIEW — ingestion_worker.py writes audit events at every stage):**
- Call `write_audit_event()` after each validation gate with `PipelineStageResult.metrics` as the `after` payload
- Events: `DOCUMENT_OCR_COMPLETE`, `DOCUMENT_CLASSIFIED`, `DOCUMENT_CHUNKED`, `DOCUMENT_EXTRACTED`, `DOCUMENT_CHUNKS_INDEXED`, `INGESTION_FAILED`
- This preserves the existing audit trail contract when `ingestion_worker.py` is deleted
- Persist final aggregated `PipelineStageResult` as JSON on `DocumentVersion` for pipeline observability

**Concurrency safety:**
- Pipeline processes ONE document at a time (no shared session)
- Callers (UI route, batch wrapper) manage concurrency externally
- UI route: `asyncio.Semaphore(3)` for bounded parallelism
- Batch wrapper: `asyncio.Semaphore(8)` + `asyncio.gather()` (NOT `ThreadPoolExecutor` — async pipeline can't run in thread pool). See batch helper below.

```python
# Batch helper in extraction_orchestrator.py (replaces ThreadPoolExecutor)
async def process_batch(requests: list[IngestRequest], max_concurrent: int = 8) -> list[PipelineStageResult]:
    sem = asyncio.Semaphore(max_concurrent)
    async def _bounded(req: IngestRequest) -> PipelineStageResult:
        async with sem:
            return await process(req)
    return await asyncio.gather(*[_bounded(r) for r in requests])
```

**Same-document concurrency guard:**
- Check `document_versions.ingestion_status = PROCESSING` before starting
- If already processing, skip with WARNING (not error)
- Batch path must apply the same guard as UI path

**Acceptance criteria:**
- [ ] `unified_pipeline.py` with `process(IngestRequest) -> PipelineStageResult`
- [ ] All 7 validation gates wired between stages (3 critical: OCR, content retention, chunk count)
- [ ] `write_audit_event()` after each gate (preserves audit trail from ingestion_worker.py)
- [ ] Final `PipelineStageResult` persisted as JSON on `DocumentVersion`
- [ ] SSE events emitted for UI-sourced requests
- [ ] Governance detection runs on every document (pure regex, zero cost)
- [ ] Async-first: all external calls use `httpx.AsyncClient` or `asyncio.to_thread()`
- [ ] No shared mutable state between documents
- [ ] Same-document concurrency guard (check ingestion_status before processing)

##### Task 2.2: Update UI Ingestion Route

Replace `ingestion_worker.process_pending_versions()` call with `unified_pipeline.process()`.

**File:** `app/domains/credit/documents/routes/ingest.py`

**Changes:**
- Import `unified_pipeline.process` and `IngestRequest`
- Build `IngestRequest(source="ui", version_id=version.id, ...)` from route context
- Call `await unified_pipeline.process(request)`
- Remove import of `ingestion_worker`

**SSE contract:** The existing terminal events (`ingestion_complete`, `error`) are preserved. New intermediate events (`classification_complete`, `extraction_complete`) are additive — SvelteKit ignores unknown event types.

**Acceptance criteria:**
- [ ] UI upload route calls `unified_pipeline.process()`
- [ ] SSE events flow correctly (test with SvelteKit frontend)
- [ ] `ingestion_worker.py` has no remaining callers

##### Task 2.3: Update Pipeline Ingest Runner

Replace `domain_ingest_orchestrator.run_ingest_for_unindexed_documents()` and `async_run_ingest_for_unindexed_documents()` with calls to `unified_pipeline.process()`.

**Files:**
- `ai_engine/ingestion/pipeline_ingest_runner.py` (lines 248, 544)
- `ai_engine/ingestion/ingest_runner.py` (line 34)
- `app/domains/credit/modules/ai/extraction.py` (line 300 — `reanalyze_deal`)

**Changes:**
- Fetch unindexed documents from DB (same query)
- Build `IngestRequest(source="batch", ...)` per document
- Call `unified_pipeline.process()` per document with bounded concurrency

**AI analysis trigger (DISCOVERED BY REVIEW + USER CORRECTION):** `domain_ingest_orchestrator.py` lines 354-388 triggers `run_deal_ai_analysis()` after all documents in a batch are ingested, grouped per deal. The unified pipeline processes one document at a time.

**Race condition risk:** With `asyncio.Semaphore(8)` processing 20 documents from a deal, documents finish at different times. The runner cannot know "all documents for this deal are done" by collecting results inline — some documents may still be in-flight when early ones complete.

**Solution: Deferred AI analysis trigger via polling, NOT inline.**
- `pipeline_ingest_runner.py` processes all documents via the unified pipeline
- After ALL `asyncio.gather()` results return, group by deal_id and trigger AI analysis per deal
- The `gather()` call naturally waits for all tasks — the trigger runs AFTER the entire batch completes, not after individual documents
- Alternative for UI path: trigger AI analysis as a separate async job when `ingestion_status = INDEXED` for all documents in a deal (query-based check, not inline)

**Acceptance criteria:**
- [ ] `pipeline_ingest_runner.py` calls `unified_pipeline.process()` for each document via `asyncio.gather()`
- [ ] AI analysis triggered AFTER `gather()` returns (all documents complete), NOT inline per document
- [ ] Results grouped by deal_id → `run_deal_ai_analysis()` per deal
- [ ] UI path: AI analysis trigger via deferred job (poll `ingestion_status = INDEXED` for all deal docs)
- [ ] `reanalyze_deal` uses unified pipeline
- [ ] `domain_ingest_orchestrator.py` has no remaining callers

##### Task 2.4: Slim extraction_orchestrator.py to Thin Wrapper

Keep infrastructure concerns, delegate processing to unified pipeline (see brainstorm: Decision 6).

**Keeps:**
- `SOURCE_CONFIG` dict (container names, indexer names)
- `get_blob_service()` — Azure Blob client factory
- `list_source_folders()` — blob listing
- Blob download to tmpdir
- Entity bootstrap (`_CONTEXT_DEAL_NAME`, `_FUND_ALIASES` — from Task 2.0 diff analysis)
- `ThreadPoolExecutor` for batch parallelism
- Indexer trigger (post-processing)
- `_JOBS` in-memory store, `run_extraction_pipeline()`, `get_job_status()`, `list_pipeline_jobs()`

**Removes:**
- `process_folder()` call → replaced by loop over `unified_pipeline.process()`
- Import of `prepare_pdfs_full`

**Target: ~150 LOC** (from ~650 LOC)

**Callers (update simultaneously):**
- `worker_app/function_app.py` (line 82) — API unchanged, internal behavior changes
- `app/services/azure/pipeline_dispatch.py` (line 130) — API unchanged
- `app/domains/credit/modules/ai/extraction.py` (lines 92-143) — API unchanged

**Acceptance criteria:**
- [ ] `extraction_orchestrator.py` reduced to ~150 LOC
- [ ] No import of `prepare_pdfs_full`
- [ ] `run_extraction_pipeline()` API unchanged (callers don't need updating)
- [ ] Processing logic delegated to `unified_pipeline.process()` per document

##### Task 2.5: Delete Legacy Files

Only after Tasks 2.1-2.4 complete and all callers are updated.

**Delete:**
- `ai_engine/extraction/prepare_pdfs_full.py` (1786 LOC) — **Phase 2 completion signal**
- `ai_engine/ingestion/domain_ingest_orchestrator.py` (825 LOC)
- `app/domains/credit/documents/services/ingestion_worker.py` (254 LOC)
- `ai_engine/classification/document_classifier.py` (~200 LOC) — legacy 7-type keyword classifier
- `ai_engine/classification/classifier.py` (~40 LOC) — delegation wrapper
- `ai_engine/classification/doc_classifier.py` (~40 LOC) — delegation wrapper

**Pre-deletion checklist:**
- [ ] `make check` passes with unified pipeline
- [ ] No remaining imports to any of these files (verified via grep)
- [ ] Diff analysis (Task 2.0) confirmed no unique logic lost

**Callers requiring update (DISCOVERED BY REVIEW):**
- `ai_engine/ingestion/document_scanner.py` (imports `classify_registered_documents` from `doc_classifier.py`) → migrate to `hybrid_classifier.classify()`
- `ai_engine/ingestion/monitoring.py` (imports `classify_documents` from `classifier.py`) → migrate
- `app/domains/credit/modules/ai/documents.py` (imports `classify_documents` from `classifier.py`) → migrate
- `tests/test_upload_architecture.py` (imports `ingestion_worker`) → update to test unified pipeline
- `ai_engine/classification/__init__.py` → update to re-export `hybrid_classifier` public API

**Acceptance criteria:**
- [ ] All 6 legacy files deleted
- [ ] All 4 hidden callers migrated to hybrid_classifier
- [ ] Test file updated
- [ ] `classification/__init__.py` updated
- [ ] `make check` passes
- [ ] Zero broken imports across entire codebase (verified via grep)

---

#### Phase 3: StorageClient + Bronze/Silver/Gold + Dual-Write

**Goal:** Migrate from direct Azure Blob SDK to StorageClient abstraction. ADLS becomes source of truth, Azure Search becomes derived index (see brainstorm: Decisions 5, 7).

##### Task 3.1: Path Routing Module (`ai_engine/pipeline/storage_routing.py`)

Implements the ADLS path hierarchy with vertical routing (see brainstorm: Decision 5).

```python
def bronze_document_path(org_id: UUID, vertical: str, doc_id: str) -> str:
    """bronze/{org_id}/{vertical}/documents/{doc_id}"""

def silver_chunks_path(org_id: UUID, vertical: str, doc_id: str) -> str:
    """silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet"""

def silver_metadata_path(org_id: UUID, vertical: str, doc_id: str) -> str:
    """silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json"""

def gold_memo_path(org_id: UUID, vertical: str, memo_id: str) -> str:
    """gold/{org_id}/{vertical}/memos/{memo_id}.json"""
```

**Rule:** Vertical comes from `IngestRequest.vertical` (request context), NOT from classification (see brainstorm: Decision 5 routing rule).

**`_global/` paths** for reference data (FRED, Yahoo, benchmarks) — no `org_id`, no vertical. Client documents NEVER go to `_global/`.

**Acceptance criteria:**
- [ ] Path routing functions with `{org_id}/{vertical}/` prefix
- [ ] Path traversal validation (leverages existing StorageClient protection)
- [ ] `_global/` path builder for reference data

##### Task 3.2: Integrate StorageClient into Unified Pipeline

Add `StorageClient.write()` calls to `unified_pipeline.py` at each stage output.

**Stage → Storage mapping:**

| Stage output | ADLS path | Format |
|---|---|---|
| OCR raw text | `bronze/{org_id}/{vertical}/documents/{doc_id}.json` | JSON |
| Chunks + embeddings | `silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet` | Parquet |
| Extracted metadata | `silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json` | JSON |
| IC memo (later) | `gold/{org_id}/{vertical}/memos/{memo_id}.json` | JSON |

**Dual-write pattern:**
1. Write to ADLS (StorageClient) first — source of truth
2. Upsert to Azure AI Search — derived index
3. If ADLS write succeeds but Search upsert fails → log warning, document is still safe in ADLS

**Feature flag:** Gated by `FEATURE_ADLS_ENABLED` (default: false). When false, `LocalStorageClient` writes to filesystem (local dev). ADLS paths only materialize in staging/production.

**Acceptance criteria:**
- [ ] Pipeline writes OCR output to bronze, chunks to silver, metadata to silver
- [ ] ADLS write happens BEFORE Azure Search upsert
- [ ] Uses `StorageClient` abstraction (not direct Azure SDK)
- [ ] Feature-flagged via `FEATURE_ADLS_ENABLED`

##### Task 3.3: Search Rebuild Service

New capability: reconstruct Azure AI Search index from silver layer without reprocessing PDFs (see brainstorm: Decision 7 consequence).

```python
async def rebuild_search_index(
    org_id: UUID,
    vertical: str,
    *,
    doc_ids: list[UUID] | None = None,  # None = rebuild all
) -> RebuildResult:
    """Rebuild Azure Search from silver layer chunks."""
```

- Read `chunks.parquet` from silver layer via StorageClient
- Upsert each chunk + embedding to Azure AI Search
- No OCR, no classification, no LLM calls — purely data movement
- Useful for: schema changes, embedding model upgrades, index corruption recovery

**Parquet schema for silver layer chunks (must include embedding metadata):**
- `embedding_model: str` — e.g., "text-embedding-3-large"
- `embedding_dim: int` — e.g., 3072
- `embedding: FixedSizeListArray(float32, dim)` — dimension enforced by array type
- If embedding model changes, old Parquet files become incompatible. Rebuild service MUST reject files where `embedding_dim != current_model_dim` and log a clear error.

**Acceptance criteria:**
- [ ] Can rebuild full org's search index from silver layer
- [ ] Can rebuild specific documents (by doc_id list)
- [ ] **Rejects Parquet files with `embedding_dim != current_model_dim`** (prevents silent data corruption on model change)
- [ ] No LLM or OCR calls during rebuild
- [ ] Works with both `LocalStorageClient` and `ADLSStorageClient`

##### Task 3.4: Migrate Existing Blob Paths (Deferred)

Existing blobs in `investment-pipeline-intelligence`, `fund-data`, `market-data` containers are NOT migrated. The migration strategy:

1. **New documents** go through unified pipeline → written to bronze/silver/gold paths
2. **Existing documents** remain in legacy containers → accessible via `extraction_orchestrator.py` (which keeps `SOURCE_CONFIG`)
3. **Gradual migration:** as documents are re-ingested (triggered by any update), they get written to the new path hierarchy
4. **Full migration** (optional, future): batch job reads all legacy blobs, runs through unified pipeline

**No acceptance criteria for this task — it's a documented decision, not Phase 3 code.**

---

## System-Wide Impact

### Interaction Graph

```
UI Upload → POST /documents/ingestion/process-pending
  → unified_pipeline.process(IngestRequest(source="ui"))
    → mistral_ocr.async_extract()         [external API: Mistral]
    → hybrid_classifier.classify()         [local sklearn + optional LLM API]
    → governance_detector.detect()         [local regex]
    → semantic_chunker.chunk_document()    [local Python]
    → document_intelligence.async_extract_metadata()  [external API: OpenAI]
    → document_intelligence.async_summarize_document() [external API: OpenAI]
    → embed_chunks.async_embed()           [external API: OpenAI]
    → StorageClient.write()                [ADLS or local filesystem]
    → search_upsert_service.upsert()       [Azure AI Search]
    → Redis pub/sub SSE event              [Redis]
```

### Error & Failure Propagation

- Validation gate failure → `PipelineStageResult(success=False, errors=[...])` → document marked FAILED → SSE `error` event → pipeline halts for this document only
- External API failure (Mistral, OpenAI) → caught by stage, wrapped in `PipelineStageResult` error → same failure path
- StorageClient failure → ADLS write fails → document NOT upserted to Search (dual-write order guarantees consistency)
- Redis/SSE failure → swallowed, logged → does NOT break ingestion (from learnings: Pattern E)

### State Lifecycle Risks

- **Partial pipeline completion:** if document passes OCR but fails at chunking, OCR output is already written to bronze. No orphan cleanup needed — bronze is append-only raw data.
- **No stage checkpointing in Phase 1-2:** pipeline is all-or-nothing per document. Resumption requires re-running the full pipeline. Acceptable given per-document processing time (~30-60s).
- **Concurrent same-document processing:** mitigated by `document_versions.ingestion_status = PROCESSING` check in the UI path. Batch path should add similar guard.

### API Surface Parity

| Interface | Change |
|---|---|
| `extraction_orchestrator.run_extraction_pipeline()` | API preserved, internal behavior changes |
| `extraction_orchestrator.get_job_status()` | Unchanged |
| `POST /documents/ingestion/process-pending` | Unchanged (calls unified pipeline internally) |
| SSE event stream | Additive (new intermediate events, terminal events preserved) |
| `document_intelligence.async_run_full_intelligence()` | Internal change (uses hybrid classifier, same output schema) |

## Security Requirements (from Security Sentinel audit)

| ID | Finding | Severity | Remediation | Phase |
|---|---|---|---|---|
| F1 | SSE job stream lacks tenant authorization | HIGH | Add tenant ownership check before creating SSE stream (query DocumentVersion where id=job_id, verify org_id matches actor) | Pre-Phase 2 |
| F2 | IngestRequest org_id trusting caller input | HIGH | `org_id` MUST come from `actor.organization_id` (JWT). IngestRequest docstring + factory methods enforce this. | Phase 1 (Task 1.1) |
| F3 | Prompt injection in Layer 3 LLM classification | MEDIUM | Three-layer architecture is itself strong mitigation (Layer 3 fires for ~5% of docs). Add post-classification governance override if Layer 3 returns `governance_critical=false` but filename indicates governance-sensitive type. | Phase 1 (Task 1.2) |
| F4 | Azure Search index missing organization_id | MEDIUM | Add `organization_id` as filterable field in search schema. All queries must include org_id filter. | Phase 3 |
| F5 | Cross-encoder model from mutable cache | LOW | Pin to commit hash: `CrossEncoder("...", revision="<sha>")`. Bundle model in container image for production. | Phase 1 (Task 1.3) |
| F6 | Vertical path segment not validated | LOW | Validate `vertical in {"credit", "wealth"}` in `IngestRequest.__post_init__()`. Apply `_SAFE_PATH_SEGMENT_RE` in storage routing. | Phase 1 (Task 1.1) |

## Acceptance Criteria

### Functional Requirements

- [ ] **Phase 1:** Hybrid classifier produces doc_type + vehicle_type without any Cohere API calls
- [ ] **Phase 1:** Cross-encoder reranks chunks for IC memo evidence without any Cohere API calls
- [ ] **Phase 1:** Validation gates catch content loss > 10% between chunking and extraction
- [ ] **Phase 2:** UI-uploaded documents receive same analytical quality as batch-ingested documents
- [ ] **Phase 2:** `prepare_pdfs_full.py` deleted
- [ ] **Phase 3:** Pipeline writes to ADLS bronze/silver/gold via StorageClient
- [ ] **Phase 3:** Azure Search index can be rebuilt from silver layer

### Non-Functional Requirements

- [ ] Zero Cohere API dependency (eliminated end of Phase 1)
- [ ] Classification latency: < 500ms for Layer 1+2, < 3s for Layer 3 (LLM)
- [ ] Cross-encoder rerank latency: < 5s for 80 chunks (via `asyncio.to_thread()`)
- [ ] No event loop blocking — all sync operations wrapped in `asyncio.to_thread()`
- [ ] SSE events preserved for UI upload path

### Quality Gates

- [ ] `make check` passes after each phase
- [ ] No broken imports (verified via grep before merging)
- [ ] Functional validation on 3 real documents (per brainstorm risk notes)
- [ ] IC memo evidence quality spot-checked after cross-encoder switch

## Dependencies & Prerequisites

| Dependency | Status | Phase |
|---|---|---|
| `scikit-learn>=1.6` | Already in `[quant]` deps | 1 |
| `sentence-transformers>=3.0` | **New** — add to `[ai]` deps | 1 |
| StorageClient (`storage_client.py`) | Exists, 289 LOC, 7 methods | 3 |
| `FEATURE_ADLS_ENABLED` env var | Exists, default false | 3 |
| `skip_filter.py` | Exists | 2 |
| `governance_detector.py` | Exists, pure regex | 2 |
| `semantic_chunker.py` | Exists, 626 LOC pure Python | 2 |
| `mistral_ocr.py` | Exists, async | 2 |

## Risk Analysis & Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| sklearn nearest-centroid underperforms on close classes | Misclassification of financial doc subtypes | Rejection threshold (ratio < 1.3) escalates to LLM. Functional validation on 3 docs before merge. |
| Cross-encoder score scale differs from Cohere | IC memo evidence selection changes | Update downstream thresholds. Spot-check memo quality. |
| `prepare_pdfs_full.py` has unique logic not in modular components | Loss of functionality | Task 2.0 diff analysis is a hard blocker. No deletion without documented confirmation. |
| Phase 2 breaks batch workflows | Production batch jobs fail silently | `extraction_orchestrator.py` public API preserved. Callers don't need updating. |
| Event loop blocking from cross-encoder inference | API latency spikes | `asyncio.to_thread()` mandatory. Lazy model loading. |
| Existing Azure Search documents have incompatible schema | Old documents invisible to RAG | Phase 3 search rebuild capability. Gradual re-ingestion. |

## Alternative Approaches Considered

See [brainstorm](docs/brainstorms/2026-03-15-pipeline-llm-deterministic-alignment-brainstorm.md): Resolved Questions 1-6.

Key rejections:
- **Cross-encoder for classification** → Rejected. Ranking model for a classification problem is a hack (brainstorm: Decision 2).
- **A/B testing against Cohere** → Rejected. No ground truth exists — Cohere also misclassified silently (brainstorm: Risk Notes).
- **Absorb extraction_orchestrator.py into unified pipeline** → Rejected. Infrastructure concerns (blob download, indexer trigger) don't belong in the document processing pipeline (brainstorm: Decision 6).
- **ADLS replaces Azure Search** → Rejected. DuckDB can't do ANN vector search for RAG. Different tools for different problems (brainstorm: Decision 7).

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-15-pipeline-llm-deterministic-alignment-brainstorm.md](docs/brainstorms/2026-03-15-pipeline-llm-deterministic-alignment-brainstorm.md) — Key decisions carried forward: hybrid classifier (D1), cross-encoder for reranking only (D2), validation gates (D3), unified ingestion (D4), ADLS vertical routing (D5), extraction_orchestrator as thin wrapper (D6), ADLS source of truth (D7)

### Internal References

- `backend/ai_engine/extraction/cohere_rerank.py` — 31 DOC_TYPE_CANDIDATES (reused as Layer 2 synthetic exemplars)
- `backend/ai_engine/extraction/prepare_pdfs_full.py` — richer candidate descriptions (preferred over cohere_rerank.py versions)
- `backend/app/services/storage_client.py` — StorageClient abstraction (7 async methods, Local + ADLS backends)
- `backend/ai_engine/model_config.py` — model routing table
- `docs/solutions/architecture-patterns/vertical-engine-extraction-patterns.md` — StorageClient path validation, asyncio.to_thread() pattern, SSE resilience

### Institutional Learnings Applied

- **Pattern D (asyncio.to_thread):** Cross-encoder and sklearn inference wrapped in `asyncio.to_thread()` to prevent event loop blocking
- **Pattern E (SSE resilience):** Redis pub/sub failures swallowed — does not break ingestion
- **Path traversal protection:** StorageClient validates paths at both base class and implementation layer
- **RLS subselect:** Any tenant-scoped queries use `(SELECT current_setting(...))` not bare function call
- **No module-level asyncio primitives:** sklearn model and cross-encoder loaded lazily inside async functions
- **Thread-unsafe rate limiter pattern:** CrossEncoder inference serialized with `asyncio.Lock` (from `thread-unsafe-rate-limiter-FredService` learning)
- **Monolith-to-modular pattern:** `prepare_pdfs_full.py` decomposition follows `monolith-to-modular-package-with-library-migration` pattern — non-fatal design where each sub-operation is independently wrapped

### Research Insights Applied (from 8-agent deepening)

**Best Practices:**
- Layer 2 uses direct `cosine_similarity` instead of `NearestCentroid` — simpler, more transparent, avoids L2 normalization gotcha where NearestCentroid computes arithmetic mean centroids inappropriate for cosine space
- `TfidfVectorizer` configured with `sublinear_tf=True` (dampens high-frequency terms) and `ngram_range=(1,2)` (bigrams capture "credit agreement" vs "side letter")
- Cross-encoder scores normalized via numerically stable sigmoid (not `apply_softmax` which returns 1.0 for single-label models)
- Dual-write uses idempotent `merge_or_upload` in Azure Search — retries and rebuilds are safe

**Performance:**
- Batch throughput improved 5-8x by replacing `ThreadPoolExecutor` with `asyncio.Semaphore(8)` + `asyncio.gather()` — async pipeline can't run in thread pool
- ADLS + Search writes can be parallelized with `asyncio.gather()` while maintaining ADLS-first consistency (check ADLS success even if both run concurrently)
- sklearn TF-IDF fit on 31 descriptions: <5ms. Per-document transform + cosine: <1ms. Validation gates total: <1ms. Pipeline latency dominated by external API calls (Mistral OCR, OpenAI).

**Security:**
- IngestRequest.org_id must be JWT-derived, never from request body
- SSE endpoint needs tenant authorization before Phase 2 adds more event types
- Cross-encoder model pinned to commit hash in production

**Parquet (Phase 3):**
- Use `pyarrow` with `FixedSizeListArray` for embeddings (better compression, DuckDB compatibility)
- Use `pa.BufferOutputStream` for in-memory serialization — no temp files needed
- Compression: `zstd` for best size/speed tradeoff on float arrays
