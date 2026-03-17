---
status: pending
priority: p2
issue_id: "114"
tags: [code-review, architecture, rebalancing]
dependencies: []
---

# detect_regime_trigger passes snapshot_id into affected_portfolios field

## Problem Statement

`service.py` line 169 passes `snapshot_id` values into `RebalanceImpact.affected_portfolios`, which is documented as "model portfolio IDs". Downstream consumers iterating `affected_portfolios` expecting `ModelPortfolio.id` will get wrong results.

```python
affected_portfolios=tuple(s.snapshot_id for s in snapshots[:1]),
```

## Proposed Solutions

### Option A: Look up actual ModelPortfolio IDs for the profile
- Query ModelPortfolio where profile matches and status='active'
- **Effort**: Small

### Option B: Remove detect_regime_trigger (YAGNI)
- No consumer exists yet. Build when wired.
- **Effort**: Small — delete ~55 lines + ~70 lines tests

## Technical Details

- **Affected files**: `backend/vertical_engines/wealth/rebalancing/service.py` line 169

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-16 | Created from PR #49 architecture review | |
