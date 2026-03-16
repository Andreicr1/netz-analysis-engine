---
status: pending
priority: p3
issue_id: "091"
tags: [code-review, duplication, frontend]
dependencies: []
---

# Investor portal layouts and page patterns duplicated across credit/wealth

## Problem Statement

The investor portal pages follow identical patterns across credit and wealth frontends:
- `(investor)/+layout.server.ts` — identical auth check
- `(investor)/+layout.svelte` — identical minimal layout
- `(investor)/documents/+page.server.ts` — same fetch pattern
- `(investor)/documents/+page.svelte` — same table rendering

These could be shared via @netz/ui or a shared investor layout component.

## Findings

- Credit: 3 investor pages (documents, report-packs, statements)
- Wealth: 4 investor pages (documents, fact-sheets, portfolios, reports)
- All use identical patterns: server load → API fetch → table render
- Layout auth check pattern is identical

## Proposed Solutions

### Option 1: Extract shared InvestorLayout and InvestorTable to @netz/ui

**Effort:** 3-4 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/routes/(investor)/**`
- `frontends/wealth/src/routes/(investor)/**`

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

## Resources

- **PRs:** #40, #42 (Phases B+, C+)
