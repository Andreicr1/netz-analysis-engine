---
status: pending
priority: p2
issue_id: "083"
tags: [code-review, architecture, encapsulation]
dependencies: ["081"]
---

# ConfigWriter Directly Imports Private _config_cache

## Problem Statement
`backend/app/core/config/config_writer.py` line 22 imports `_config_cache` (underscore-prefixed private symbol) from `config_service.py`. ConfigWriter has its own `_invalidate_cache` and `_invalidate_cache_prefix` methods that duplicate logic already in `ConfigService.invalidate()`.

## Findings
- **Source:** Kieran Python Reviewer (HIGH), Architecture Strategist (Medium Risk)
- **Impact:** If ConfigService's cache mechanism changes (e.g., from TTLCache to Redis L2 as planned for Sprint 5-6), ConfigWriter's cache invalidation silently breaks.

## Proposed Solutions
### Solution A: Use ConfigService.invalidate() (Recommended)
Replace all direct `_config_cache` access with `ConfigService.invalidate()`. Remove `_invalidate_cache` and `_invalidate_cache_prefix` methods from ConfigWriter.
- **Effort:** Small (30 min)
- **Risk:** Low

## Acceptance Criteria
- [ ] ConfigWriter does not import `_config_cache`
- [ ] All cache invalidation goes through `ConfigService.invalidate()`
- [ ] `_invalidate_cache` and `_invalidate_cache_prefix` removed from ConfigWriter
