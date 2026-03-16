---
status: pending
priority: p2
issue_id: "085"
tags: [code-review, quality, conventions, backend]
dependencies: []
---

# Investor portal routes return raw dicts instead of Pydantic schemas

## Problem Statement

All 3 routes in `investor_portal.py` return `dict[str, Any]` or `list[dict[str, Any]]` with inline dict serialization. This violates the CLAUDE.md critical rule: "All routes use `response_model=` and return via `model_validate()`. No inline dict serialization."

The inline dicts use defensive `hasattr()` checks and manual `.isoformat()` calls — a Pydantic schema with `model_config = ConfigDict(from_attributes=True)` handles this automatically.

## Findings

- `investor_portal.py:63` — `list_published_packs` returns `list[dict[str, Any]]`
- `investor_portal.py:97` — `list_published_statements` returns `dict[str, Any]`
- `investor_portal.py:130` — `list_approved_documents` returns `dict[str, Any]`
- Lines 76-86, 109-119, 144-158: Manual dict construction with `hasattr()` guards
- Also uses `asyncio.ensure_future` (deprecated pattern) instead of `asyncio.create_task`

## Proposed Solutions

### Option 1: Create Pydantic response schemas

**Approach:** Add `InvestorReportPackResponse`, `InvestorStatementResponse`, `InvestorDocumentResponse` schemas. Use `response_model=` on routes.

**Pros:**
- Follows CLAUDE.md conventions
- Automatic serialization, validation, OpenAPI docs
- Removes fragile `hasattr()` checks

**Cons:**
- Small effort to create schemas

**Effort:** 1-2 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `backend/app/domains/credit/reporting/routes/investor_portal.py:55-158`
- `backend/app/domains/admin/schemas.py` (add new schemas)

## Acceptance Criteria

- [ ] All investor portal routes use `response_model=`
- [ ] No inline dict serialization
- [ ] `asyncio.ensure_future` replaced with `asyncio.create_task`
- [ ] Tests pass with new schema validation

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

## Resources

- **PR:** #40 (Phase B+)
- **Rule:** CLAUDE.md "Pydantic schemas" critical rule
