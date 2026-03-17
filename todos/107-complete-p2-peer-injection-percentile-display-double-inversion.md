---
status: pending
priority: p2
issue_id: "107"
tags: [code-review, quality, peer-group, correctness]
dependencies: []
---

# peer_injection.py percentile display logic may double-invert for lower_is_better metrics

## Problem Statement

In `peer_injection.py:69`, the annotation percentile display applies different logic for `lower_is_better` vs normal metrics, but the `percentile` value in `MetricRanking` has ALREADY been inverted for `lower_is_better` metrics in `service.py:257-258`. This means:

- For `sharpe_ratio` (higher=better), percentile=77 → display: `round(100 - 77) = 23` → "top 23%" (correct)
- For `max_drawdown_pct` (lower=better), service already inverted: percentile=65 → display: `round(65) = 65` → "top 65%"

The second case is semantically confusing: "top 65%" means the instrument is at the 65th percentile after inversion, which means it's in the top 35%. The display should say "top 35%".

## Findings

- `service.py:257-258` — percentile already inverted: `pctile = 100.0 - pctile` for lower_is_better
- `peer_injection.py:69` — display logic: `round(100.0 - r.percentile) if not r.lower_is_better else round(r.percentile)`
- For higher-is-better: percentile=77 means "77th percentile" → top 23% (100-77) ✓
- For lower-is-better: percentile=65 means "65th percentile after inversion" → top 35% (100-65) but display shows "top 65%" ✗
- The `if not r.lower_is_better` branch is correct; the `else` branch should also use `100 - percentile`

## Proposed Solutions

### Option 1: Uniform "top X%" calculation

**Approach:** Always use `round(100.0 - r.percentile)` for the "top X%" display, regardless of lower_is_better. The percentile is already normalized by the service.

**Pros:**
- Consistent semantics: "top X%" always means "better than (100-X)% of peers"
- Simpler code (remove the conditional)

**Cons:**
- None

**Effort:** 5 minutes

**Risk:** Low

## Technical Details

**Affected files:**
- `backend/vertical_engines/wealth/dd_report/peer_injection.py:69`

**Fix:**
```python
# Before:
pctile_display = round(100.0 - r.percentile) if not r.lower_is_better else round(r.percentile)

# After:
pctile_display = round(100.0 - r.percentile)
```

## Resources

- **PR:** #48

## Acceptance Criteria

- [ ] "top X%" always means "better than (100-X)% of peers"
- [ ] Annotations are semantically correct for both higher-is-better and lower-is-better metrics
- [ ] Tests updated to verify annotation correctness

## Work Log

### 2026-03-16 - Initial Discovery

**By:** Claude Code (code review of PR #48)

**Actions:**
- Traced percentile flow from service.py inversion through peer_injection.py display
- Identified double-inversion bug for lower_is_better metrics
