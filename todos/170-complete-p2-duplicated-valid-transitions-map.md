---
id: 170
status: pending
priority: p2
tags: [code-review, architecture, credit, agent-native]
created: 2026-03-17
---

# Duplicated VALID_TRANSITIONS map — frontend/backend drift risk

## Problem Statement

The frontend duplicates the deal stage transition map that already exists in the backend. This creates a drift risk: if the backend adds or removes valid transitions, the frontend copy goes stale and may allow or block transitions incorrectly.

## Findings

- **Frontend copy:** `frontends/credit/src/lib/types/api.ts` lines 71-80
  - Hardcoded `VALID_TRANSITIONS` map defining which deal stages can transition to which

- **Backend source of truth:** `backend/app/domains/credit/deals/services/stage_transition.py` lines 18-27
  - The authoritative `VALID_TRANSITIONS` map
  - The backend already returns `allowedTransitions` in the stage timeline API response

- The two maps must be kept in sync manually, which is error-prone
- The backend already provides the allowed transitions dynamically via the API, making the frontend copy redundant

## Proposed Solutions

1. Remove the `VALID_TRANSITIONS` constant from `frontends/credit/src/lib/types/api.ts`
2. Rely solely on the `allowedTransitions` field returned by the stage timeline API response
3. Update any frontend logic that references the local constant to use the API-provided data instead
4. If the frontend needs transitions before the API call, fetch them eagerly or show a loading state

## Acceptance Criteria

- [ ] Frontend `VALID_TRANSITIONS` constant is removed
- [ ] All stage transition UI logic derives allowed transitions from the API response
- [ ] No hardcoded transition rules remain in the frontend
- [ ] Stage transition buttons are enabled/disabled based on API-provided `allowedTransitions`
