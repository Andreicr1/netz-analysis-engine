---
status: pending
priority: p1
issue_id: 126
tags: [code-review, architecture, routing]
---

# Problem Statement

`backend/app/main.py` mounts the exposure router with `prefix="/wealth"` but the router itself already declares `prefix="/exposure"`. This composes to `/api/v1/wealth/exposure/matrix`. Other wealth routers may not follow the same double-prefix pattern, creating routing inconsistency. Frontend loader URLs may be calling the wrong path and receiving 404s silently.

# Findings

- `backend/app/main.py` line ~255 mounts the exposure router with `prefix="/wealth"`.
- `backend/app/domains/wealth/routes/exposure.py` already declares its own `prefix="/exposure"`.
- Composed path becomes `/api/v1/wealth/exposure/...`.
- If other wealth routers are mounted without a `/wealth` prefix in `main.py` (router-internal prefix only), they resolve to `/api/v1/{router-prefix}/...`.
- Inconsistency means some wealth endpoints are under `/api/v1/wealth/` and others are not, making the API surface unpredictable.
- Frontend loaders calling either pattern for the wrong router will silently 404.

# Proposed Solutions

1. **Normalize all wealth routers to use no prefix in `main.py` and carry their own prefix internally.** Mount all wealth routers with `prefix=""` in main.py. Each router owns its full path. Exposure becomes `/api/v1/exposure/matrix`.
2. **Add `/wealth` prefix at mount time for all wealth routers and strip it from individual router declarations.** All wealth routes live under `/api/v1/wealth/`. Exposure becomes `/api/v1/wealth/exposure/matrix`. This is the cleaner namespacing approach.

Option 2 is preferred for multi-vertical API clarity (`/api/v1/wealth/` vs `/api/v1/credit/`).

Regardless of choice: audit ALL wealth router mounts in `main.py` for consistency, then verify all frontend loader fetch URLs match.

# Technical Details

- **Files:**
  - `backend/app/main.py` line ~255
  - `backend/app/domains/wealth/routes/exposure.py`
- **Audit scope:** All `include_router` calls in `main.py` for wealth domain routers.
- **Frontend verification:** Search `frontends/wealth/src` for `/exposure` fetch calls and confirm path matches resolved route.
- **Source:** architecture-strategist, pattern-recognition
