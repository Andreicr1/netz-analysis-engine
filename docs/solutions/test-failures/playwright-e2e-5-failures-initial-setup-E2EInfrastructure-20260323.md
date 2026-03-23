---
module: E2E Test Infrastructure
date: 2026-03-23
problem_type: test_failure
component: testing_framework
symptoms:
  - "Admin 'Continue as Dev User' not found — actual text is 'Continue as dev admin'"
  - "Admin role guard tests on /health skipped — /health is in PUBLIC_PREFIXES"
  - "Strict mode violation: getByText(/Funds|No Funds/) resolved to 3 elements"
  - "Admin health CSP: localhost:8000 blocked by connect-src 'self'"
root_cause: logic_error
resolution_type: test_fix
severity: medium
tags: [playwright, e2e, strict-mode, csp, role-guard, sveltekit, dev-bypass]
---

# Troubleshooting: Playwright E2E — 5 Failures on Initial Test Suite Setup

## Problem

After creating 60 Playwright E2E tests across 3 SvelteKit frontends (credit, wealth, admin), 5 tests failed on the first run due to incorrect assumptions about page content, route guards, and CSP behavior in dev mode.

## Environment

- Module: E2E Test Infrastructure (Playwright + 3 SvelteKit frontends)
- Stack: SvelteKit 5, Playwright 1.58, Clerk dev bypass via `createClerkHook`
- Affected Component: `e2e/credit/pipeline.spec.ts`, `e2e/admin/auth.spec.ts`, `e2e/admin/health.spec.ts`
- Date: 2026-03-23

## Symptoms

1. **Admin "Continue as Dev User" button not found** — `getByRole('link', { name: 'Continue as Dev User' })` failed. Admin sign-in page uses "Continue as dev admin" not "Continue as Dev User" like credit/wealth.
2. **Admin role guard tests passed unexpectedly** — investor/gestora roles could access `/health` without redirect. Tests timed out waiting for redirect to `/auth/sign-in?error=unauthorized`.
3. **Credit pipeline strict mode violation** — `getByText(/Funds|No Funds/)` matched 3 elements: nav link "Funds", heading `<h1>Funds</h1>`, and empty state heading `<h3>No Funds</h3>`.
4. **Admin CSP violation on health page** — `connect-src 'self'` blocks `localhost:8000` because frontend runs on port 5175 (different origin). Workers log feed tries to connect to backend API.
5. **Stray `test-1.spec.ts`** — Auto-generated Playwright scaffold file picked up as a test.

## What Didn't Work

**Attempted Solution 1 (pipeline):** Used `[class*='fund'], [class*='card'], [class*='empty']` CSS selector.
- **Why it failed:** The empty state uses utility classes (`text-base font-semibold`) not semantic class names containing "fund", "card", or "empty".

**Attempted Solution 2 (pipeline):** Used `getByText(/Funds|No Funds/)` regex.
- **Why it failed:** Regex matched 3 elements — Playwright strict mode requires locators to resolve to exactly 1 element.

## Solution

### Fix 1: Admin dev button text

```typescript
// Before (broken):
await expect(page.getByRole("link", { name: "Continue as Dev User" })).toBeVisible();

// After (fixed):
await expect(page.getByRole("link", { name: "Continue as dev admin" })).toBeVisible();
```

### Fix 2: Admin role guard — use non-public route

The admin `adminGuardHook` in `hooks.server.ts` defines:
```typescript
const PUBLIC_PREFIXES = ["/auth/", "/health"];
```

`/health` starts with `/health` → guard is skipped for that route.

```typescript
// Before (broken — /health is public):
await loginAs(page, "investor");
await page.goto("/health");
await page.waitForURL("**/auth/sign-in**");

// After (fixed — /tenants is admin-guarded):
await loginAs(page, "investor");
await page.goto("/tenants");
expect(page.url()).toContain("/auth/sign-in");
expect(page.url()).toContain("error=unauthorized");
```

Also removed `page.waitForURL()` — the redirect is a server-side `throw redirect(303)` in the SvelteKit hook, so `page.goto()` follows it synchronously. The URL is already changed when `goto` resolves.

### Fix 3: Credit pipeline strict mode

```typescript
// Before (broken — matches 3 elements):
await expect(page.getByText(/Funds|No Funds/)).toBeVisible({ timeout: 10_000 });

// After (fixed — targets exactly the h1 heading):
await expect(
  page.getByRole("heading", { name: "Funds", exact: true })
).toBeVisible({ timeout: 10_000 });
```

### Fix 4: Admin CSP — exclude dev-mode backend violations

```typescript
// Before (broken — catches dev-mode false positives):
if (msg.type() === "error" && msg.text().includes("Content Security Policy")) {
  cspErrors.push(msg.text());
}

// After (fixed — excludes known dev-mode cross-origin backend):
if (msg.type() === "error" && msg.text().includes("Content Security Policy")) {
  if (!msg.text().includes("localhost:8000")) {
    cspErrors.push(msg.text());
  }
}
```

### Fix 5: Stray scaffold file

```bash
rm e2e/wealth/test-1.spec.ts
```

## Why This Works

1. **Button text**: Each frontend has its own sign-in page with different copy. Admin uses "Continue as dev admin" to emphasize the admin-specific bypass. Always read the actual page source before writing selectors.

2. **PUBLIC_PREFIXES**: The admin guard has an explicit public route list that includes `/health`. This is intentional — the health endpoint should be accessible for monitoring without admin credentials. Test admin role guards against genuinely protected routes like `/tenants`.

3. **Strict mode**: Playwright's `getByText` with a regex that matches common words will inevitably hit multiple elements (nav links, headings, body text). `getByRole("heading", { exact: true })` is the correct Playwright pattern — it targets a specific ARIA role with exact text matching.

4. **CSP in dev mode**: SvelteKit dev servers run on different ports than the backend. The CSP `connect-src 'self'` refers to the frontend origin (e.g., `localhost:5175`), not `localhost:8000`. This is a known dev-mode limitation, not a production issue (production uses same domain or explicit API domain in CSP).

5. **SvelteKit server-side redirects**: `throw redirect(303)` in a SvelteKit hook responds with an HTTP 303 to the browser. Playwright's `page.goto()` follows redirects, so the final URL is already the redirect target. No need for `page.waitForURL()`.

## Prevention

- **Always read the actual sign-in page source** for each frontend before writing auth tests — button text varies per frontend.
- **Check `PUBLIC_PREFIXES` in hooks.server.ts** before writing role-guard tests. Use a route that is NOT in the public list.
- **Prefer `getByRole()` with `exact: true`** over `getByText()` with regex. Strict mode violations are the most common Playwright failure mode.
- **For CSP smoke tests in dev mode**, always exclude `localhost:{backend_port}` violations. These are cross-port false positives that don't exist in production.
- **After `npx playwright install`**, check for auto-generated scaffold files (`test-1.spec.ts`, `example.spec.ts`) and remove them.
- **Server-side redirects** (`throw redirect()` in SvelteKit hooks): assert on `page.url()` directly after `page.goto()` — don't use `page.waitForURL()`.

## Related Issues

No related issues documented yet.
