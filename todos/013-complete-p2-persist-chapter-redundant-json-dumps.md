---
status: complete
priority: p2
issue_id: "013"
tags: [code-review, performance]
dependencies: []
---

# Eliminate redundant json.dumps in _persist_chapter

## Problem Statement

`_persist_chapter()` in `memo/service.py` calls `json.dumps(evidence_pack, default=str)` on every chapter persist (line 124) purely to estimate input token count. This serializes the entire evidence pack (~50-100KB) 14 times per memo generation — ~1.4MB of throwaway serialization per run.

## Findings

- `service.py` line 124: `token_count_input=len(json.dumps(evidence_pack, default=str)) // 4`
- Called once per chapter x 14 chapters = 14 redundant serializations
- The evidence pack is identical for all 14 chapters within a single memo generation
- Found by: performance-oracle
- Related: `evidence.py` uses `_CHARS_PER_TOKEN = 3.5` while service.py uses `// 4` — inconsistent token estimation ratios

## Proposed Solutions

### Option 1: Compute once, pass as parameter

**Approach:** Compute `evidence_pack_json_len` once in `generate_memo_book()` / `async_generate_memo_book()` and pass it to `_persist_chapter()`.

**Pros:**
- Eliminates 13 redundant serializations per memo
- Trivial fix (add parameter, compute once)

**Cons:**
- Slightly changes `_persist_chapter` signature (private function, no external callers)

**Effort:** 20 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/vertical_engines/credit/memo/service.py` — `_persist_chapter()`, `generate_memo_book()`, `async_generate_memo_book()`

## Resources

- **PR:** #19
- **Review agent:** performance-oracle

## Acceptance Criteria

- [ ] `json.dumps(evidence_pack)` called exactly once per memo generation (not per chapter)
- [ ] `make check` passes

## Work Log

### 2026-03-15 - Code Review Discovery

**By:** Claude Code (ce:review)
**Actions:** Identified redundant serialization during performance review
