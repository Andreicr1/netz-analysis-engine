---
status: pending
priority: p3
issue_id: "077"
tags: [code-review, security]
---

# 077: DD Report PDF filename allows unsanitized fund_name

## Problem Statement

fact_sheets.py line 254 uses `fund_name.replace(' ', '_')` in Content-Disposition filename. Fund names containing `"` or `\n` could break the HTTP header or enable header injection.

## Findings

- `fact_sheets.py:254` — only spaces are replaced in fund_name before use in Content-Disposition
- Characters like `"`, `\n`, `\r`, `/`, `\` are passed through unsanitized
- Could break Content-Disposition header parsing or enable response splitting

## Proposed Solutions

Sanitize fund_name to alphanumeric + underscore/dash only (e.g., `re.sub(r'[^a-zA-Z0-9_-]', '_', fund_name)`).

## Acceptance Criteria

- [ ] Filename in Content-Disposition is sanitized to `[a-zA-Z0-9_-]` characters only
- [ ] Unit test verifies special characters are stripped
