---
status: complete
priority: p3
issue_id: "153"
tags: [code-review, frontend, dark-theme, consistency]
dependencies: []
---

# Wealth FOUC script missing `prefers-color-scheme` fallback

## Problem Statement

Credit's `app.html` FOUC prevention script (from PR #53) includes a `prefers-color-scheme` media query fallback for first-time visitors. Wealth's `app.html` hardcodes `'dark'` as the default for unknown values. Credit's approach is more user-friendly — respecting OS preference. Wealth should be updated to match.

## Findings

- Credit `app.html:14-16`: Falls back to `prefers-color-scheme` for first-time visitors
- Wealth `app.html:12`: `if (theme !== 'dark' && theme !== 'light') theme = 'dark';` — hardcoded default
- Both function correctly; difference affects only first-visit experience
- Plan's research phase identified this improvement (Dark Theme Research)

## Proposed Solutions

### Option 1: Backport `prefers-color-scheme` to Wealth

**Approach:** Update Wealth's `app.html` FOUC script to match Credit's improved pattern, keeping `'dark'` as the fallback when `prefers-color-scheme` is unavailable.

**Effort:** 5 minutes

**Risk:** Low

## Recommended Action

*To be filled during triage.*

## Technical Details

**Affected files:**
- `frontends/wealth/src/app.html`

## Resources

- **PR:** #53

## Acceptance Criteria

- [ ] Wealth `app.html` has `prefers-color-scheme` fallback in FOUC script
- [ ] Default remains `'dark'` when media query unavailable

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code

**Actions:**
- Identified pattern divergence during PR #53 cross-frontend comparison
