---
status: pending
priority: p2
issue_id: "089"
tags: [code-review, project, admin, reverted]
dependencies: ["080", "081", "083"]
---

# PRs #43 and #45 (Admin Backend + Frontend) were merged then reverted

## Problem Statement

PR #43 (Admin Backend APIs: config writer, prompt service, admin routes) and PR #45 (Admin Frontend SvelteKit + review fixes) were merged to main and then immediately reverted. The admin infrastructure (migration 0009, models, branding/asset routes from PR #37) is still on main, but the admin API routes and frontend are missing.

This means the admin vertical is incomplete: the database tables exist but the management APIs and UI are gone. Before re-landing these PRs, the P1 findings from this review should be addressed.

## Findings

- `f3a7585` — Revert of PR #43 (Admin Backend APIs)
- `45ba49c` — Revert of PR #45 (Admin Frontend)
- Reverted code included: config_writer.py, prompt_service.py, admin routes (configs, prompts, tenants, health), admin frontend (SvelteKit app)
- Migration 0009 (tenant_assets, prompt_overrides tables) is STILL applied — tables exist but no API manages them
- The fix commit `f94a477` in PR #45 addressed "13 code review findings (3 P1, 6 P2, 4 P3)" — these fixes are also reverted

## Proposed Solutions

### Option 1: Fix P1 issues, re-land as new PRs

**Approach:** Create new branch from main. Cherry-pick #43/#45 commits. Apply P1 fixes. Open new PR.

**Effort:** 4-6 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- All files from PRs #43 and #45 (see PR file lists above)

## Acceptance Criteria

- [ ] Admin backend APIs re-landed with P1 fixes applied
- [ ] Admin frontend re-landed
- [ ] All 13 previously-identified review findings still resolved

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

## Resources

- **PRs:** #43, #45 (reverted), #44 (closed)
