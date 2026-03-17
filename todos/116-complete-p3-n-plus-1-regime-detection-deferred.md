---
status: pending
priority: p3
issue_id: "116"
tags: [code-review, performance, rebalancing]
dependencies: ["115"]
---

# N+1 query pattern in regime detection

## Problem Statement

`detect_regime_trigger()` queries for distinct profiles, then executes a separate query per profile. With 20 profiles = 21 queries. Could be a single window function query.

## Proposed Solutions

Use `row_number() OVER (PARTITION BY profile ORDER BY snapshot_date DESC)` to get latest N snapshots per profile in one query.

Note: If #115 (YAGNI removal) is accepted, this becomes moot.

## Technical Details

- **Affected files**: `backend/vertical_engines/wealth/rebalancing/service.py` lines 126-157

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-16 | Created from PR #49 performance review | |
