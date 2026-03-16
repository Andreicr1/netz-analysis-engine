---
status: pending
priority: p3
issue_id: "073"
tags: [code-review, quality]
---

# 073: FactSheetEngine uses stdlib logging instead of structlog

## Problem Statement

fact_sheet_engine.py line 17 uses `import logging` / `logging.getLogger(__name__)` while ALL other wealth engines use structlog. Inconsistent with codebase convention.

## Findings

- `fact_sheet_engine.py:17` — uses stdlib `logging` module
- Every other wealth engine uses `structlog.get_logger()`
- Breaks structured logging pipeline (no JSON output, no bound context)

## Proposed Solutions

Replace with `import structlog` / `structlog.get_logger()`.

## Acceptance Criteria

- [ ] `fact_sheet_engine.py` uses `structlog.get_logger()` instead of `logging.getLogger(__name__)`
- [ ] No stdlib `logging` import remains in the file
- [ ] Existing log calls work with structlog API
