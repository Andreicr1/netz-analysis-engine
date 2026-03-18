---
status: complete
priority: p2
issue_id: "191"
tags: [code-review, architecture, wealth, frontend]
dependencies: []
---

# Wealth error page uses wrong CSS variable name

## Problem Statement

The wealth `+error.svelte` uses `var(--netz-primary)` while credit and admin use `var(--netz-brand-primary)`. The token system defines `--netz-brand-primary`, not `--netz-primary`. Buttons may render with no background color when branding is active.

## Findings

- `frontends/wealth/src/routes/+error.svelte` — uses `--netz-primary` (incorrect)
- `frontends/credit/src/routes/+error.svelte` — uses `--netz-brand-primary` (correct)
- `frontends/admin/src/routes/+error.svelte` — uses `--netz-brand-primary` (correct)
- `packages/ui/src/lib/styles/tokens.css` defines `--netz-brand-primary`

## Proposed Solutions

### Option 1: Fix CSS variable name

**Approach:** Replace `--netz-primary` with `--netz-brand-primary`.

**Effort:** 5 minutes

**Risk:** None

## Recommended Action

## Technical Details

**Affected files:**
- `frontends/wealth/src/routes/+error.svelte`

## Acceptance Criteria

- [ ] All styles use `--netz-brand-primary`
- [ ] Error page renders with correct brand colors

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — pattern-recognition + architecture agents)
