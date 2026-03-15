---
status: pending
priority: p2
issue_id: "006"
tags: [code-review, quality]
dependencies: []
---

# ProfileLoader has redundant dual registry dicts

## Problem Statement
`_VERTICAL_REGISTRY` and `_PROFILE_TO_VERTICAL` are two separate dicts that must be kept in sync. Currently profile name equals vertical name in every entry — the second dict is an identity mapping.

## Proposed Solutions
Consolidate into a single registry dataclass or just use profile name directly as vertical name.

## Acceptance Criteria
- [ ] Single source of truth for profile→vertical mapping
- [ ] Cannot add a profile to one dict and forget the other
