---
status: pending
priority: p2
issue_id: "108"
tags: [code-review, architecture, import-linter, peer-group]
dependencies: []
---

# peer_injection.py missing from 2 import-linter contracts

## Problem Statement

`peer_injection.py` lives in `vertical_engines/wealth/dd_report/` but is not registered in two existing import-linter contracts that govern dd_report helpers. Without these registrations, `peer_injection.py` could import `dd_report_engine` or any wealth service entry-point without triggering a linter violation, breaking the architectural DAG.

## Findings

- Pattern Recognition Specialist agent identified this gap unanimously
- `quant_injection.py` (the sibling file) IS registered in both contracts
- `peer_injection.py` was created as a separate file specifically to respect import-linter rules, yet was not added to the contracts that enforce the helper pattern

### Missing registrations:

1. **"Wealth dd_report helpers must not import engine"** (pyproject.toml ~line 201-211) — `peer_injection` not in `source_modules`
2. **"Wealth domain helpers must not import service within packages"** (pyproject.toml ~line 288-314) — `peer_injection` not in `source_modules`

## Proposed Solutions

### Option 1: Add peer_injection to both contracts

**Approach:** Add `"vertical_engines.wealth.dd_report.peer_injection"` to `source_modules` in both contracts.

**Effort:** 5 minutes

**Risk:** Low

## Technical Details

**Affected files:**
- `pyproject.toml` — two `[[tool.importlinter.contracts]]` sections

## Resources

- **PR:** #48
- **Agent:** Pattern Recognition Specialist

## Acceptance Criteria

- [ ] `peer_injection.py` registered in "Wealth dd_report helpers must not import engine"
- [ ] `peer_injection.py` registered in "Wealth domain helpers must not import service within packages"
- [ ] `lint-imports` passes with all contracts kept

## Work Log

### 2026-03-16 - Initial Discovery

**By:** Claude Code (Pattern Recognition Specialist review agent)

**Actions:**
- Cross-referenced peer_injection.py against all existing import-linter contracts
- Found 2 missing registrations
