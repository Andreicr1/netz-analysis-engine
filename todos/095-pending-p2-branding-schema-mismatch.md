---
status: pending
priority: p2
issue_id: "095"
tags: [code-review, architecture, schema-mismatch, frontend, backend]
dependencies: []
---

# BrandingResponse (backend) and BrandingConfig (frontend) have different field names

## Problem Statement

The backend `BrandingResponse` schema has fields like `company_name`, `tagline`, `report_header`, `report_footer`, `email_from_name`. The frontend `BrandingConfig` type has `org_name`, `org_slug`, `primary_color`, `secondary_color`, `light_color`, `highlight_color`. These schemas share almost no field names.

The frontend calls `api.get<BrandingConfig>("/branding")` — the TypeScript generic cast silently produces an object where most fields are `undefined` because the backend response field names don't match. The migration seeds `primary_color: "#1a1a2e"` but the frontend default is `"#1B365D"`.

The branding system only works via the fallback path (`catch → defaultBranding`).

## Findings

- `backend/app/domains/admin/schemas.py` — `BrandingResponse` fields
- `packages/ui/src/lib/utils/types.ts` — `BrandingConfig` fields
- `backend/app/core/db/migrations/versions/0009_admin_infrastructure.py` — seeds different colors than frontend defaults
- Frontend `+layout.server.ts` uses `defaultBranding` fallback on API error — this is why it appears to work

**Source:** Architecture Strategist + Pattern Recognition agents

## Proposed Solutions

### Option 1: Align schemas — make BrandingConfig match BrandingResponse

**Effort:** 2-3 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `backend/app/domains/admin/schemas.py`
- `packages/ui/src/lib/utils/types.ts`
- `packages/ui/src/lib/utils/branding.ts`
- `backend/app/core/db/migrations/versions/0009_admin_infrastructure.py`

## Acceptance Criteria

- [ ] Frontend BrandingConfig and backend BrandingResponse have matching field names
- [ ] Default branding colors consistent between migration seed and frontend defaults
- [ ] Branding API response properly consumed by frontend (not relying on fallback)

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Architecture Strategist + Pattern Recognition agents

## Resources

- **PRs:** #37 (Phase A)
