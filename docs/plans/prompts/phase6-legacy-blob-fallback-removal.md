# Phase 6 Prompt — Legacy Blob Fallback Removal

> Paste this prompt into a fresh Claude Code session to execute Phase 6.

---

## Context

You are implementing Phase 6 of the Deep Review Optimization plan. This phase removes legacy blob-download fallback paths from `deep_review/corpus.py`.

Read these documents first:

1. `docs/reference/deep-review-optimization-plan-2026-03-20.md` — the full optimization plan
2. `docs/plans/2026-03-20-deep-review-optimization-backlog.md` — Phase 6 details

**Goal:** Remove dead legacy blob-download functions that served as fallbacks before the RAG pipeline was complete. All deals are now indexed — the fallback is unreachable in production.

## Current State

- `deep_review/corpus.py` has three legacy functions:
  - `_extract_text_from_blob()` (line ~33) — downloads blob and extracts text via PDF/DOCX parsers
  - `_gather_deal_texts_legacy()` (line ~413) — queries `DocumentRegistry`, downloads blobs per deal
  - `_gather_investment_texts_legacy()` (line ~519) — queries `DocumentRegistry`, downloads blobs per investment
- `_gather_deal_texts()` (line ~394) falls back to `_gather_deal_texts_legacy()` when RAG returns no chunks
- `_gather_investment_texts()` (line ~516) falls back to `_gather_investment_texts_legacy()` when RAG returns no chunks
- `from app.services.blob_storage import blob_uri, download_bytes` (line ~19) — only used by legacy functions
- `from app.services.text_extract import extract_text_from_docx, extract_text_from_pdf` (line ~20) — only used by `_extract_text_from_blob`

### What to KEEP

- `_load_deal_context_from_blob()` (line ~63) in `corpus.py` — still used in primary path for `deal_context.json` loading. This is a separate concern and must NOT be removed.
- `_load_deal_context_from_blob` uses `blob_uri` and `download_bytes` — verify if this function uses those imports before removing them. If it does, keep the `blob_storage` import.

## Implementation Steps

### Step 1: Remove legacy functions from `deep_review/corpus.py`

1. Delete `_extract_text_from_blob()` function entirely
2. Delete `_gather_deal_texts_legacy()` function entirely
3. Delete `_gather_investment_texts_legacy()` function entirely
4. Remove `_EXTRACTABLE_EXTENSIONS` constant (only used by `_extract_text_from_blob`)

### Step 2: Replace fallback paths with warning + empty return

In `_gather_deal_texts()` (~line 394), replace the legacy fallback block:

**Before:**
```python
# ── Fallback: legacy blob download (only if no indexed chunks) ──
logger.warning(
    "rag_empty.fallback_blob_download",
    deal_id=d_id,
    fund_id=f_id,
    entity_type="deal",
)
legacy_text = _gather_deal_texts_legacy(db, fund_id=fund_id, deal=deal)
return {
    "corpus_text": legacy_text,
    ...
}
```

**After:**
```python
# No indexed chunks — return empty corpus with warning
logger.warning(
    "rag_empty.no_indexed_chunks",
    deal_id=d_id,
    fund_id=f_id,
    entity_type="deal",
)
return {
    "corpus_text": "",
    "evidence_map": [],
    "raw_chunks": [],
    "chapter_evidence": {},
    "retrieval_audit": retrieval_audit,
    "saturation_report": saturation_report,
}
```

In `_gather_investment_texts()` (~line 509), replace similarly:

**Before:**
```python
# ── Fallback: legacy blob download ────────────────────────────
logger.warning(
    "rag_empty.fallback_blob_download",
    investment_id=str(investment.id),
    fund_id=str(fund_id),
    entity_type="investment",
)
return _gather_investment_texts_legacy(db, fund_id=fund_id, investment=investment)
```

**After:**
```python
# No indexed chunks — return empty string with warning
logger.warning(
    "rag_empty.no_indexed_chunks",
    investment_id=str(investment.id),
    fund_id=str(fund_id),
    entity_type="investment",
)
return ""
```

### Step 3: Clean up imports

- Check if `_load_deal_context_from_blob()` uses `blob_uri` or `download_bytes`
- If YES: keep the `blob_storage` import
- If NO: remove `from app.services.blob_storage import blob_uri, download_bytes`
- Remove `from app.services.text_extract import extract_text_from_docx, extract_text_from_pdf` (only used by deleted `_extract_text_from_blob`)
- Remove `from pathlib import Path` if only used by `_extract_text_from_blob`

### Step 4: Update `__all__`

Remove `_load_deal_context_from_blob` from `__all__` ONLY if it is no longer in the file. Since we are keeping it, `__all__` should remain unchanged.

### Step 5: Tests

Add tests in a new file `backend/tests/test_corpus_no_legacy_fallback.py`:

- `test_deal_empty_corpus_on_no_chunks`: Mock RAG returning no chunks for a deal → verify empty `corpus_text` string, warning logged
- `test_investment_empty_string_on_no_chunks`: Mock RAG returning no chunks for investment → verify empty string returned, warning logged
- `test_no_blob_storage_calls`: Ensure `download_bytes` is never called during corpus assembly (patch and assert not called)

Run: `make check` passes (lint + typecheck + test)

### Step 6: Validate

- `_gather_deal_texts_legacy` no longer exists in codebase
- `_gather_investment_texts_legacy` no longer exists in codebase
- `_extract_text_from_blob` no longer exists in codebase
- `_load_deal_context_from_blob` still present and functional
- No `extract_text_from_pdf` or `extract_text_from_docx` imports in corpus.py

## Branch & PR

- Branch: `refactor/deep-review-legacy-blob-removal`
- PR title: `refactor(deep-review): remove legacy blob fallback from corpus assembly`

---

## Phase 7 Note

Phase 7 (`_pre_classify_from_corpus()` deprecation) is **DEFERRED** pending 50+ deal concordance data from production. Do NOT generate a Phase 7 prompt.
