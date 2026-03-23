# Pipeline LLM-Deterministic Alignment Brainstorm

**Date:** 2026-03-15
**Status:** Draft
**Scope:** Extraction/classification pipeline refactor — LLM vs Python deterministic tooling, ingestion path unification, ADLS alignment

---

## What We're Building

A three-phase refactor of the document processing pipeline that:

1. Replaces unnecessary LLM calls with deterministic Python where equivalent quality is achievable
2. Unifies the two divergent ingestion paths (batch vs UI) into a single pipeline
3. Migrates storage from direct Azure Blob SDK to StorageClient with bronze/silver/gold hierarchy

The goal is **robustness and cost-efficiency** without sacrificing the semantic extraction and IC memo generation that define the product's value.

---

## Why This Approach

### The Problem

The pipeline inherited from Private Credit OS has five structural issues:

1. **LLM overuse** — Classification uses gpt-4.1-mini for 31 doc_types where 80%+ are deterministically classifiable. Cohere Rerank was repurposed for classification (a ranking tool solving a classification problem). Cost and latency are unnecessarily high.

2. **Ingestion quality gap** — Two completely separate pipelines exist:
   - **Batch** (`domain_ingest_orchestrator.py`): Mistral OCR → Cohere classification → governance regex → LLM extraction → semantic chunking → embedding (full quality)
   - **UI upload** (`ingestion_worker.py`): pypdf text extraction → page-boundary chunking → Azure Search upsert (no LLM classification, no semantic chunking, no governance detection)
   - Institutional clients get different analytical quality depending on *how* a document entered the system. Unacceptable for a commercial product.

3. **No inter-stage validation** — Each pipeline stage passes output to the next without quality gates. The 60% content loss bug from `semantic_chunker` was exactly this: Mistral OCR produced output the chunker didn't handle, and nothing detected the anomaly before it propagated through the entire chain.

4. **StorageClient bypass** — Both pipelines use Azure Blob SDK directly instead of the `StorageClient` abstraction mandated by CLAUDE.md. No bronze/silver/gold hierarchy, no `{org_id}` path isolation.

5. **Monolith duplication** — `prepare_pdfs_full.py` (1750+ lines) duplicates logic from `cohere_rerank.py`, `governance_detector.py`, and `semantic_chunker.py`. Bug fixes in the modular components don't propagate to this file.

### What Already Works (Do Not Touch)

| Component | Why it stays |
|---|---|
| Mistral OCR | No Python alternative for scanned financial PDFs with complex tables |
| LLM metadata extraction (gpt-4.1) | Structured extraction of fund-of-funds patterns, Side Letter structures, covenant language — the product's core IP |
| LLM summarization (gpt-4.1-mini) | Product depends on document summaries |
| `semantic_chunker.py` | Already pure Python, 626 lines, well-structured with adaptive sizing per doc_type |
| `governance_detector.py` | Already pure regex (15 patterns, 6 critical). Zero API cost |
| Embedding (text-embedding-3) | Commodity API, deterministic |
| IC memo deep review pipeline | The product itself. Not a candidate for substitution |

---

## Key Decisions

### Decision 1: Hybrid Classifier Replaces LLM + Cohere for Classification

**Problem being solved:** Classification (doc_type + vehicle_type) currently uses Cohere Rerank (a ranking model repurposed for classification) with LLM fallback. This is the wrong tool for the problem.

**Architecture:**

```
Layer 1: Deterministic rules (filename + first 500 chars)
├── 14 filename patterns already exist in cohere_rerank.py
├── Expand to ~40 rules covering all canonical doc_types
├── Covers ~80% of documents with 100% confidence
└── Returns immediately, zero cost

Layer 2: sklearn nearest-centroid classifier (TfidfVectorizer + NearestCentroid)
├── Each of the 31 canonical doc_types has a rich ~150-token description in cohere_rerank.py
├── These descriptions serve as synthetic exemplars: TF-IDF vectorize each description → class centroid
├── Incoming document text (first 2000 chars) is vectorized and matched to nearest centroid
├── Confidence = distance ratio between top-1 and top-2 centroids
│   ├── Known weakness: financial docs with shared specialized vocabulary across close classes
│   │   (e.g., "credit agreement" vs "loan agreement" vs "facility agreement") produce
│   │   close centroids, making rejection boundary hard to calibrate
│   ├── Rejection threshold: ratio < 1.3 → reject to Layer 3 (LLM)
│   └── On rejection: escalate directly to Layer 3. NO retry with different parameters.
├── Covers ~15% of remaining documents (clear vocabulary match, not ambiguous enough for LLM)
└── Local inference, zero API cost, no training loop — centroids computed once at startup

Layer 3: LLM fallback (gpt-4.1-mini) — only for the ~5% genuinely ambiguous cases
├── "Is this a due diligence report or a credit analysis?"
├── Uses existing Jinja2 templates from document_intelligence.py
└── JSON mode output: {doc_type, sub_type, confidence, reasoning}
```

**vehicle_type (6 classes):** Same hybrid pattern. Layer 1 rules cover 90%+ of cases — vehicle_type is trivial compared to doc_type.

**Result:** Cohere API dependency for classification is eliminated naturally, not by substitution. The hybrid classifier is purpose-built for classification, unlike the repurposed ranking model.

### Decision 2: Cross-Encoder for RAG Reranking Only

**Critical distinction:** Classification and reranking are different problems requiring different tools.

| Problem | Correct tool |
|---|---|
| doc_type (31 classes) | Hybrid classifier (Decision 1) — NOT a ranking problem |
| vehicle_type (6 classes) | Hybrid classifier Layer 1 — trivial |
| RAG chunk relevance for IC memo | Cross-encoder `ms-marco-MiniLM-L-6-v2` — this IS a ranking problem |

**Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` via `sentence-transformers`
- 22MB, runs on CPU
- Zero cost per request, zero external dependency
- Trained for query-document relevance (exactly the IC memo evidence use case)

**What it replaces:** Cohere Rerank API for chunk reranking in the RAG pipeline (evidence selection for IC memo chapters).

**What it does NOT replace:** Classification. Using a ranking model for multi-label classification would be a hack that underperforms on ambiguous boundary cases — exactly where accuracy matters most.

**Combined result of Decisions 1 + 2:** Cohere is completely eliminated from the pipeline — classification by the hybrid classifier, reranking by the cross-encoder. For correct reasons, not shortcuts.

### Decision 3: Inter-Stage Validation Gates as First-Class Pipeline Citizens

Every stage transition gets a typed validation gate:

```python
@dataclass(frozen=True)
class PipelineStageResult:
    stage: str                    # "ocr", "classification", "chunking", etc.
    success: bool
    data: Any                     # Stage output
    metrics: dict                 # char_count, chunk_count, confidence, etc.
    warnings: list[str]           # Non-fatal issues
    errors: list[str]             # Fatal issues (pipeline halts)

# Validation rules per transition:
# OCR → Classification:
#   - text length > 100 chars (reject empty/corrupt extractions)
#   - no more than 30% non-printable characters
#
# Classification → Chunking:
#   - doc_type is in CANONICAL_DOC_TYPES
#   - confidence > threshold (configurable per layer)
#
# Chunking → Extraction:
#   - chunk_count > 0
#   - total chars across chunks within 10% of input chars (detect content loss)
#   - no chunk exceeds max_chunk_size
#
# Extraction → Embedding:
#   - metadata JSON validates against schema
#   - embedding input text is non-empty for each chunk
```

**This is the architectural change that prevents the 60% content loss class of bugs.** The chunker bug was silent because nothing checked `sum(chunk_lengths) / input_length`.

### Decision 4: Unified Ingestion Pipeline

One pipeline for all document sources. Source determines queue priority and feedback mechanism, NOT analytical quality.

```python
@dataclass
class IngestRequest:
    source: Literal["ui", "batch", "api"]
    org_id: UUID
    vertical: str           # "credit" | "wealth" — from request context
    document_id: UUID
    blob_uri: str
    priority: int           # ui=high, batch=normal, api=configurable

# Unified pipeline (identical for all sources):
# OCR (Mistral)
#   → [validation gate]
# Hybrid classifier (Layer 1 → Layer 2 → Layer 3)
#   → [validation gate]
# Semantic chunker (Python)
#   → [validation gate]
# LLM metadata extraction (gpt-4.1)
#   → [validation gate]
# Embedding + index
#   → [validation gate]
# StorageClient write (bronze → silver)
```

**Source-specific behavior (NOT quality):**
- `ui`: SSE feedback events via Redis pub/sub, high priority queue
- `batch`: Progress tracking in job table, normal priority
- `api`: Webhook callback on completion, configurable priority

**Acceptance criterion for Phase 2 completion:** `prepare_pdfs_full.py` is deleted. While it exists, the system has two sources of truth and bug fixes don't propagate.

### Decision 5: ADLS Path Hierarchy with Vertical Routing

**Rule:** The vertical is always known at ingestion time because it comes from the request context, NOT from document classification. A document enters the pipeline because it was submitted in the context of a credit deal — it goes to `credit/`.

**Path structure:**

```
bronze/
├── {org_id}/
│   ├── credit/
│   │   └── documents/{year}/{month}/{day}/{doc_id}.pdf + .json
│   └── wealth/
│       └── nav/{fund_id}/{year}/{month}.parquet
└── _global/
    ├── fred/{year}/{month}.parquet
    └── yahoo/{year}/{month}/{day}/batch.parquet

silver/
├── {org_id}/
│   ├── credit/
│   │   └── chunks/{document_id}/chunks.parquet
│   └── wealth/
│       └── fund_metrics/{fund_id}/{year}-{month}.parquet
└── _global/
    └── fred_clean/{year}.parquet

gold/
├── {org_id}/
│   ├── credit/
│   │   └── memos/{memo_id}.json
│   └── wealth/
│       └── portfolios/{profile}/{date}.parquet
└── _global/
    └── analysis_patterns/{vertical}/{year}/{month}.parquet
```

**Routing function:**

```python
def route_document(org_id: UUID, vertical: str, doc_id: str) -> str:
    # vertical = "credit" | "wealth" — always provided by caller
    return f"bronze/{org_id}/{vertical}/documents/{doc_id}"

# _global/ is exclusively for data with no org_id (FRED, Yahoo, benchmarks)
# Client documents NEVER go to _global/
```

**Pipeline stage outputs map to layers:**
- OCR raw output → `bronze/{org_id}/{vertical}/documents/{doc_id}.json`
- Chunks + embeddings → `silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet`
- Extracted metadata → `silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json`
- IC memos → `gold/{org_id}/{vertical}/memos/{memo_id}.json`

### Decision 6: extraction_orchestrator.py Becomes Thin CLI Wrapper

`extraction_orchestrator.py` has infrastructure responsibilities that don't belong in the document processing pipeline:

- `SOURCE_CONFIG` mapping (which Azure container, which indexer, which index)
- Blob download to tmpdir
- Entity bootstrap (batch pre-processing, not per-document)
- `ThreadPoolExecutor` parallelism
- Indexer trigger (batch post-processing)
- Job tracking (`run_extraction_pipeline`, `get_job_status`)

These are **batch orchestration concerns**, not document processing logic. A UI-uploaded document doesn't need entity bootstrap or indexer triggers.

**After refactor:**

```
Unified Pipeline (processes 1 document, source-agnostic)
───────────────────────────────────────────────────────
IngestRequest → OCR → [gate] → Classify → [gate]
             → Chunk → [gate] → Extract metadata → [gate]
             → Embed → [gate] → Upsert index
             → StorageClient write (bronze/silver)

extraction_orchestrator.py (thin CLI/batch wrapper, ~150 LOC)
───────────────────────────────────────────────────────
Keeps: SOURCE_CONFIG, blob download, entity bootstrap,
       ThreadPoolExecutor, indexer trigger, job tracking
Calls: unified_pipeline.process(IngestRequest(...)) per document
```

**Phase 2 acceptance criteria (updated):**
- `prepare_pdfs_full.py` deleted (duplicated logic absorbed)
- `domain_ingest_orchestrator.py` deleted (replaced by unified pipeline)
- `ingestion_worker.py` deleted (replaced by unified pipeline)
- `extraction_orchestrator.py` reduced from ~650 LOC to ~150 LOC (thin wrapper)

### Decision 7: ADLS as Source of Truth, Azure AI Search as Derived Index

ADLS and Azure AI Search serve fundamentally different purposes and are not interchangeable:

| | ADLS (durability + analytics) | Azure AI Search (real-time retrieval) |
|---|---|---|
| **Role** | System of record | Derived index |
| **Durability** | Permanent | Rebuildable from silver layer |
| **Use case** | Analytics, reprocessing, audit, backup | RAG queries for IC memo chapter generation |
| **Query pattern** | DuckDB over Parquet (batch analytics) | ANN vector search (sub-second retrieval) |

**Key rules:**
1. ADLS is the system of record (source of truth)
2. Azure AI Search is a derived index (can be reconstructed from silver layer)
3. The pipeline always writes to ADLS first
4. Azure AI Search is populated from ADLS, never directly from raw documents
5. If ADLS and Search are inconsistent, ADLS wins

**Consequence:** If the Azure Search index is corrupted or needs rebuilding (new embedding model, schema change), it can be reconstructed entirely from `silver/{org_id}/{vertical}/chunks/` without reprocessing original PDFs. Today this is impossible because the pipeline writes directly to Search without persisting chunks durably.

**Pipeline write targets per stage:**

```
OCR output
  → bronze/{org_id}/{vertical}/documents/{doc_id}.json        (ADLS)

Chunks + embeddings
  → silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet  (ADLS)
  → Azure AI Search upsert                                     (Search)

Extracted metadata (LLM)
  → silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json (ADLS)

IC memo
  → gold/{org_id}/{vertical}/memos/{memo_id}.json              (ADLS)
```

`search_upsert_service.py` changes role: from primary destination to consumer of the silver layer. Can be called inline (immediate consistency) or as a separate job (batch reconstruction).

---

## Implementation Phases

### Phase 1 — Deterministic Foundation (3 surgical adjustments)

Establishes a stable base before unifying paths. No existing pipeline is disrupted — new components are built alongside and switched in.

1. **Hybrid classifier** (`ai_engine/classification/hybrid_classifier.py`)
   - Layer 1: expand filename rules from 14 → ~40 covering all canonical types
   - Layer 2: sklearn nearest-centroid (TfidfVectorizer) using 31 candidate descriptions as synthetic exemplars
   - Layer 3: LLM fallback via existing `document_intelligence.py` templates
   - Covers both doc_type (31) and vehicle_type (6)
   - Cohere classification calls removed

2. **Cross-encoder reranker** (`ai_engine/extraction/local_reranker.py`)
   - `sentence-transformers` with `cross-encoder/ms-marco-MiniLM-L-6-v2`
   - Drop-in replacement for Cohere Rerank in RAG chunk selection
   - Used only for IC memo evidence pipeline

3. **Validation gates** (`ai_engine/pipeline/validation.py`)
   - `PipelineStageResult` dataclass
   - Validators for each stage transition
   - Logging + metrics for validation failures

**Cohere API dependency eliminated at end of Phase 1.**

### Phase 2 — Ingestion Path Unification

Single pipeline for batch and UI upload. The difference is queue priority and feedback, not analytical quality.

0. **PREREQUISITE — Diff analysis of `prepare_pdfs_full.py`**
   - Compare `prepare_pdfs_full.py` line-by-line with `{cohere_rerank.py, governance_detector.py, semantic_chunker.py, document_intelligence.py}`
   - Identify any unique logic not yet absorbed by the modular components
   - Document findings in `docs/solutions/` before any deletion
   - **`prepare_pdfs_full.py` CANNOT be deleted until this task is complete**
1. **Unified `IngestRequest` model** with source discriminator
2. **Single pipeline orchestrator** replacing `domain_ingest_orchestrator.py` and `ingestion_worker.py`
3. **SSE adapter** — UI source gets real-time feedback; batch source gets job tracking
4. **Slim `extraction_orchestrator.py`** — reduce from ~650 LOC to ~150 LOC thin wrapper that calls `unified_pipeline.process()` per document. Infrastructure concerns (SOURCE_CONFIG, blob download, entity bootstrap, indexer trigger) stay here.

**Acceptance criteria:**
- Diff analysis documented in `docs/solutions/`
- `prepare_pdfs_full.py` deleted (signal of completion — duplicated logic absorbed)
- `domain_ingest_orchestrator.py` deleted
- `ingestion_worker.py` deleted
- `extraction_orchestrator.py` reduced to thin wrapper (~150 LOC)

### Phase 3 — StorageClient + Bronze/Silver/Gold + Dual-Write

1. **Migrate all pipeline storage calls** from Azure Blob SDK to `StorageClient`
2. **Implement path routing** with `{org_id}/{vertical}/` prefix
3. **Stage output mapping** — each pipeline stage writes to the correct layer (bronze/silver/gold)
4. **Dual-write pattern** — chunks written to ADLS (source of truth) first, then upserted to Azure AI Search (derived index)
5. **Search rebuild capability** — `search_upsert_service.py` can reconstruct Azure Search from silver layer without reprocessing PDFs
6. **Multi-tenancy isolation** validated by path structure, not just blob metadata

---

## What We're NOT Building

- **New IC memo pipeline** — `deep_review.py` is the product. Untouched.
- **New OCR** — Mistral OCR has no Python alternative for financial PDFs. Untouched.
- **New metadata extraction** — gpt-4.1 structured extraction is the core IP. Untouched.
- **ML training pipeline** — Layer 2 uses 31 candidate descriptions as synthetic centroids via TF-IDF. No labeled dataset, no training loop, no maintenance burden.
- **New chunking strategy** — `semantic_chunker.py` is already correct (pure Python, adaptive sizing). Untouched.

---

## Open Questions

*None — all questions resolved during brainstorm dialogue.*

## Resolved Questions

1. **Scope: surgical adjustments only vs full alignment?** → Full alignment (Unify + optimize), sequenced into 3 phases to avoid big bang.
2. **ADLS path: vertical in path vs flat + metadata?** → Vertical in path. Vertical comes from request context, not document classification. `_global/` is for data with no org_id.
3. **Cross-encoder scope: classification + reranking vs reranking only?** → Reranking only. Classification and reranking are different problems. Hybrid classifier handles classification; cross-encoder handles RAG relevance ranking. Using a ranking model for classification would be a hack.
4. **Governance detection: needs LLM?** → No. Already pure regex (15 patterns). No change needed.
5. **What happens to extraction_orchestrator.py?** → Becomes thin CLI wrapper (~150 LOC). Infrastructure concerns (SOURCE_CONFIG, blob download, entity bootstrap, indexer trigger) stay there. Processing logic moves to unified pipeline.
6. **ADLS vs Azure AI Search relationship?** → ADLS is source of truth, Azure Search is derived index. Pipeline writes ADLS first. Search can be reconstructed from silver layer without reprocessing PDFs. If inconsistent, ADLS wins.

---

## Risk Notes

- **Phase 1 can be deployed independently** — hybrid classifier and validation gates improve the existing pipeline without requiring path unification.
- **Phase 2 deletion of `prepare_pdfs_full.py`** is gated by a mandatory diff analysis (Phase 2, Task 0). No deletion without documented confirmation that all unique logic has been absorbed.
- **Phase 3 StorageClient migration** is gated by `FEATURE_ADLS_ENABLED`. Local dev continues using PostgreSQL; ADLS paths only materialize in staging/production.
- **Layer 2 validation** — No A/B testing against Cohere. Cohere also misclassified and the system had no validation gates, so there is no ground truth to compare against. Instead, functional validation on 3 real documents from the existing deal room:
  1. An LPA → must classify as `legal_lpa` via Layer 1 (rules)
  2. An audited financial statement → must classify via Layer 1 or Layer 2
  3. An ambiguous document (e.g., research report) → must escalate to Layer 3 (LLM)
  If the 3 cases behave correctly, Layer 2 is approved. What matters is correctness on verifiable cases + validation gates catching when Layer 3 is needed.
