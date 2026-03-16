---
status: pending
priority: p2
issue_id: "070"
tags: [code-review, quality]
---

# Remove duplicate deactivated-fund check in monitoring

## Problem Statement

Both `alert_engine._check_fund_watchlist()` and `drift_monitor._check_universe_removal_impact()` detect the same condition (deactivated funds in live portfolios) with duplicate logic (~48 lines each). They produce different alert types but check the same thing.

## Findings

- `alert_engine._check_fund_watchlist()` checks for deactivated funds in live portfolios
- `drift_monitor._check_universe_removal_impact()` checks the same condition
- ~48 lines duplicated across the two files
- Both produce alerts but with different alert types
- The drift_monitor version is more semantically appropriate (deactivated fund = universe drift)

## Proposed Solutions

Remove `_check_fund_watchlist` from alert_engine.py. The drift_monitor version is more appropriate since "deactivated fund in portfolio" is a drift/universe concern.

## Technical Details

- Affected files:
  - `alert_engine.py:130-177` (_check_fund_watchlist — to be removed)
  - `drift_monitor.py:121-183` (_check_universe_removal_impact — to be kept)
- Ensure drift_monitor's alert type covers the use cases previously handled by alert_engine
- Update any callers that reference `_check_fund_watchlist`
- ~48 lines removed from alert_engine.py

## Acceptance Criteria

- [ ] `_check_fund_watchlist()` is removed from alert_engine.py
- [ ] drift_monitor's `_check_universe_removal_impact()` covers all deactivated-fund detection
- [ ] No duplicate logic remains for this condition
- [ ] All callers updated to use drift_monitor's version
- [ ] All existing tests pass (update tests that referenced the removed method)

## Work Log

(none yet)
