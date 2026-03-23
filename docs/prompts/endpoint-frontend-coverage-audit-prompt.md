# Endpoint ↔ Frontend Coverage Audit — Implementation Prompt

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Goal

Map every backend endpoint to its frontend consumer (or lack thereof). Produce a coverage report identifying:

1. **Connected endpoints** — backend route has a matching frontend `api.get/post/put/patch/delete` call
2. **Disconnected endpoints** — backend route exists but NO frontend page calls it
3. **Phantom frontend calls** — frontend calls an API path that doesn't match any backend route
4. **UX gaps** — endpoints that SHOULD have a frontend surface but don't (new features without UI)

The output is a markdown file at `docs/audit/endpoint-frontend-coverage-audit.md`.

---

## Scope

### Backend routes to scan

All routes registered in these route files:

```
# Wealth domain
backend/app/domains/wealth/routes/
  allocation.py         # /allocation/*
  analytics.py          # /analytics/*
  attribution.py        # /analytics/attribution/*
  content.py            # /content/*
  correlation_regime.py # /analytics/correlation-regime/*
  dd_reports.py         # /dd-reports/*
  documents.py          # /documents/* (NEW — 2026-03-19)
  exposure.py           # /wealth/exposure/*
  fact_sheets.py        # /fact-sheets/*
  funds.py              # /funds/* (DEPRECATED — use instruments)
  instruments.py        # /instruments/* (includes import/yahoo, import/csv)
  macro.py              # /macro/*
  model_portfolios.py   # /model-portfolios/*
  portfolios.py         # /portfolios/*
  risk.py               # /risk/*
  screener.py           # /screener/*
  strategy_drift.py     # /analytics/strategy-drift/*
  universe.py           # /universe/*
  workers.py            # /workers/* (9 worker endpoints)

# Credit domain (for completeness)
backend/app/domains/credit/

# Admin domain
backend/app/domains/admin/ or wherever admin routes live
```

### Frontend files to scan

```
# Wealth frontend
frontends/wealth/src/routes/**/+page.svelte        # UI pages
frontends/wealth/src/routes/**/+page.server.ts      # Server-side data loading
frontends/wealth/src/lib/stores/*.svelte.ts          # Client-side stores
frontends/wealth/src/lib/components/*.svelte          # Components with API calls
frontends/wealth/src/lib/api/client.ts               # API client base

# Credit frontend
frontends/credit/src/routes/**/+page.svelte
frontends/credit/src/routes/**/+page.server.ts
frontends/credit/src/lib/

# Admin frontend
frontends/admin/src/routes/**/+page.svelte
frontends/admin/src/routes/**/+page.server.ts
```

---

## Method

### Step 1: Extract all backend routes

For each route file, extract:
- HTTP method (GET/POST/PUT/PATCH/DELETE)
- Full path (including prefix from router registration in `__init__.py` or `main.py`)
- Function name
- Brief description (from docstring or function name)

Build a complete list. Cross-reference with `backend/manifests/routes.json` if it exists, but prefer source code as the authoritative source (routes.json may be stale).

### Step 2: Extract all frontend API calls

Scan all `.svelte` and `.ts` files for patterns:
- `api.get("...")`, `api.post("...")`, `api.put("...")`, `api.patch("...")`, `api.delete("...")`
- `fetch(\`${apiBase}/...`)` or `fetch("/api/...")`
- SSE connections (`ReadableStream`, `EventSource`)

For each call, record:
- HTTP method
- API path (resolve template literals like `${fundId}` to `{fundId}`)
- Source file and line number
- Context (which page/component makes this call)

### Step 3: Cross-reference and classify

For each backend route, mark one of:
- **CONNECTED** — at least one frontend file calls this exact path
- **DISCONNECTED** — no frontend consumer found
- **WORKER-ONLY** — intended for background processing, no direct UI (workers are OK to be disconnected)
- **ADMIN-ONLY** — consumed by admin frontend only

For each frontend call, mark one of:
- **MATCHED** — maps to a real backend route
- **PHANTOM** — no matching backend route (broken or stale reference)

### Step 4: Identify UX gaps

For disconnected endpoints, classify:
- **Needs UX** — this is a user-facing feature that should have a UI surface
- **API-only OK** — this is a programmatic/internal endpoint, no UI needed
- **Future** — planned for a future sprint, no UI yet (acceptable)

Pay special attention to these recently added endpoints that likely need UX:
- `POST /documents/upload-url` + `POST /documents/upload-complete` — wealth document upload flow
- `GET /documents` + `GET /documents/{id}` — wealth document listing
- `POST /documents/ingestion/process-pending` — trigger document pipeline
- `POST /instruments/import/yahoo` — bulk import from Yahoo Finance
- `POST /instruments/import/csv` — bulk import from CSV
- `POST /workers/run-*` — 9 worker endpoints (some may need admin UI triggers)

---

## Output Format

Write the report to `docs/audit/endpoint-frontend-coverage-audit.md`:

```markdown
# Endpoint ↔ Frontend Coverage Audit

**Generated:** {date}
**Backend routes:** {count}
**Frontend API calls:** {count}
**Connected:** {count} | **Disconnected:** {count} | **Phantom:** {count}

## Summary

{3-5 sentences summarizing the state of coverage}

## Coverage Matrix — Wealth

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | /instruments | instruments/+page.server.ts | CONNECTED |
| POST | /instruments/import/yahoo | — | DISCONNECTED (Needs UX) |
| ... | ... | ... | ... |

## Coverage Matrix — Credit

(same format)

## Coverage Matrix — Admin

(same format)

## Disconnected Endpoints (Needs UX)

| Route | Why it needs UX | Suggested page/component |
|-------|----------------|-------------------------|
| POST /documents/upload-url | Wealth document upload flow | documents/upload/+page.svelte |
| ... | ... | ... |

## Phantom Frontend Calls

| Frontend File | API Call | Issue |
|--------------|----------|-------|
| ... | ... | No matching backend route |

## Workers — UI Trigger Status

| Worker Endpoint | Has Admin/UI Trigger? | Notes |
|----------------|----------------------|-------|
| POST /workers/run-ingestion | ? | Legacy NAV fetch |
| ... | ... | ... |
```

---

## Critical Rules

- Do NOT modify any code — this is a read-only audit
- Do NOT guess API paths — only report what you find in source code
- Include line numbers for every frontend API call found
- If a route path uses FastAPI path parameters like `{fund_id}`, match against frontend patterns like `${fundId}` or `${params.fundId}`
- The wealth frontend API client prepends `/api/v1/wealth/` to relative paths — so `api.get("/funds")` = `GET /api/v1/wealth/funds`
- The credit frontend may use a different base path — check its client.ts
- Admin frontend may use `/api/v1/admin/` — check its client.ts

## What NOT to Do

- Do not create or modify code
- Do not run the app or make HTTP requests
- Do not create new frontend pages or components
- Do not modify routes.json
- Do not guess — if unsure whether a frontend call matches a backend route, mark it as UNCERTAIN
