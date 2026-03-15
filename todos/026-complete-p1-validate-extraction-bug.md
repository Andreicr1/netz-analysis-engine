---
status: pending
priority: p1
issue_id: "026"
tags: [code-review, bug, validation]
dependencies: []
---

## Problem Statement

`validate_extraction()` in `validation.py` checks for `REQUIRED_METADATA_FIELDS = frozenset({"doc_type"})` but the extraction metadata dict contains `dates`, `amounts`, `parties`, `counterparties`, `jurisdictions` — never `doc_type`. So `validate_extraction` ALWAYS produces an error, which is ALWAYS downgraded to a warning. Every document gets a spurious warning. It is a non-functional gate pretending to be validation.

## Findings

- `REQUIRED_METADATA_FIELDS` at line ~186 is `frozenset({"doc_type"})`.
- Extraction output metadata contains: `dates`, `amounts`, `parties`, `counterparties`, `jurisdictions` — never `doc_type`.
- Because `doc_type` is never present, `validate_extraction()` always reports a missing field error.
- The error is always downgraded to a warning (lines 327-332 in `unified_pipeline.py`), so it never halts processing.
- Every single document processed through the pipeline receives a spurious "Missing required metadata fields" warning.
- The validation gate provides zero actual value — it never catches real issues and always fires a false positive.

## Proposed Solutions

**(a)** Fix `REQUIRED_METADATA_FIELDS` to match actual extraction output fields (e.g., `dates`, `amounts`, `parties`).

**(b)** Remove `validate_extraction` entirely since the gate never halts processing and extraction failures are already handled via `return_exceptions=True` in `asyncio.gather`.

## Technical Details

- **Files:**
  - `backend/ai_engine/pipeline/validation.py` lines 186-210
  - `backend/ai_engine/pipeline/unified_pipeline.py` lines 327-332
- `REQUIRED_METADATA_FIELDS = frozenset({"doc_type"})` — never present in extraction output
- Error always downgraded to warning — gate never halts

## Acceptance Criteria

- [ ] No spurious "Missing required metadata fields" warning on every document
- [ ] Validation gate either works correctly (checks real fields) or is removed entirely
- [ ] If kept, `REQUIRED_METADATA_FIELDS` matches actual extraction output schema
