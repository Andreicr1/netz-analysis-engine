---
status: pending
priority: p2
issue_id: "028"
tags: [code-review, quality, refactoring]
dependencies: []
---

## Problem Statement

`unified_pipeline.py` has 4 identical gate-failure blocks (~80 LOC of duplication). Each block checks success, emits an SSE error, audits the failure, and returns a `PipelineStageResult`. The same pattern is repeated at lines 142-158, 186-202, 255-271, and 349-365.

## Findings

- Four gate-check blocks follow the exact same structure: check gate result success, emit SSE error event, record audit failure, return `PipelineStageResult` with failure status.
- This duplication inflates `process()` by ~80 lines unnecessarily.
- Any change to the gate-failure pattern (e.g., adding a metric, changing the SSE payload) must be replicated in all 4 locations, risking drift.

## Proposed Solutions

Extract an `async _check_gate()` helper method that takes:
- The gate result object
- The stage name/enum
- The request context (for SSE emission and audit)

Returns `PipelineStageResult` on failure, or `None` on success. Each call site becomes a simple two-line check:

```python
if failure := await self._check_gate(gate_result, stage, ctx):
    return failure
```

This reduces `process()` from ~370 lines to ~290 lines.

## Technical Details

- File: `backend/ai_engine/pipeline/unified_pipeline.py`
- Duplicated blocks at lines: 142-158, 186-202, 255-271, 349-365
- The helper should be a private async method on the pipeline class.

## Acceptance Criteria

- Gate-handling logic exists in a single `_check_gate()` helper function.
- No duplicated gate-failure blocks remain in `process()`.
- All 4 gate checks use the shared helper.
- Behavior is identical before and after refactor.
