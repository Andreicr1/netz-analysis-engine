---
status: pending
priority: p2
issue_id: "005"
tags: [code-review, performance]
dependencies: []
---

# ProfileLoader makes two sequential ConfigService calls

## Problem Statement
`ProfileLoader.load()` makes two sequential `await self._config.get()` calls (chapters + calibration). These are independent and can be parallelized with `asyncio.gather()`, halving latency on cache miss.

## Proposed Solutions
```python
chapters_config, calibration = await asyncio.gather(
    self._config.get(vertical, "chapters", org_id),
    self._config.get(vertical, "calibration", org_id),
)
```

**Effort:** Small (5-minute change) | **Risk:** None

## Acceptance Criteria
- [ ] Both config calls execute in parallel
- [ ] Tests still pass
