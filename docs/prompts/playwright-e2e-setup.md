# Playwright E2E Tests — Full Frontend Coverage

## Context

You are working on `netz-analysis-engine`, a multi-tenant investment analysis platform with 3 SvelteKit frontends deployed to Cloudflare Pages. There are **zero existing frontend tests**. Your job is to set up Playwright and write comprehensive E2E tests.

Read `CLAUDE.md` at the repo root for full architecture context.

### Frontend Architecture
- **Credit** (`frontends/credit/`, port 5173): Private credit intelligence
- **Wealth** (`frontends/wealth/`, port 5174): Wealth management OS
- **Admin** (`frontends/admin/`, port 5175): Platform administration
- **Shared UI** (`packages/ui/`): `@netz/ui` — Tailwind tokens, shadcn-svelte, layouts

### Auth Pattern
All frontends use Clerk JWT v2 via `hooks.server.ts` → `createClerkHook()` from `@netz/ui/utils`.
- **Dev bypass**: `X-DEV-ACTOR` header or dev-token in Authorization header
- **Public routes**: `/auth/*`, `/health`
- **Session**: `event.locals.actor` (id, email, organization_id, role) + `event.locals.token` (JWT)

### Role Guards
- **Credit `(team)/`**: rejects INVESTOR role → allows gestora users
- **Credit `(investor)/`**: allows INVESTOR, ADVISOR only
- **Wealth `(app)/`**: all authenticated users
- **Admin `(admin)/`**: SUPER_ADMIN, ADMIN, ORG:ADMIN only → redirects unauthorized to `/auth/sign-in?error=unauthorized`

---

## Task 1: Setup Playwright Infrastructure

### 1.1 Install Playwright in the monorepo root

```bash
pnpm add -D -w @playwright/test
npx playwright install chromium
```

### 1.2 Create `playwright.config.ts` at repo root

```typescript
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // sequential — shared backend state
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'credit',
      testDir: './e2e/credit',
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:5173',
      },
    },
    {
      name: 'wealth',
      testDir: './e2e/wealth',
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:5174',
      },
    },
    {
      name: 'admin',
      testDir: './e2e/admin',
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:5175',
      },
    },
  ],
  // Start all 3 dev servers before tests
  webServer: [
    {
      command: 'pnpm --filter netz-credit-intelligence dev',
      port: 5173,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'pnpm --filter netz-wealth-os dev',
      port: 5174,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'pnpm --filter netz-admin dev',
      port: 5175,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
```

### 1.3 Create directory structure

```
e2e/
├── fixtures/
│   └── auth.ts          # shared auth helpers
├── credit/
│   ├── auth.spec.ts
│   ├── dashboard.spec.ts
│   ├── pipeline.spec.ts
│   ├── documents.spec.ts
│   ├── portfolio.spec.ts
│   └── investor-portal.spec.ts
├── wealth/
│   ├── auth.spec.ts
│   ├── screener.spec.ts
│   ├── portfolios.spec.ts
│   ├── dd-reports.spec.ts
│   ├── analytics.spec.ts
│   ├── macro.spec.ts
│   └── documents.spec.ts
└── admin/
    ├── auth.spec.ts
    ├── health.spec.ts
    ├── tenants.spec.ts
    └── config.spec.ts
```

### 1.4 Add scripts to root `package.json`

```json
{
  "scripts": {
    "test:e2e": "playwright test",
    "test:e2e:credit": "playwright test --project=credit",
    "test:e2e:wealth": "playwright test --project=wealth",
    "test:e2e:admin": "playwright test --project=admin",
    "test:e2e:ui": "playwright test --ui"
  }
}
```

---

## Task 2: Auth Fixtures

Create `e2e/fixtures/auth.ts` — shared authentication helper using dev bypass.

The frontends in dev mode accept the `X-DEV-ACTOR` header or a dev token. The sign-in page has a "Continue as Dev User" button that bypasses Clerk.

**Strategy**: For each test, either:
- Click the "Continue as Dev User" button on the sign-in page, OR
- Set a cookie/localStorage that the hooks.server.ts recognizes

Read these files to understand the exact dev bypass mechanism:
- `frontends/credit/src/hooks.server.ts`
- `frontends/credit/src/routes/auth/sign-in/+page.svelte`
- `packages/ui/src/lib/utils/clerk-hook.ts` (or wherever `createClerkHook` lives)

The auth fixture should export:
```typescript
// Logs in as dev user with given role, returns authenticated page
async function loginAs(page: Page, role: 'admin' | 'gestora' | 'investor' | 'super_admin'): Promise<void>
```

---

## Task 3: Write Tests Per Frontend

### CREDIT FRONTEND (`e2e/credit/`)

#### `auth.spec.ts` — Authentication & Role Guards
```
- sign-in page loads without CSP errors
- "Continue as Dev User" button visible in dev mode
- clicking dev bypass → redirects to /dashboard
- navigating to /dashboard without auth → redirects to /auth/sign-in
- investor role cannot access (team) routes → gets 403
- gestora role cannot access (investor) routes → gets 403
- sign-out redirects to /auth/sign-in
```

#### `dashboard.spec.ts` — Dashboard
```
- page loads with correct title
- shows fund summary cards (or empty state)
- task inbox renders
- navigation sidebar is visible with correct links
```

#### `pipeline.spec.ts` — Deal Pipeline
```
- /funds/{fundId}/pipeline loads
- pipeline view renders (list or kanban)
- stage columns visible in kanban mode
- empty state shown when no deals
```

#### `documents.spec.ts` — Documents
```
- /funds/{fundId}/documents loads
- document list renders or shows empty state
- upload button is visible
- search input is functional
- dataroom page loads
```

#### `portfolio.spec.ts` — Portfolio
```
- /funds/{fundId}/portfolio loads
- tabs render (obligations, alerts, actions)
- empty state for portfolio without assets
```

#### `investor-portal.spec.ts` — Investor Portal
```
- investor role can access /report-packs
- investor role can access /statements
- gestora role CANNOT access investor routes
```

### WEALTH FRONTEND (`e2e/wealth/`)

#### `auth.spec.ts` — Authentication
```
- sign-in page loads (dark theme)
- dev bypass works → redirects to /screener
- unauthenticated → redirects to /auth/sign-in
```

#### `screener.spec.ts` — Fund Screener
```
- /screener loads with results table or empty state
- filter controls render
- pagination works (if results exist)
```

#### `portfolios.spec.ts` — Portfolios
```
- /portfolios loads with list or empty state
- /portfolios/{profile} loads portfolio detail
```

#### `dd-reports.spec.ts` — DD Reports
```
- /dd-reports loads with list or empty state
- report detail page loads (if reports exist)
```

#### `analytics.spec.ts` — Analytics
```
- /analytics page loads
- /risk page loads
- /exposure page loads
- /macro page loads
```

#### `documents.spec.ts` — Documents
```
- /documents page loads
- upload flow accessible
```

### ADMIN FRONTEND (`e2e/admin/`)

#### `auth.spec.ts` — Admin Auth
```
- sign-in page loads
- dev bypass with super_admin → can access /health
- non-admin role → redirected to /auth/sign-in?error=unauthorized
```

#### `health.spec.ts` — Health Dashboard
```
- /health loads with service status cards
- PostgreSQL, Redis status indicators render
```

#### `tenants.spec.ts` — Tenant Management
```
- /tenants loads with tenant list or empty state
- tenant detail page loads when clicking a tenant
```

#### `config.spec.ts` — Configuration
```
- /config/credit loads config editor
- /config/wealth loads config editor
```

---

## Task 4: CSP Smoke Test (Playwright)

Create `e2e/credit/csp.spec.ts` — validates no CSP console errors:

```typescript
test('page loads without CSP violations', async ({ page }) => {
  const cspErrors: string[] = [];
  page.on('console', msg => {
    if (msg.type() === 'error' && msg.text().includes('Content Security Policy')) {
      cspErrors.push(msg.text());
    }
  });

  await loginAs(page, 'gestora');
  await page.goto('/dashboard');
  await page.waitForLoadState('networkidle');

  expect(cspErrors).toEqual([]);
});
```

Duplicate this test for wealth (`/screener`) and admin (`/health`).

---

## Execution Rules

1. **Read source files before writing tests** — understand what each page renders
2. **Use dev bypass for auth** — never use real Clerk credentials
3. **Tests must work offline** — mock external API calls if needed, but SvelteKit SSR with dev bypass should work against local backend
4. **No hardcoded wait times** — use `waitForSelector`, `waitForLoadState`, Playwright auto-waiting
5. **Each test file ≤ 15 tests** — focused, readable
6. **Run tests after each file**: `pnpm test:e2e:{project} -- {spec_file}`
7. **Commit after each frontend** with message: `test(e2e): add Playwright tests for {frontend} ({N} tests)`

## Verification

After completing all tests:

```bash
pnpm test:e2e
```

Expected: ~60-80 tests across 3 frontends, all passing, zero CSP violations.
