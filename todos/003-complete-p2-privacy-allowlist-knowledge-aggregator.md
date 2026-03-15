---
status: pending
priority: p2
issue_id: "003"
tags: [code-review, security, privacy]
dependencies: []
---

# Knowledge aggregator should use positive allowlist instead of deny list

## Problem Statement
`extract_anonymous_signal()` uses `_FORBIDDEN_FIELDS` (deny list) to check for privacy violations. This only catches exact key names — a field like `"org"` or `"company"` would slip through. A positive allowlist (`_ALLOWED_SIGNAL_FIELDS`) is a stronger privacy invariant.

Additionally, the check only validates top-level keys. Nested dicts with forbidden names would pass.

## Findings
- **Python reviewer:** HIGH — allowlist is stronger than deny list
- **Security reviewer:** confirms deny list is necessary-but-insufficient
- **Architecture reviewer:** MEDIUM — suggests Pydantic model for structural prevention

## Proposed Solutions

### Option A: Add _ALLOWED_SIGNAL_FIELDS allowlist
Verify `signal.keys()` is a subset of allowed fields. Any new field must be explicitly approved.
- **Effort:** Small | **Risk:** Low

### Option B: Define signal as a frozen Pydantic model
Structurally prevents forbidden fields from existing. Strongest guarantee.
- **Effort:** Medium | **Risk:** Low

## Acceptance Criteria
- [ ] Signal output validated against positive allowlist
- [ ] Adding a new field requires explicit approval in allowlist
- [ ] Tests verify allowlist enforcement
