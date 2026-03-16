---
status: pending
priority: p1
issue_id: "064"
tags: [code-review, bug]
---

# TODO 064: ReturnMetrics bug — nonexistent sharpe_mean field

## Problem Statement

`backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py` lines 191-193 pass `sharpe_mean=result.mean_sharpe` to `ReturnMetrics()`, but `ReturnMetrics` (frozen dataclass in `models.py`) has no `sharpe_mean` field. This will raise `TypeError: __init__() got an unexpected keyword argument 'sharpe_mean'` at runtime when `compute_backtest()` succeeds with actual data.

## Findings

- **Source:** Code review of PRs #32-#36 (Wealth Vertical Modularization)
- **File:** `backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py:191-196`
- **Severity:** P1 — runtime crash on the backtest-success code path
- **Root cause:** Likely a copy-paste error or field rename that wasn't propagated. `ReturnMetrics` expects fields like `mtd`, `qtd`, `ytd`, `one_year`, `three_year`, `since_inception`, but the code passes `sharpe_mean` which doesn't exist.
- **Additional bug:** `since_inception=result.mean_sharpe` maps a Sharpe ratio value to a return field, which is semantically incorrect even if it didn't crash.

## Proposed Solutions

1. Remove the `sharpe_mean=` keyword argument entirely
2. Map backtest results to the correct `ReturnMetrics` fields (`mtd`, `qtd`, `ytd`, `one_year`, `three_year`, `since_inception`)
3. Populate `since_inception` with the actual since-inception return value from the backtest result, not the Sharpe ratio
4. Add a test that exercises the backtest-success code path to prevent regression

## Technical Details

- `ReturnMetrics` is a frozen dataclass, so invalid keyword arguments raise `TypeError` immediately
- The bug is latent because it only triggers when `compute_backtest()` returns actual data (not `None`)
- The Sharpe ratio should be stored in a risk/performance metrics structure, not in `ReturnMetrics`
- Need to inspect `result` object from `compute_backtest()` to identify the correct field mappings

### Affected files

- `backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py:191-196`
- `backend/vertical_engines/wealth/fact_sheet/models.py` (ReturnMetrics definition)

## Acceptance Criteria

- [ ] `ReturnMetrics` construction uses only valid fields
- [ ] `since_inception` populated with actual return value, not Sharpe ratio
- [ ] Tests cover the backtest-success code path

## Work Log

_(empty — work not yet started)_
