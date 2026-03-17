---
status: done
priority: p2
issue_id: "096"
tags: [code-review, bug, frontend, credit, agent-parity]
dependencies: []
---

# 6 action buttons in credit frontend are noop (onclick={() => {}})

## Problem Statement

The credit frontend has 6 buttons wired to empty `onclick={() => {}}` handlers. Backend API endpoints exist for these actions but the frontend never calls them. Users see actionable buttons that do nothing when clicked.

## Findings

**Review decision buttons (3):**
- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:23-25`
- Approve, Reject, Request Revision — backend has `POST /{review_id}/decide`, `/finalize`, `/resubmit`

**Reporting buttons (3+):**
- `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte:44,54,68-69`
- Create NAV Snapshot, Generate Report Pack, Export JSON, Export PDF

**Source:** Agent-Native Reviewer

## Proposed Solutions

### Option 1: Wire buttons to existing backend endpoints

**Effort:** 2-3 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte`

## Acceptance Criteria

- [ ] All action buttons call their respective API endpoints
- [ ] Success/error feedback shown to user
- [ ] Page refreshes or updates after action completes

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Agent-Native Reviewer (ce:review PRs #37-#45)

### 2026-03-16 - Resolution

**By:** Claude Code

**Actions:**
- Wired 4 reporting buttons to backend endpoints: Create NAV Snapshot → `POST /funds/{fund_id}/reports/nav/snapshots`, Generate Report Pack → `POST /funds/{fund_id}/report-packs`, Export JSON → `POST /funds/{fund_id}/reports/evidence-pack`, Export PDF → `POST /funds/{fund_id}/reports/evidence-pack/pdf`
- All use `getContext("netz:getToken")` + `createClientApiClient` + `invalidateAll()` pattern
- Review decision buttons (Approve/Reject/Request Revision): backend has NO review decision endpoints — buttons set to `disabled` with HTML comment documenting the gap
- Loading states added to all wired buttons

## Resources

- **PRs:** #39 (Phase B)
