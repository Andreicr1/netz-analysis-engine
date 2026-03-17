---
status: pending
priority: p3
issue_id: "147"
tags: [code-review, architecture, import-linter]
dependencies: []
---

# Monitoring helpers not covered by import-linter contracts

## Problem Statement

`drift_monitor.py` and `alert_engine.py` in the monitoring package are not listed in the consolidated "domain helpers must not import service" contract in pyproject.toml. This leaves a gap in the import architecture safety net.

## Findings

- Found by: pattern-recognition-specialist
- `pyproject.toml` lines 303-337: consolidated helpers contract does not include monitoring helpers
- `monitoring/drift_monitor.py` and `monitoring/alert_engine.py` could import `strategy_drift_scanner` without linter catching it

## Proposed Solutions

### Option 1: Add monitoring helpers to contracts (Recommended)

**Approach:** Add `vertical_engines.wealth.monitoring.drift_monitor` and `vertical_engines.wealth.monitoring.alert_engine` to the source_modules list, with `strategy_drift_scanner` in forbidden_modules.

**Effort:** 10 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `pyproject.toml` (import-linter contracts section)

## Acceptance Criteria

- [ ] drift_monitor and alert_engine listed in linter contracts
- [ ] `lint-imports` passes

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
