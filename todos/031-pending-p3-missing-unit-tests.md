---
status: pending
priority: p3
issue_id: "031"
tags: [code-review, testing]
dependencies: []
---

## Problem Statement

No unit tests exist for `skip_filter`, `governance_detector`, or the pipeline `process()` function. `skip_filter` and `governance_detector` are pure functions that are trivial to test parametrically. The pipeline `process()` needs at minimum a mocked happy-path integration test.

## Findings

- `skip_filter` (the `is_skippable()` function) is a pure function with clear input/output that has no test coverage.
- `governance_detector` (the `detect_governance()` function) is similarly a pure function with no test coverage.
- The `process()` method in `unified_pipeline.py` has no integration test, even a basic mocked happy-path.
- These are critical pipeline components that determine whether documents are processed and how they are classified.

## Proposed Solutions

1. Add parametrized tests for `is_skippable()` covering:
   - Files that should be skipped (e.g., by extension, by name pattern)
   - Files that should not be skipped
   - Edge cases (empty names, unusual extensions)

2. Add parametrized tests for `detect_governance()` covering:
   - Documents with governance indicators
   - Documents without governance indicators
   - Edge cases and boundary conditions

3. Add a mocked end-to-end test for `process()` with mocked:
   - OCR service
   - Classifier
   - Chunker
   - Embedder
   - Verify the happy-path produces expected `PipelineStageResult` outputs

## Technical Details

- New test files needed in `backend/tests/`
- Use `pytest.mark.parametrize` for the pure function tests.
- Use `unittest.mock.AsyncMock` for the pipeline integration test.
- Follow existing test patterns in the repository.

## Acceptance Criteria

- Unit tests exist for `skip_filter` (`is_skippable()`).
- Unit tests exist for `governance_detector` (`detect_governance()`).
- A mocked integration test exists for `pipeline.process()`.
- All new tests pass in CI.
