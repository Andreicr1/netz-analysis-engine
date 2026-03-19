# E2E Wealth Pipeline Quality Test

## Objective

Add a **Group 10: Wealth Document Pipeline (Full)** to the e2e smoke test (`backend/tests/e2e_smoke_test.py`) that validates the complete wealth vertical ingestion pipeline with real PDFs from R2 storage.

## Context

Read these files before starting:
- `CLAUDE.md` — full project rules, architecture, critical constraints
- `backend/tests/e2e_smoke_test.py` — existing e2e (54 tests across 9 groups)
- `backend/ai_engine/extraction/local_reranker.py` — cross-encoder reranker (just added)
- `backend/ai_engine/extraction/pgvector_search_service.py` — search + rerank wrappers

## What was already validated (commit 0c68dde)

Groups 1-9 cover: infrastructure (PG, Redis, R2), external APIs, instrument provider, quant engine, regime, wealth document models, DD report approval workflow, AI pipeline (classifier, chunker, OCR, embedding), and vector store + semantic quality with synthetic corpus.

**What's missing:** an e2e test that exercises the wealth vertical's **full document ingestion → search → rerank** flow using real PDFs.

## Architecture — Wealth Document Pipeline

The wealth pipeline is:
1. **Upload** → `wealth_documents` + `wealth_document_versions` tables
2. **Storage** → R2 (prod) or LocalStorage (dev) via `StorageClient`
3. **OCR** → Mistral `async_extract_pdf_with_mistral`
4. **Classify** → `hybrid_classifier.classify()` (3-layer: rules → TF-IDF → LLM)
5. **Chunk** → `semantic_chunker.chunk_document()`
6. **Embed** → `embedding_service.async_generate_embeddings()` (text-embedding-3-large, dim=3072)
7. **Upsert** → `pgvector_search_service.upsert_chunks()` into `vector_chunks` table
8. **Search** → `search_and_rerank_deal()` or `search_deal_chunks()` with optional reranker

Key wealth doc types: `fund_presentation`, `investment_memo`, `legal_lpa` (PPM/LPA), `fund_profile`, `strategy_profile`, `operational_monitoring`.

## What Group 10 should test

### 10.1 — Download sample PDFs from R2
Download 3 wealth-relevant PDFs from R2 bucket `netz-data-lake`. Use the BridgeInvest fund (org=`70f19993-b0d9-42ff-b3c7-cf2bb0728cec`, fund=`66b1ed07-8274-4d96-806f-1515bb0e148b`). Good candidates:
- `BridgeInvest Credit Fund V LP_Fund Presentation_Q1 2026.pdf` (~3.2MB, 46 pages)
- `BridgeInvest_Investment Memo_Balfour Hotel.pdf` (~2.8MB, 27 pages)
- `BridgeInvest_Quarterly Investor Letter_Q4 2025.pdf` (~1.7MB, 10 pages)

Build the R2 endpoint from `R2_ACCOUNT_ID` if `R2_ENDPOINT_URL` not set (same pattern as test 1.3).

### 10.2 — OCR each PDF
Use `async_extract_pdf_with_mistral()` with retry (Mistral can SSLError on large PDFs). Assert pages > 0 and text length > 100.

### 10.3 — Classify each PDF
Use `classify(text=ocr_text[:3000], filename=fname)`. Validate:
- Fund Presentation → `fund_presentation` (L1 or L2)
- Investment Memo → `investment_memo` (L1, new rule added in 0c68dde)
- Quarterly Letter → `fund_presentation` (L1, new rule added in 0c68dde)

### 10.4 — Chunk each PDF
Use `chunk_document(ocr_text, doc_id, doc_type, metadata)`. Assert chunks > 0 and avg chunk length > 200.

### 10.5 — Embed all chunks
Use `async_generate_embeddings()` in batches of 20. Assert all vectors have dim=3072.

### 10.6 — Upsert to vector_chunks
Use `build_search_document()` + `upsert_chunks()`. Use a synthetic deal_id `00000000-0000-0000-0000-wea1th0e2e01` (valid hex: `00000000-0000-0000-0000-aea10000e201`). Set `organization_id=TEST_ORG` (not the real BridgeInvest org, so cleanup is safe). Assert all upserts succeed.

### 10.7 — Semantic search quality (cosine only)
Query: "What was the fund performance in Q4 2025?" → top result should come from the Quarterly Letter or Fund Presentation.

### 10.8 — Semantic search with reranker
Use `search_and_rerank_deal()` with `candidates=30, top=5`. Same query. Assert `reranker_score` field exists on results. Assert top result has higher reranker_score than cosine-only top.

### 10.9 — Cross-document relevance
Query: "Describe the Balfour Hotel loan structure and LTV" → top result should come from Investment Memo.

### 10.10 — Cleanup
Delete all `vector_chunks` where `deal_id = :synthetic_deal_id`.

## Implementation notes

- Guard all tests with `if has_key("OPENAI_API_KEY") and has_key("MISTRAL_API_KEY"):`
- Add retry with `await asyncio.sleep(2)` for Mistral OCR (SSL errors on large PDFs)
- Use `with_timeout(coro, 60)` for OCR calls (large PDFs can take 30s+)
- Reranker loads model lazily on first call (~2s model load, then <100ms per batch)
- `build_search_document` does NOT accept `embedding_model` as kwarg — set it via `doc["embedding_model"] = "text-embedding-3-large"` after building
- Cleanup: add `DELETE FROM vector_chunks WHERE deal_id = :deal` to the finally block

## Files to modify

1. `backend/tests/e2e_smoke_test.py` — add Group 10 between Group 9 and the `finally:` cleanup block

## Validation

After implementing, run:
```bash
cd backend && python tests/e2e_smoke_test.py
```

Expected: all existing 54 tests pass + 10 new tests = 64 total (Mistral tests skip if key not set).
