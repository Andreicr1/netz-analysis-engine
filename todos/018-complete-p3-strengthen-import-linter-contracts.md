---
status: complete
priority: p3
issue_id: "018"
tags: [code-review, architecture, ci]
dependencies: []
---

# Strengthen import-linter contracts for full DAG enforcement

## Problem Statement

The current "Engine domain modules must not import service" contract only checks `models -> service`. It does not enforce that other domain modules (parser.py, classifier.py, etc.) cannot import service.py. No contract prevents reverse-tier imports (e.g., evidence.py importing chapters.py within memo/).

## Findings

- Current contract: `source_modules = ["vertical_engines.credit.*.models"]` forbidden from service
- Missing: broader domain module → service prohibition
- Missing: intra-package tier enforcement
- No violations exist today, but the constraint is unguarded for future contributors
- pyproject.toml line 119 comment is stale ("currently matches edgar/ only" — now covers 12 packages)
- Found by: architecture-strategist

## Proposed Solutions

### Option 1: Broaden forbidden imports contract

**Approach:** Add contracts for `*.parser`, `*.classifier`, etc. or use a broader pattern. Update stale comment.

**Effort:** 30 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `pyproject.toml` — import-linter contracts section

## Acceptance Criteria

- [ ] All domain modules (not just models) are forbidden from importing service
- [ ] Stale comment updated
- [ ] `make architecture` passes

## Work Log

### 2026-03-15 - Code Review Discovery

**By:** Claude Code (ce:review)
