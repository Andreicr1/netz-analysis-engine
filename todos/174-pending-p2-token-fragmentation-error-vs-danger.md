---
id: 174
status: pending
priority: p2
tags: [code-review, quality, design-system]
created: 2026-03-17
---

# Token fragmentation — --netz-status-error vs --netz-danger

## Problem Statement

Two different CSS custom property names are used across frontends for the same semantic meaning (error/danger styling), creating inconsistency in the design system and making future theming changes error-prone.

## Findings

- **Admin pages** use `--netz-danger` for error-related styling (backgrounds, text, borders)
- **Credit and wealth pages** use `--netz-status-error` for error-related styling
- Both tokens map to the same visual intent: indicating errors, failures, or destructive states
- Two names for one concept violates the single-source-of-truth principle of a design system

- **Additionally:** Error variable naming is inconsistent across components:
  - `actionError`, `createError`, `error`, `editError`, `saveError`, `uploadError`
  - While variable names are component-scoped, a consistent convention improves readability

## Proposed Solutions

1. Choose one canonical token name (recommend `--netz-status-error` as it follows the `--netz-status-*` pattern already used for success, warning, info)
2. Alias the deprecated name to the canonical one in `tokens.css` for backward compatibility
3. Migrate all usages to the canonical name across all three frontends
4. Remove the alias after migration is complete
5. Document the token naming convention in the design system

## Acceptance Criteria

- [ ] A single token name is used for error/danger styling across all frontends
- [ ] No direct references to the deprecated token name remain (after alias removal)
- [ ] `tokens.css` documents the canonical error token
- [ ] Error variable naming convention is documented (even if not enforced by lint)
