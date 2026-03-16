---
status: pending
priority: p3
issue_id: "078"
tags: [code-review, architecture]
---

# 078: Missing import-linter contracts for wealth packages

## Problem Statement

pyproject.toml import-linter contracts only enforce helper-to-service invariants for `vertical_engines.credit.*`. The wealth packages follow the same pattern voluntarily but are not CI-enforced.

## Findings

- `pyproject.toml` — import-linter contracts exist for credit packages (helpers must not import service, models must not import service)
- Wealth packages (`vertical_engines.wealth.*`) follow the same convention but have no enforcement
- A future contributor could break the pattern without CI catching it

## Proposed Solutions

Add parallel import-linter contracts for `vertical_engines.wealth.*` packages in pyproject.toml, mirroring the credit contracts.

## Acceptance Criteria

- [ ] import-linter contracts added for wealth packages in pyproject.toml
- [ ] `make check` enforces wealth helper/model import rules
- [ ] Existing code passes the new contracts without changes
