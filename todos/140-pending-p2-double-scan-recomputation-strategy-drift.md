---
status: pending
priority: p2
issue_id: "140"
tags: [code-review, performance]
dependencies: []
---

# Double computation of stable/insufficient instruments in drift scan

## Problem Statement

`_do_drift_scan` calls `scan_all_strategy_drift()` which processes ALL instruments internally, then the route re-computes `scan_strategy_drift()` for every non-alert instrument. Every stable/insufficient instrument is scanned twice. For 200 instruments with only 5 drifting, 195 are redundantly recomputed.

## Findings

- Found by: performance-oracle (CRITICAL-4), kieran-python-reviewer, code-simplicity-reviewer (3 agents)
- `backend/app/domains/wealth/routes/strategy_drift.py` lines 244-256
- `scan_all_strategy_drift` already processes every instrument but only returns drift_detected in alerts
- Route then re-imports `scan_strategy_drift` and loops again for stable/insufficient instruments
- `any(a.instrument_id == inst_id_str for a in scan_result.alerts)` is O(A) per instrument, making total O(N*A)

## Proposed Solutions

### Option 1: Return all results from scan_all (Recommended)

**Approach:** Add `all_results` field to `StrategyDriftScanResult` containing all results (not just alerts). Eliminates the second loop entirely.

**Pros:** Removes N redundant computations, cleaner code

**Cons:** Minor change to scan_all_strategy_drift signature

**Effort:** 30 minutes
**Risk:** Low

### Option 2: Compute all individually in the route

**Approach:** Don't use scan_all at all — compute each instrument individually in the route and partition results.

**Pros:** Single pass, no scan_all dependency

**Cons:** Removes batch processing abstraction

**Effort:** 30 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/routes/strategy_drift.py` lines 244-256
- `backend/vertical_engines/wealth/monitoring/strategy_drift_scanner.py` (scan_all_strategy_drift)

## Acceptance Criteria

- [ ] Each instrument processed exactly once
- [ ] All results (drift, stable, insufficient) persisted
- [ ] Tests pass

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
