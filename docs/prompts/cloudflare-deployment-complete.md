# Prompt: Complete Cloudflare Deployment

## Context

The Netz Analysis Engine needs full deployment to Cloudflare. Partial deployment was done 17h ago — the gateway worker and cron worker deployed successfully, but the backend container never came up, and the 3 Pages frontends have no Git connection.

**Current Cloudflare state (from dashboard):**
- `netz-gateway` — deployed, 0 bindings (missing WORKER_SECRET)
- `netz-cron` — deployed, 0 bindings (missing WORKER_SECRET)
- `netz-backend` — container NOT running (never built/pushed)
- `netz-credit` — Pages project exists, no Git connection
- `netz-wealth` — Pages project exists, no Git connection
- `netz-admin` — Pages project exists, no Git connection

**Backend is confirmed working locally** with the prod Timescale Cloud DB (16,606 SEC managers, all migrations applied).

## What Needs to Happen

### Phase 1: Backend Container (Critical Path)

The backend runs as a Docker container on Cloudflare Containers.

**Dockerfile:** `infra/cloudflare/Dockerfile`
```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[ai,quant,edgar]"
COPY backend/ backend/
COPY profiles/ profiles/
COPY calibration/ calibration/
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

**Known issues to fix BEFORE building:**
1. `profiles/` and `calibration/` directories DON'T EXIST in the repo. The Dockerfile COPY will fail. Either create empty directories or remove those COPY lines (ConfigService falls back to DB, which is populated).
2. `pyproject.toml` requires Python >=3.12 — the Dockerfile uses 3.12-slim, OK.
3. The `pip install -e ".[ai,quant,edgar]"` needs the backend source mounted. Since COPY pyproject.toml happens before COPY backend/, the editable install won't work. Change to: `pip install --no-cache-dir ".[ai,quant,edgar]"` (non-editable) or restructure the COPY order.

**Secrets needed for backend container** (all in `.env.production`):
- DATABASE_URL, REDIS_URL, OPENAI_API_KEY, MISTRAL_API_KEY
- CLERK_SECRET_KEY, CLERK_JWKS_URL
- R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
- WORKER_DISPATCH_SECRET, FRED_API_KEY, EDGAR_IDENTITY
- APP_ENV=production, FEATURE_R2_ENABLED=true, R2_ACCOUNT_ID

**DB state:** Timescale Cloud at `nvhhm6dwvh.keh9pcdgv1.tsdb.cloud.timescale.com:30124/tsdb`. All migrations applied (head: `0042_bis_imf_hypertables`). Seed data complete including `(liquid_funds, chapters)`.

**PgNotifier SSL issue:** The `PgNotifier` class uses raw `asyncpg.connect()` with the `?ssl=true` param which asyncpg rejects (needs `sslmode=require` instead of `ssl=true`). This causes reconnect spam in logs but doesn't break functionality — it's a background LISTEN/NOTIFY for config cache invalidation. Fix: in `backend/app/core/config/pg_notify.py`, convert `?ssl=true` to `sslmode=require` in the DSN before passing to `asyncpg.connect()`.

### Phase 2: Worker Secrets

Both workers are deployed but have 0 bindings. They need the `WORKER_SECRET`:

```bash
cd infra/cloudflare/gateway
echo "Gwq3H8bEhDqOCVIks8Xd4dJZugKTrl_KlfX54jYyi7c" | npx wrangler secret put WORKER_SECRET

cd infra/cloudflare/cron
echo "Gwq3H8bEhDqOCVIks8Xd4dJZugKTrl_KlfX54jYyi7c" | npx wrangler secret put WORKER_SECRET
```

**Gateway wrangler.toml** has `BACKEND_ORIGIN = "https://netz-backend.andrei-rachadel.workers.dev"` — verify this matches the actual container URL after deployment.

### Phase 3: Pages Frontends (3 apps)

All three use `@sveltejs/adapter-cloudflare` (already configured in `svelte.config.js`).

**Build commands:**
| Project | Root dir | Build command | Output dir |
|---------|----------|---------------|------------|
| netz-credit | `frontends/credit` | `pnpm install && pnpm build` | `.svelte-kit/cloudflare` |
| netz-wealth | `frontends/wealth` | `pnpm install && pnpm build` | `.svelte-kit/cloudflare` |
| netz-admin | `frontends/admin` | `pnpm install && pnpm build` | `.svelte-kit/cloudflare` |

**Env vars for each Pages project:**
- `PUBLIC_BACKEND_URL` = `https://api.netz.app` (or gateway worker URL)
- `PUBLIC_CLERK_PUBLISHABLE_KEY` = `pk_test_Y2FwaXRhbC10YXJwb24tNDIuY2xlcmsuYWNjb3VudHMuZGV2JA`

**Git connection:** Each Pages project needs GitHub repo connection in the Cloudflare Dashboard. The monorepo has all 3 frontends — configure root dir per app.

**IMPORTANT — Monorepo pnpm workspace:** The frontends depend on `@netz/ui` from `packages/ui/`. Cloudflare Pages needs to install from the monorepo root first, then build the specific frontend. The build command should be:
```
cd ../.. && pnpm install --frozen-lockfile && cd frontends/wealth && pnpm build
```
Or use the root Makefile: `make build-all` builds everything in topological order.

### Phase 4: DNS

Run `infra/cloudflare/provision-dns.sh` or manually create:
- `api.netz.app` → CNAME → `netz-gateway.andrei-rachadel.workers.dev` (proxied)
- `credit.netz.app` → Pages custom domain
- `wealth.netz.app` → Pages custom domain
- `admin.netz.app` → Pages custom domain

### Phase 5: CI/CD (GitHub Actions)

`.github/workflows/deploy.yml` exists but needs GitHub secrets:
- `CF_API_TOKEN` — Cloudflare API token with Workers + Containers + R2 permissions
- `CF_ACCOUNT_ID` = `a44ddf3ff0612bc0f62d1ee86f465ac9`

```bash
gh secret set CF_ACCOUNT_ID --body "a44ddf3ff0612bc0f62d1ee86f465ac9"
# CF_API_TOKEN must be created at dash.cloudflare.com/profile/api-tokens
```

## Files Reference

| File | Purpose |
|------|---------|
| `infra/cloudflare/Dockerfile` | Backend container image |
| `infra/cloudflare/gateway/` | API gateway worker (proxy + /internal/ auth) |
| `infra/cloudflare/cron/` | Cron worker (scheduled dispatch) |
| `infra/cloudflare/provision.sh` | Full provisioning script (R2 + workers + containers + pages + GitHub) |
| `infra/cloudflare/provision-dns.sh` | DNS record creation |
| `infra/cloudflare/.env.cloudflare.template` | All secrets/vars reference |
| `.env.production` | Actual secret values (repo root) |
| `.github/workflows/deploy.yml` | CI/CD pipeline |
| `.github/workflows/ci.yml` | CI checks (lint + test) |

## Credentials

All credentials are in `.env.production` at the repo root. Key values:
- Cloudflare Account ID: `a44ddf3ff0612bc0f62d1ee86f465ac9`
- R2 Bucket: `netz-data-lake`
- Worker dispatch secret: `Gwq3H8bEhDqOCVIks8Xd4dJZugKTrl_KlfX54jYyi7c`
- Clerk is in test mode (`pk_test_`, `sk_test_`)

## Validation Checklist

1. `curl https://api.netz.app/health` returns `{"status":"ok",...}`
2. `curl https://api.netz.app/api/v1/manager-screener/?page=1&page_size=1` returns manager data (with valid Clerk JWT)
3. `https://wealth.netz.app/screener` loads the unified screener page
4. Cron worker triggers show in `wrangler tail netz-cron`
5. R2 bucket accessible from backend container

## Bug Fixes Applied in This Session (Already Committed)

These fixes are in the working tree but NOT yet committed:

1. **`backend/app/domains/wealth/queries/manager_screener_sql.py`:**
   - Fixed self-correlating subquery (missing FROM clause → "aggregate in WHERE" error)
   - Fixed `uuid = text` type mismatch (cast to UUID instead of TEXT)

2. **`backend/app/domains/wealth/routes/manager_screener.py`:**
   - Fixed `asyncio.gather()` on same session (asyncpg doesn't support pipelining) → sequential execution

3. **`packages/ui/src/lib/utils/auth.ts`:**
   - Added `devToken` option to `createClerkHook` for configurable dev token

4. **`frontends/wealth/src/hooks.server.ts`:**
   - Reads `VITE_DEV_TOKEN` for dev bypass with correct backend token

5. **Unified Screener merge** (the main feature):
   - `frontends/wealth/src/routes/(app)/screener/` — merged manager + fund screener
   - `frontends/wealth/src/routes/(app)/+layout.svelte` — sidebar updated (11 items)
   - `frontends/wealth/src/routes/(app)/manager-screener/` — DELETED
