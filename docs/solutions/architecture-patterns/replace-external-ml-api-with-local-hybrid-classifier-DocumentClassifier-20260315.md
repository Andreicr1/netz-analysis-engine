---
title: "Cohere Rerank API replaced with local hybrid three-layer classifier"
category: "architecture-patterns"
severity: "high"
component: "ai_engine/classification, ai_engine/extraction, ai_engine/pipeline"
date_discovered: "2026-03-15"
date_resolved: "2026-03-15"
tags:
  - llm-overuse
  - external-dependency
  - cost-optimization
  - supply-chain-security
  - thread-safety
  - document-classification
  - cohere-rerank
  - cross-encoder
  - deterministic-first
  - asyncio-patterns
related_files:
  - backend/ai_engine/classification/hybrid_classifier.py
  - backend/ai_engine/extraction/local_reranker.py
  - backend/ai_engine/pipeline/models.py
  - backend/ai_engine/pipeline/validation.py
  - backend/ai_engine/extraction/document_intelligence.py
  - backend/ai_engine/extraction/entity_bootstrap.py
---

# Replace External ML API with Local Hybrid Classifier

## Problem Statement

The document classification pipeline relied exclusively on Azure AI Foundry's Cohere Rerank endpoint to classify incoming documents into one of 31 `doc_type` categories. Cohere Rerank is a **ranking model** repurposed as a classifier by treating each doc_type label as a candidate and picking the top-ranked result. This created four compounding problems:

1. **LLM overuse:** 80%+ of documents are deterministically classifiable by filename patterns and content headers, yet every document incurred a full API round-trip.
2. **External API dependency:** 200-800ms latency per call, per-request cost, rate-limit exposure, and document content sent to a third party.
3. **Thread safety at async boundary:** The local cross-encoder replacement needed careful async/thread boundary handling to avoid blocking the event loop.
4. **Supply chain security:** Loading HuggingFace models without revision pinning allows upstream repository compromise to inject arbitrary code.

Additionally, `entity_bootstrap.py` had hidden direct HTTP calls to the Cohere endpoint (lines 700-742) bypassing `cohere_rerank.py` — a dependency that would survive any refactor of the main classification path.

## Symptoms

- Every document upload triggered a Cohere API call, even for files named `2024-Q3-Financial-Statements.pdf`
- Classification latency: 200-800ms network round-trip before extraction could begin
- Cohere endpoint outages halted document ingestion for all tenants
- Rerank scores are relative rankings, not calibrated probabilities — low-confidence ties between adjacent types with no principled fallback threshold
- Document content (confidential financials, PII, deal terms) sent to external API on every classification
- No auditability of classification reasoning

## Root Cause Analysis

The pipeline inherited from Private Credit OS used a ranking model for a classification problem. Cohere Rerank compares a query against candidate descriptions and returns relevance scores — it was never designed for multi-class classification. The architectural mismatch caused:

- No deterministic fast-path for unambiguous documents
- No inter-stage validation (the 60% content loss bug from `semantic_chunker` propagated silently)
- Monolith duplication (`prepare_pdfs_full.py` at 1786 LOC duplicated logic from modular components)

## Solution

### Three-Layer Hybrid Classifier

**Layer 1 — Deterministic Rules (confidence=1.0, ~80% of documents):**

28 filename regex rules + 13 content rules ported from `prepare_pdfs_full.py` (richer NOT clauses preserved intact as TF-IDF discriminative features). Returns immediately with zero cost.

**Layer 2 — TF-IDF Cosine Similarity (~15% of documents):**

31 synthetic exemplars from `prepare_pdfs_full.py` descriptions, vectorized at startup:

```python
TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), max_features=5000, stop_words="english")
```

Head+tail OCR window (5000+2000 chars). Rejection thresholds: `min_similarity=0.05`, `min_ratio=1.3`. Direct `cosine_similarity` instead of `NearestCentroid` (with 1 exemplar per class, NearestCentroid degenerates to 1-NN with Euclidean distance).

**Layer 3 — LLM Fallback (~5% of documents):**

Reuses existing `async_classify_document()` from `document_intelligence.py`. Only for genuinely ambiguous cases.

### Local Cross-Encoder for RAG Reranking

`ms-marco-MiniLM-L-6-v2` (22MB, CPU-only) replaces Cohere for chunk relevance scoring. Thread-safe via `asyncio.Lock` with `threading.Lock` bootstrap guard. Model pinned to revision `c510bff`.

### Validation Gates

Five inter-stage gates returning `PipelineStageResult`. Key gate: content retention check (25% threshold) prevents the 60% content loss class of bugs.

### Single Source of Truth

`CANONICAL_DOC_TYPES` consolidated to `pipeline/models.py` as a `frozenset[str]`. All consumers import from there. Import-time `RuntimeError` (not `assert`) verifies description dictionaries match.

## Key Technical Decisions

1. **Cosine similarity over NearestCentroid** — with 1 exemplar per class, NearestCentroid degenerates. Direct cosine is simpler and better for sparse TF-IDF.
2. **Classification and reranking are separate problems** — ranking model for classification is a hack. Each tool is purpose-built.
3. **Three-layer escalation with no retry** — rejection always escalates forward. Deterministic and debuggable.
4. **threading.Lock bootstrap for asyncio.Lock** — prevents race condition in lazy lock creation (Known Pattern: thread-unsafe-rate-limiter-FredService).
5. **Model revision pinning** — prevents supply chain attacks via HuggingFace model poisoning.
6. **Head+tail OCR window** — tail chars contain signature blocks and entity declarations that distinguish similar types.
7. **Content retention gate at 25%** — catches catastrophic loss while allowing legitimate stripping.
8. **IngestRequest.org_id from JWT only** — prevents tenant impersonation.

## Prevention Strategies

### For External API Dependencies
- Before adding external API dependency: Can this be solved deterministically? Can it use a local model? What's the fallback?
- Maintain a decision log for classification/ranking tasks with approach chosen and justification.

### For Thread Safety in Async Primitives
- All asyncio primitives must be created lazily inside async methods, bootstrapped by `threading.Lock`.
- CI check: flag `asyncio.Lock()`, `asyncio.Semaphore()`, `asyncio.Event()` at module scope.

### For Supply Chain Risk
- Every ML model reference must include `revision=` with a specific commit SHA.
- CI check: grep for model loading calls and verify `revision=` is present.

### For Duplicate Definitions
- Constants referenced by >1 module must live in a dedicated file. All consumers import from there.

### Checklist for Future Similar Work
- [ ] Is external API strictly necessary, or can this be solved locally?
- [ ] Are all asyncio primitives created lazily with threading.Lock bootstrap?
- [ ] Are ORM attributes in frozen dataclasses before crossing async/thread boundaries?
- [ ] Do all path/URI fields validate against traversal at construction time?
- [ ] Are all `assert` in non-test code replaced with `if/raise`?
- [ ] Are ML model references pinned to specific revision SHA?
- [ ] Are new constants defined in exactly one place?

## Related Documentation

- [Pipeline LLM-Deterministic Alignment Brainstorm](../../brainstorms/2026-03-15-pipeline-llm-deterministic-alignment-brainstorm.md)
- [Pipeline LLM-Deterministic Alignment Plan](../../plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md)
- [Thread-Unsafe Rate Limiter FredService](../runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md) — same threading.Lock bootstrap pattern
- [Vertical Engine Extraction Patterns](vertical-engine-extraction-patterns.md) — asyncio.to_thread() pattern
- [Monolith-to-Modular Package Migration](monolith-to-modular-package-with-library-migration.md) — PEP 562 lazy imports, never-raises pattern
- [RLS Subselect 1000x Slowdown](../performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md) — related pipeline performance
- PR #20: `refactor/pipeline-llm-deterministic-phase1`
