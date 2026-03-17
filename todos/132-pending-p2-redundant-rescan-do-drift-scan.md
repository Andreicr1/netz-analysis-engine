---
status: pending
priority: p2
issue_id: 132
tags: [code-review, performance, simplicity]
---

# Problem Statement

`_do_drift_scan` in the strategy drift route calls `scan_all_strategy_drift` (which returns only instruments with `drift_detected=True`), then re-scans every instrument that was NOT in that result set to determine stable/insufficient status. This doubles the CPU cost of every scan. Additionally, the membership check uses `any()` on a list, making it O(N*M) in instrument count.

# Findings

- `backend/app/domains/wealth/routes/strategy_drift.py` lines 244-256 implement the re-scan pattern.
- `scan_all_strategy_drift` returns only alerts (drifted instruments). All others require individual re-scanning.
- For a portfolio with 100 instruments: if 10 are drifted, the remaining 90 get individually re-scanned, adding ~90 unnecessary analysis calls.
- The `any(inst.id == ... for inst in drift_results)` pattern is O(N) per lookup, making the full loop O(N*M) where N = total instruments and M = drifted count.
- With 100 instruments and 10 drifted: 100 * 10 = 1,000 comparisons just for membership testing.

# Proposed Solutions

**Fix 1: Modify `scan_all_strategy_drift` to return all results.**
Change the return type to include ALL instruments with their status (drifted / stable / insufficient), not just drifted ones. This eliminates the re-scan loop entirely — one call, complete picture.

**Fix 2: Replace `any()` list scan with set lookup.**
Until Fix 1 is implemented, convert drift results to a set of IDs for O(1) lookup:
```python
drifted_ids = {inst.id for inst in drift_results}
is_drifted = instrument_id in drifted_ids  # O(1) vs O(N)
```

Both fixes should be applied together. Fix 1 is the structural improvement; Fix 2 is a quick win that reduces algorithmic complexity independently.

# Technical Details

- **File:** `backend/app/domains/wealth/routes/strategy_drift.py` lines 244-256
- **Current complexity:** O(N) re-scans + O(N*M) membership checks
- **Target complexity:** 1 full scan call + O(1) lookups
- **Related function:** `scan_all_strategy_drift` in the strategy drift service
- **Source:** code-simplicity-reviewer, architecture-strategist
