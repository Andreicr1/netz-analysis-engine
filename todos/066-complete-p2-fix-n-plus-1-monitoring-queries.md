---
status: pending
priority: p2
issue_id: "066"
tags: [code-review, performance]
---

# Fix N+1 queries in monitoring layer

## Problem Statement

alert_engine.py has N+1 patterns in `_check_dd_expiry()` (queries DDReport per fund), `_check_rebalance_overdue()` (queries RebalanceEvent per portfolio). drift_monitor.py calls `_find_affected_portfolios()` per fund, re-querying all portfolios each time. With 200 funds and 50 portfolios, this produces 250+ queries per scan.

## Findings

- `_check_dd_expiry()` issues one DDReport query per fund
- `_check_rebalance_overdue()` issues one RebalanceEvent query per portfolio
- `_find_affected_portfolios()` is called per fund, re-querying all portfolios each time
- At scale (200 funds, 50 portfolios), this generates 250+ queries per monitoring scan

## Proposed Solutions

Replace per-entity queries with JOIN or subquery patterns. Hoist portfolio query outside the loop in drift_monitor and build an inverted index (fund_id -> [portfolio_ids]). Use LEFT JOIN for DDReport latest per fund.

## Technical Details

- Affected files:
  - `alert_engine.py:75-127` (_check_dd_expiry, _check_rebalance_overdue)
  - `alert_engine.py:180-225`
  - `drift_monitor.py:77-183` (_find_affected_portfolios loop)
- Pattern: replace N individual SELECTs with single JOIN/subquery
- For drift_monitor: load all portfolios once, build dict mapping fund_id to portfolio list
- For alert_engine: use LEFT JOIN to get latest DDReport per fund in one query

## Acceptance Criteria

- [ ] `_check_dd_expiry()` uses a single JOIN query instead of per-fund queries
- [ ] `_check_rebalance_overdue()` uses a single query with JOIN/subquery
- [ ] `_find_affected_portfolios()` query is hoisted outside the per-fund loop
- [ ] Total query count per scan is O(1) not O(N)
- [ ] All existing monitoring tests pass
- [ ] Alert output is identical before and after optimization

## Work Log

(none yet)
