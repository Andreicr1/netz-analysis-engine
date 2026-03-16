---
status: pending
priority: p3
issue_id: "076"
tags: [code-review, security]
---

# 076: Fact-sheet download path validation uses substring check

## Problem Statement

fact_sheets.py line 165 uses `f"/{org_id}/" not in f"/{fact_sheet_path}"` for org validation. A path containing org_id as substring in a different segment could bypass this check.

## Findings

- `fact_sheets.py:164-166` — substring-based org_id validation on storage paths
- A crafted path with org_id appearing in a filename or nested directory could pass validation while belonging to a different tenant

## Proposed Solutions

Parse the path structurally and validate that org_id is in the expected position (e.g., `parts[1]`). Consistent with how `storage_routing.py` builds paths with `{organization_id}/{vertical}/` as prefix.

## Acceptance Criteria

- [ ] Path validation parses path segments and checks org_id at the expected position
- [ ] Substring-based check is removed
- [ ] Unit test verifies that org_id appearing in non-prefix segments is rejected
