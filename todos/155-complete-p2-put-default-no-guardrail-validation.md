---
status: pending
priority: p2
issue_id: "155"
tags: [code-review, security, admin]
---

# `put_default()` has no guardrail validation

## Problem Statement
`ConfigWriter.put()` validates against guardrails and branding validators, but `put_default()` writes to `VerticalConfigDefault` without any validation. A super-admin could write malformed defaults that cascade to all tenants.

## Findings
- `backend/app/core/config/config_writer.py`: `put_default()` skips validation
- Same guardrail + branding validation logic should apply

## Proposed Solution
Apply same guardrail + branding validation from `put()` to `put_default()`.
