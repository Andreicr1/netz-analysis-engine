---
status: pending
priority: p2
issue_id: "156"
tags: [code-review, security, admin, frontend]
---

# Frontend admin guard checks `actor.role` instead of `actor.roles`

## Problem Statement
`hooks.server.ts` checks `actor.role` (singular string) but the Actor from `createClerkHook` may have `roles` (plural array). Mismatch could block legitimate super-admins or allow regular admins.

## Findings
- `frontends/admin/src/hooks.server.ts`: checks `actor.role !== "super_admin"`
- Backend Actor has `roles: list[Role]`, frontend Actor interface has `role: string`
- Dev mode workaround checks "admin" which would let org-admins through

## Proposed Solution
Verify exact field shape from `createClerkHook`, use `roles.includes("SUPER_ADMIN")` check.
