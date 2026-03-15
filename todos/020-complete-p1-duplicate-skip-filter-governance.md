---
status: pending
priority: p1
issue_id: "020"
tags: [code-review, duplication, pattern]
dependencies: []
---

## Problem Statement

Two identical `skip_filter.py` files exist: `ai_engine/ingestion/skip_filter.py` (new) and `ai_engine/extraction/skip_filter.py` (existing). Same for `governance_detector.py` — the new version in `ingestion/` returns a bare tuple, while the existing version in `extraction/` returns a frozen `GovernanceResult` dataclass (better). Maintenance divergence risk.

## Findings

- `backend/ai_engine/ingestion/skip_filter.py` duplicates `backend/ai_engine/extraction/skip_filter.py`.
- `backend/ai_engine/ingestion/governance_detector.py` duplicates `backend/ai_engine/extraction/governance_detector.py` but with a weaker return type (bare tuple vs frozen `GovernanceResult` dataclass).
- `unified_pipeline.py` imports from the new `ingestion/` copies.
- Two copies of the same logic will inevitably diverge, causing subtle bugs.

## Proposed Solutions

1. Delete the new duplicates in `ingestion/`.
2. Have `unified_pipeline.py` import from existing `extraction/skip_filter.py` and `extraction/governance_detector.py`.
3. Adapt pipeline code to use the `GovernanceResult` dataclass from the extraction version.

## Technical Details

- **Files:**
  - `backend/ai_engine/ingestion/skip_filter.py` (delete)
  - `backend/ai_engine/ingestion/governance_detector.py` (delete)
  - `backend/ai_engine/pipeline/unified_pipeline.py` (update imports)
  - `backend/ai_engine/extraction/skip_filter.py` (canonical source)
  - `backend/ai_engine/extraction/governance_detector.py` (canonical source)

## Acceptance Criteria

- [ ] Only one `skip_filter.py` exists in the codebase (in `extraction/`)
- [ ] Only one `governance_detector.py` exists in the codebase (in `extraction/`)
- [ ] `unified_pipeline.py` imports from `extraction/` versions
- [ ] Pipeline uses `GovernanceResult` dataclass (not bare tuple)
