# Refactor: Migrate Azure Search Callers to pgvector Search Service

> Execute this prompt in a fresh Claude Code session on branch `refactor/deep-review-legacy-blob-removal`.

---

## Context

The pgvector migration (commit 497df51) replaced the Azure Search backend with `pgvector_search_service.py`, but **did not update the callers**. Four files still instantiate `AzureSearchChunksClient` (a dead stub with no methods) and call `resolve_index_scope()` / `search_institutional_hybrid()` — methods that don't exist on the stub. The pipeline crashes at runtime with `AttributeError`.

The pgvector service already has sync wrappers that match the needed functionality:
- `search_deal_chunks_sync()` — cosine similarity search scoped to deal + org
- `search_and_rerank_deal_sync()` — cosine + cross-encoder rerank
- `search_fund_policy_chunks_sync()` — policy-domain search scoped to fund + org
- `search_and_rerank_fund_policy_sync()` — policy + rerank
- `search_fund_chunks_sync()` — all-domain fund search (copilot RAG)

The callers need to stop using the Azure Search API shape and use the pgvector functions directly.

Read these files first (in this order):
1. `backend/ai_engine/extraction/pgvector_search_service.py` — the target API
2. `backend/app/services/search_index.py` — the dead stub being replaced
3. `backend/vertical_engines/credit/deep_review/corpus.py` — caller #1
4. `backend/vertical_engines/credit/retrieval/evidence.py` — caller #2
5. `backend/vertical_engines/credit/deep_review/policy.py` — caller #3
6. `backend/app/domains/credit/modules/ai/memo_chapters.py` — caller #4
7. `backend/app/domains/credit/documents/services/ai_review_analyzer.py` — caller #5

---

## Critical Knowledge

### vector_chunks table schema

```
id                  text (PK)
organization_id     uuid          ← MUST be in every query (tenant isolation)
deal_id             text
fund_id             text
domain              text
doc_type            text
doc_id              text
title               text
content             text
page_start          integer
page_end            integer
chunk_index         integer
section_type        text
breadcrumb          text
governance_critical boolean
embedding           vector(3072)
embedding_model     text
created_at          timestamptz
updated_at          timestamptz
```

### Key difference: Azure Search API vs pgvector API

| Azure Search (dead) | pgvector (live) |
|---|---|
| `AzureSearchChunksClient()` — class instance | Module-level functions — no class |
| `searcher.resolve_index_scope(fund_id, deal_id, deal_name, deal_folder_path)` → `(fund_id, deal_id, scope_mode)` | **Not needed.** pgvector uses `deal_id` UUID directly, no folder-derived index resolution |
| `searcher.search_institutional_hybrid(query, fund_id, deal_id, top, k, doc_type_filter, scope_mode)` → list of hit objects with `.title`, `.blob_name`, `.content_text`, `.score`, `.reranker_score`, etc. | `search_and_rerank_deal_sync(deal_id, organization_id, query_text, query_vector, top, candidates)` → `RerankedResult(chunks=[dict], signal=RetrievalSignal)`. Chunks are dicts with `"title"`, `"content"`, `"score"`, etc. |
| Hit objects: `.chunk_id`, `.title`, `.blob_name`, `.doc_type`, `.authority`, `.page_start`, `.page_end`, `.chunk_index`, `.content_text`, `.score`, `.reranker_score`, `.container_name`, `.retrieval_timestamp`, `.fund_id`, `.deal_id`, `.section_type`, `.vehicle_type`, `.governance_critical`, `.governance_flags`, `.breadcrumb` | Dict keys: `"id"`, `"deal_id"`, `"fund_id"` (when returned), `"domain"`, `"doc_type"`, `"title"`, `"content"`, `"page_start"`, `"page_end"`, `"chunk_index"`, `"score"` |
| OData `doc_type_filter` string: `"doc_type eq 'legal_lpa' or doc_type eq 'fund_structure'"` | `domain_filter` param (single domain string, e.g. `"POLICY"`) — doc_type filtering not supported at query level, done post-retrieval |
| `scope_mode`: `"STRICT"` / `"RELAXED"` | Not needed — pgvector scopes by `deal_id` + `organization_id` |

### pgvector sync search requires `query_vector`

The pgvector search functions require an embedding vector. The Azure Search used hybrid (text + vector) search. For pgvector, callers must:
1. Generate embedding via `generate_embeddings([query_text])` from `ai_engine.extraction.embedding_service`
2. Pass `query_vector=emb.vectors[0]` to the search function

### _get_sync_engine SSL bug

`pgvector_search_service.py` line 36 does:
```python
sync_url = settings.database_url.replace("+asyncpg", "+psycopg")
```
This produces `?ssl=require` which psycopg rejects. Must be `?sslmode=require`. Fix this.

---

## Changes Required

### 1. Fix `_get_sync_engine()` SSL param in `pgvector_search_service.py`

**File:** `backend/ai_engine/extraction/pgvector_search_service.py` line 36

```python
# BEFORE:
sync_url = settings.database_url.replace("+asyncpg", "+psycopg")

# AFTER:
sync_url = settings.database_url.replace("+asyncpg", "+psycopg").replace("?ssl=require", "?sslmode=require")
```

### 2. Refactor `corpus.py` — `_gather_deal_texts()`

**File:** `backend/vertical_engines/credit/deep_review/corpus.py`

**Remove:**
- `from app.services.search_index import AzureSearchChunksClient` (line 255)
- `searcher = AzureSearchChunksClient()` (line 266)
- `resolve_index_scope()` block (lines 273-278)
- `scope_mode` variable and all references
- The `if deal_name: d_id = deal_name` hack (line 287) — pgvector uses deal UUID, not name
- `from app.services.blob_storage import blob_uri, download_bytes` (line 16) — no longer used after Phase 6

**Add:**
- `from ai_engine.extraction.embedding_service import generate_embeddings`
- Pass `organization_id` through to `gather_chapter_evidence()`

**Refactor `_gather_deal_texts()`:**
- Use `f_id = str(fund_id)` and `d_id = str(deal.id)` directly (no scope resolution)
- Pass `organization_id=str(organization_id)` to `gather_chapter_evidence()`
- Remove `searcher` and `scope_mode` from `gather_chapter_evidence()` calls

### 3. Refactor `evidence.py` — `gather_chapter_evidence()`

**File:** `backend/vertical_engines/credit/retrieval/evidence.py`

This is the most complex change. The function currently accepts a `searcher` object and calls `searcher.search_institutional_hybrid()`. It needs to call pgvector directly.

**Change signature:**
```python
def gather_chapter_evidence(
    *,
    chapter_key: str,
    deal_name: str,
    fund_id: str,
    deal_id: str | None = None,
    organization_id: str | None = None,  # NEW — required for pgvector
    # REMOVE: searcher, global_dedup, doc_type_filter, override_filter, scope_mode
) -> dict[str, Any]:
```

**Replace `_execute_query()` inner function:**
- Instead of `searcher.search_institutional_hybrid(...)`, call:
  ```python
  from ai_engine.extraction.embedding_service import generate_embeddings
  from ai_engine.extraction.pgvector_search_service import search_and_rerank_deal_sync

  emb = generate_embeddings([query])
  query_vector = emb.vectors[0] if emb.vectors else None
  result = search_and_rerank_deal_sync(
      deal_id=uuid.UUID(deal_id),
      organization_id=organization_id,
      query_text=query,
      query_vector=query_vector,
      top=tier_top,          # replaces old `top` param
      candidates=tier_k,     # replaces old `k` param
  )
  hits = result.chunks  # list[dict]
  ```

**Map dict keys to the existing chunk_data format:**
The existing code reads Azure Search hit objects with dot notation (`.title`, `.blob_name`, `.content_text`). pgvector returns dicts with keys like `"title"`, `"content"`, `"score"`. Map accordingly:

```python
for chunk in hits:
    title      = chunk.get("title", "")
    chunk_idx  = chunk.get("chunk_index", 0)
    score      = chunk.get("score", 0.0)
    reranker_score = chunk.get("reranker_score", score)  # rerank adds this key
    hits_data.append({
        "chunk_id":            chunk.get("id", ""),
        "title":               title,
        "blob_name":           title,  # pgvector has no separate blob_name — use title
        "doc_type":            chunk.get("doc_type", "unknown"),
        "authority":           "",     # not in pgvector schema
        "page_start":          chunk.get("page_start", 0),
        "page_end":            chunk.get("page_end", 0),
        "chunk_index":         chunk_idx,
        "content":             chunk.get("content", ""),
        "score":               score,
        "reranker_score":      reranker_score,
        "_best_score":         reranker_score or score,
        "_query_origin":       query[:80],
        "_chapter_key":        chapter_key,
        "_retrieval_mode":     retrieval_mode,
        "container_name":      "",
        "retrieval_timestamp": "",
        "fund_id":             chunk.get("fund_id", ""),
        "deal_id":             chunk.get("deal_id", ""),
        "section_type":        chunk.get("section_type"),
        "vehicle_type":        None,   # not in pgvector schema
        "governance_critical": chunk.get("governance_critical", False),
        "governance_flags":    [],     # not in pgvector schema
        "breadcrumb":          chunk.get("breadcrumb"),
    })
```

**Remove doc_type_filter logic:**
- Remove `CHAPTER_DOC_TYPE_FILTERS` import and usage (already dead — was Phase 4 backlog item, safe to do here)
- Remove the filter-retry block (lines 257-334) — pgvector doesn't support OData filters
- Keep the cross-deal contamination detection block (lines 337-369) — still needed
- Keep the signal-based expansion block (lines 396-460) — still needed, it re-calls `_execute_query` with expanded tiers

**Embedding caching:** Each query in a chapter fires `generate_embeddings()`. This is an OpenAI API call. To avoid N separate calls per chapter, batch all queries:
```python
queries = query_map.get(chapter_key, [])
if queries:
    emb_result = generate_embeddings(queries)
    query_vectors = emb_result.vectors  # list[list[float]]
else:
    query_vectors = []
```
Then in `_execute_query`, use `query_vectors[q_idx]` instead of calling `generate_embeddings` per query.

### 4. Refactor `policy.py` — `_gather_policy_context()`

**File:** `backend/vertical_engines/credit/deep_review/policy.py`

**Remove:**
- `from app.services.search_index import AzureSearchChunksClient`
- `searcher = AzureSearchChunksClient()`
- `searcher.resolve_index_scope()` call
- `searcher.search_institutional_hybrid()` calls

**Replace with:**
```python
from ai_engine.extraction.embedding_service import generate_embeddings
from ai_engine.extraction.pgvector_search_service import search_and_rerank_fund_policy_sync
```

This function searches fund-level policy documents (not deal-level), so use `search_and_rerank_fund_policy_sync()` with `domain_filter="POLICY"`.

The `organization_id` parameter is already in the function signature — pass it through.

### 5. Refactor `memo_chapters.py` — single-chapter re-retrieval

**File:** `backend/app/domains/credit/modules/ai/memo_chapters.py` (around line 517-546)

Same pattern as corpus.py. Replace:
- `AzureSearchChunksClient()` → pgvector functions
- `searcher.resolve_index_scope()` → remove (use fund_id/deal_id directly)
- `gather_chapter_evidence(searcher=...)` → `gather_chapter_evidence(organization_id=...)`

This caller needs `organization_id`. Check how `regenerate_single_chapter()` is called and ensure `organization_id` is available (it should be via the RLS context or the deal record).

### 6. Refactor `ai_review_analyzer.py` — `InstitutionalSearchEngine` stub

**File:** `backend/app/domains/credit/documents/services/ai_review_analyzer.py` (lines 103-104, 131)

This uses `InstitutionalSearchEngine` (another dead stub) for document review search. Replace with pgvector search. The `_search_for_item()` function (line 116) calls `search_engine.search_institutional_hybrid()` with `scope_mode="FUND_ONLY"` — this maps to `search_and_rerank_fund_sync()`.

### 7. Update callers of `gather_chapter_evidence()`

After changing the signature (removing `searcher`, `scope_mode`, adding `organization_id`), update ALL callers:

```
corpus.py:306      — _fetch_chapter() lambda
memo_chapters.py:539  — single chapter re-retrieval
```

Remove `searcher=searcher, scope_mode=scope_mode` and add `organization_id=str(organization_id)`.

### 8. Clean up `search_index.py`

**File:** `backend/app/services/search_index.py`

After all callers are migrated:
- Remove `AzureSearchChunksClient` class (lines 206-211) — no callers left
- Remove `InstitutionalSearchEngine` class (lines 226-231) — no callers left
- Keep `AzureSearchMetadataClient` — still used by document metadata (separate concern)
- Keep exception classes (`RetrievalEmbeddingError`, `RetrievalExecutionError`, `RetrievalScopeError`) if referenced elsewhere, else remove

### 9. Update tests

- `backend/tests/test_corpus_no_legacy_fallback.py` — patches `AzureSearchChunksClient`, needs to patch pgvector functions instead
- `backend/tests/test_search_tier_expansion.py` — patches `searcher.search_institutional_hybrid`, needs update
- Any test importing `AzureSearchChunksClient` or `InstitutionalSearchEngine` — update or remove

### 10. Remove dead `models.py` constants

After evidence.py no longer uses doc_type filters:
- Remove `CHAPTER_DOC_TYPE_FILTERS` from `vertical_engines/credit/retrieval/models.py` — dead code (was Phase 4 backlog, now folded in)
- Keep `CHAPTER_SEARCH_TIERS`, `DEFAULT_SEARCH_TIER`, `EXPANDED_SEARCH_TIER` — still used by evidence.py
- Keep `CRITICAL_DOC_TYPES` — different concern (evidence pack assembly)

---

## Execution Checklist

1. [ ] Fix `_get_sync_engine()` SSL param
2. [ ] Refactor `evidence.py` — new signature + pgvector calls + embedding batching
3. [ ] Refactor `corpus.py` — remove AzureSearchChunksClient, pass organization_id
4. [ ] Refactor `policy.py` — use `search_and_rerank_fund_policy_sync()`
5. [ ] Refactor `memo_chapters.py` — remove AzureSearchChunksClient, pass organization_id
6. [ ] Refactor `ai_review_analyzer.py` — replace InstitutionalSearchEngine
7. [ ] Clean up `search_index.py` — remove dead classes
8. [ ] Remove `CHAPTER_DOC_TYPE_FILTERS` from `retrieval/models.py`
9. [ ] Remove `blob_storage` import from `corpus.py`
10. [ ] Update all tests
11. [ ] Run `make check` — all tests pass
12. [ ] Run `make architecture` — no import-linter violations

---

## Rules

- **Do NOT modify any prompt templates (`.j2` files).**
- **Do NOT modify `pgvector_search_service.py` beyond the SSL fix** — its API is stable.
- **Do NOT add new dependencies.**
- **Do NOT change the return shape of `gather_chapter_evidence()`** — downstream consumers (`build_ic_corpus`, `enforce_evidence_saturation`, `build_retrieval_audit`) depend on the current dict structure.
- **Keep the cross-deal contamination filter** in `evidence.py` — it's still needed.
- **Keep the signal-based expansion** in `evidence.py` — it's Phase 5 work that's already implemented.
- **Batch embedding calls** — don't call `generate_embeddings()` per query. Batch all chapter queries in one call.
- **organization_id is mandatory** for all pgvector queries. If a caller doesn't have it, trace it from the deal record or the RLS context. Never query pgvector without tenant filter.

---

## Commit Convention

Single commit:
```
refactor(retrieval): migrate Azure Search callers to pgvector search service

Replace dead AzureSearchChunksClient stub with live pgvector_search_service
functions across 5 callers (corpus.py, evidence.py, policy.py, memo_chapters.py,
ai_review_analyzer.py). Fix SSL param for psycopg sync engine. Remove dead
CHAPTER_DOC_TYPE_FILTERS. Batch embedding generation per chapter.
```

Branch: `refactor/deep-review-legacy-blob-removal` (current branch — this is a natural continuation of the Phase 6 blob removal already on this branch).
