---
status: pending
priority: p2
issue_id: "067"
tags: [code-review, performance]
---

# Duplicate backtest computation in FactSheetEngine

## Problem Statement

`_compute_returns()` and `_compute_risk()` in fact_sheet_engine.py both independently call `compute_backtest()` with identical arguments. This runs the same expensive DB query + NumPy walk-forward backtest twice per fact-sheet generation.

## Findings

- `_compute_returns()` calls `compute_backtest()` to get return series
- `_compute_risk()` calls `compute_backtest()` again with the same arguments to get risk metrics
- `compute_backtest()` involves a DB query and NumPy walk-forward computation
- Every fact-sheet generation pays the cost of this expensive operation twice

## Proposed Solutions

Call `compute_backtest()` once in `_build_fact_sheet_data()`, pass the `BacktestResult` to both `_compute_returns` and `_compute_risk`.

## Technical Details

- Affected file: `fact_sheet_engine.py:169-233`
- `_build_fact_sheet_data()` should call `compute_backtest()` once and store the result
- `_compute_returns(backtest_result)` receives pre-computed data
- `_compute_risk(backtest_result)` receives pre-computed data
- Both methods extract what they need from the shared `BacktestResult`

## Acceptance Criteria

- [ ] `compute_backtest()` is called exactly once per fact-sheet generation
- [ ] `_compute_returns` and `_compute_risk` accept a `BacktestResult` parameter
- [ ] Fact-sheet output is identical before and after the change
- [ ] All existing tests pass
- [ ] Measurable reduction in fact-sheet generation time

## Work Log

(none yet)
