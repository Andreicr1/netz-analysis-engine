---
status: pending
priority: p2
issue_id: "121"
tags: [code-review, architecture, import-linter]
dependencies: []
---

# New packages not added to consolidated import-linter contracts

## Problem Statement

`mandate_fit` and `fee_drag` packages have per-package import-linter contracts but were not added to the consolidated contracts at `pyproject.toml` lines 270 and 292 ("Wealth engine models must not import service" and "Wealth domain helpers must not import service within packages"). Previous packages (screener, peer_group, rebalancing) were added to both. This gap also affects the watchlist package from Sprint 4.

The per-package contracts provide equivalent protection, but the consolidated contracts act as a second safety net and maintain the double-ratchet pattern.

## Findings

**Flagged by:** Pattern Recognition Specialist

**Evidence:**
- `pyproject.toml` line 270: consolidated models contract missing mandate_fit, fee_drag, watchlist
- `pyproject.toml` line 292: consolidated helpers contract missing mandate_fit.constraint_evaluator, watchlist.transition_detector

## Proposed Solutions

### Option A: Add all missing modules to consolidated contracts
- **Effort:** Small (10 min)

## Acceptance Criteria

- [ ] mandate_fit.models, fee_drag.models, watchlist.models added to consolidated models contract
- [ ] mandate_fit.constraint_evaluator, watchlist.transition_detector added to consolidated helpers contract
- [ ] mandate_fit.service, fee_drag.service, watchlist.service added to forbidden_modules
- [ ] `lint-imports` still passes

## Work Log

| Date | Action |
|------|--------|
| 2026-03-16 | Created from PR #51 code review |
