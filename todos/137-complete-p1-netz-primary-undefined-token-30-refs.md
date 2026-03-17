---
status: complete
priority: p1
issue_id: 137
tags: [code-review, css, tokens, dark-theme]
---

# Problem Statement

`var(--netz-primary)` is referenced in 30+ places across wealth and credit frontends, but this token **does not exist** in `tokens.css`. Only `--netz-brand-primary` exists. On dark theme, all these references resolve to nothing — invisible text, invisible buttons, invisible borders.

# Findings

**Wealth (new code from this PR):**
- `screener/+page.svelte` — 14 references (agent-generated with wrong token)
- `allocation/+page.svelte` — 3 references (pre-existing, not fixed)
- `+error.svelte` — 3 references
- `sign-in/+page.svelte` — 1 reference
- `(investor)/documents/+page.svelte` — 1 reference

**Credit (pre-existing, same issue):**
- `+error.svelte` — 3
- `CopilotChat.svelte` — 2
- `ICMemoViewer.svelte` — 1
- `ICMemoStreamingChapter.svelte` — 1
- `copilot/+page.svelte` — 2
- `funds/[fundId]/+layout.svelte` — 2
- `documents/upload/+page.svelte` — 1

# Proposed Solutions

## Option A: Add alias in tokens.css (fastest)
Add `--netz-primary: var(--netz-brand-primary);` to both `:root` and `[data-theme="dark"]` blocks.
- Pros: Zero file changes across frontends, backward compatible
- Cons: Two names for the same token, minor confusion

## Option B: Replace all references (thorough)
`sed` all `var(--netz-primary)` → `var(--netz-brand-primary)` across both frontends.
- Pros: Single source of truth, no alias
- Cons: Touches 30+ files including credit (larger blast radius)

## Recommended: Option A now + Option B as follow-up

# Technical Details
- **Affected files:** 30+ across wealth + credit frontends
- **Root cause:** tokens.css only defines `--netz-brand-primary`, not `--netz-primary`
- **Severity:** P1 — buttons, active states, and borders invisible on dark theme
