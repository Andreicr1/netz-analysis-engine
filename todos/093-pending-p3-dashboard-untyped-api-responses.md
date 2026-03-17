---
status: done
priority: p3
issue_id: "093"
tags: [code-review, quality, type-safety, frontend]
dependencies: []
---

# Dashboard and pages use untyped API responses (Record<string, unknown>)

## Problem Statement

Frontend pages cast API responses to `Record<string, unknown>` and access properties with optional chaining (`portfolio?.total_aum`). This provides no compile-time type safety. The dashboard alone has 20+ untyped property accesses.

## Findings

- `frontends/credit/src/routes/(team)/dashboard/+page.svelte:16-19` — 4 `as Record<string, unknown>` casts
- Similar pattern across all team view pages
- No TypeScript interfaces for API response shapes
- `as unknown[]` casts for list responses

## Proposed Solutions

### Option 1: Create TypeScript interfaces for all API response types

**Approach:** Define interfaces matching backend Pydantic schemas. Use them in load functions.

**Effort:** 3-4 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- All `+page.svelte` files in credit and wealth frontends

## Acceptance Criteria

- [ ] TypeScript interfaces for all API response types
- [ ] No `as Record<string, unknown>` casts in page components

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

## Work Log

### 2026-03-16 - Resolution

**By:** Claude Code

**Actions:**
- Created `frontends/credit/src/lib/types/api.ts` with 20+ interfaces: PortfolioSummary, PipelineSummary, PipelineAnalytics, MacroSnapshot, TaskItem, DealDetail, StageTimelineEntry, PaginatedResponse<T>, PortfolioAsset, PortfolioObligation, PortfolioAlert, PortfolioAction, DocumentItem, ReviewItem, ReviewSummary, ReviewDetail, ReviewAssignment, ReviewChecklist, ChecklistItem, NavSnapshot, ReportPack, ICMemo, ICMemoChapter, VotingStatus, Citation
- Created `frontends/wealth/src/lib/types/api.ts` with RegimeData (wealth dashboard already had inline types for others)
- Updated 10 Svelte files to replace `Record<string, unknown>` with typed interfaces
- ICMemoViewer and CopilotCitation now have properly typed props instead of `unknown`

## Resources

- **PRs:** #39, #41
