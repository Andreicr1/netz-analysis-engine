---
module: CI Frontend Pipeline
date: 2026-03-23
problem_type: build_error
component: development_workflow
symptoms:
  - "Cannot read file '.svelte-kit/tsconfig.json' — svelte-check fails in CI"
  - "HTMLElement not assignable to HTMLDivElement for clerk.mountSignIn()"
  - "afterSignInUrl does not exist in type SignInProps (Clerk v4 deprecation)"
  - "subtitle does not exist in type $ComponentProps (PageHeader)"
  - "Property title missing in type { message: string } (EmptyState)"
root_cause: incomplete_setup
resolution_type: code_fix
severity: high
tags: [ci, svelte-check, sveltekit-sync, clerk, typescript, frontend-pipeline]
---

# Troubleshooting: CI Frontend Type-Check Failures on First Run

## Problem

After adding a `check-frontends` job to the CI workflow, all 3 SvelteKit frontends failed `svelte-check`. The first run failed because `.svelte-kit/tsconfig.json` didn't exist. After adding `svelte-kit sync`, real TypeScript errors surfaced across sign-in pages and the market-data page.

## Environment

- Module: CI Frontend Pipeline (`.github/workflows/ci.yml`)
- Stack: SvelteKit 5, Svelte 5, Clerk JS v4, @netz/ui shared components
- Affected Files: `frontends/*/src/routes/auth/sign-in/+page.svelte`, `frontends/credit/src/routes/(team)/funds/[fundId]/market-data/+page.svelte`
- Date: 2026-03-23

## Symptoms

1. **All 3 frontends**: `Cannot read file '.svelte-kit/tsconfig.json'` — `svelte-check` could not find generated types
2. **All 3 sign-in pages**: `Argument of type 'HTMLElement' is not assignable to parameter of type 'HTMLDivElement'` at `clerk.mountSignIn(el, ...)`
3. **Credit sign-in**: `'afterSignInUrl' does not exist in type 'SignInProps'. Did you mean to write 'afterSignOutUrl'?`
4. **Market-data page line 146**: `'"subtitle"' does not exist in type '$ComponentProps'` on `<PageHeader subtitle="...">`
5. **Market-data page line 150**: `Property 'title' is missing in type '{ message: string; }' but required in type 'Props'` on `<EmptyState message="...">`
6. **Market-data page lines 58-59**: `Object is possibly 'undefined'` on `section[sid].label` and `section[sid].points`

## What Didn't Work

**Attempted Solution 1:** Added `svelte-kit sync` step before type-check.
- **Partial success:** Fixed the `.svelte-kit/tsconfig.json` error but exposed 6 real TypeScript errors that had been hidden because type-checking was never run in CI before.

## Solution

### Fix 1: Add `svelte-kit sync` to CI before type-check

```yaml
# .github/workflows/ci.yml — check-frontends job
- name: Sync SvelteKit generated types
  run: pnpm --filter "./frontends/*" exec svelte-kit sync
- name: Type-check all frontends
  run: pnpm --filter "./frontends/*" check
```

### Fix 2: Cast getElementById to HTMLDivElement (all 3 sign-in pages)

```typescript
// Before (broken):
const el = document.getElementById("clerk-sign-in");

// After (fixed):
const el = document.getElementById("clerk-sign-in") as HTMLDivElement | null;
```

Clerk's `mountSignIn()` expects `HTMLDivElement`, but `getElementById` returns `HTMLElement | null`. The target element is always a `<div>`, so the cast is safe.

### Fix 3: Replace deprecated `afterSignInUrl` with `fallbackRedirectUrl`

```typescript
// Before (broken — Clerk v4 removed this prop):
clerk.mountSignIn(el, {
  afterSignInUrl: "/",
  ...
});

// After (fixed — Clerk v4 API):
clerk.mountSignIn(el, {
  fallbackRedirectUrl: "/",
  ...
});
```

### Fix 4: Remove invalid `subtitle` prop from PageHeader

```svelte
<!-- Before (broken — PageHeader has no subtitle prop): -->
<PageHeader title="Market Data" subtitle="Credit market indicators from FRED" />

<!-- After (fixed): -->
<PageHeader title="Market Data" />
```

`PageHeader` props: `title`, `breadcrumbs`, `class`, `actions`. No `subtitle`.

### Fix 5: Add required `title` to EmptyState

```svelte
<!-- Before (broken — title is required): -->
<EmptyState message="Market data unavailable..." />

<!-- After (fixed): -->
<EmptyState title="No Market Data" message="Market data unavailable..." />
```

### Fix 6: Non-null assertions after filter

```typescript
// Before (broken — TS doesn't narrow after .filter()):
.filter((sid) => section[sid]?.points?.length)
.map((sid) => ({
  name: section[sid].label,       // Object is possibly 'undefined'
  data: section[sid].points.map(  // Object is possibly 'undefined'

// After (fixed — ! asserts existence guaranteed by filter):
.filter((sid) => section[sid]?.points?.length)
.map((sid) => ({
  name: section[sid]!.label,
  data: section[sid]!.points.map(
```

## Why This Works

1. **`svelte-kit sync`** generates `.svelte-kit/tsconfig.json` and type declarations for routes, which `svelte-check` depends on. In dev mode (`pnpm dev`), this happens automatically. In CI (no dev server), it must run explicitly.

2. **HTMLDivElement cast** is safe because the target element `<div id="clerk-sign-in">` is always a div. `getElementById` returns the generic `HTMLElement` type but the Clerk SDK's `mountSignIn` signature specifically requires `HTMLDivElement`.

3. **Clerk v4 renamed** `afterSignInUrl` → `fallbackRedirectUrl` as part of their redirect URL unification. The old prop was removed from the TypeScript types.

4. **Component prop mismatches** were never caught because `svelte-check` wasn't running in CI. The pages rendered fine at runtime (Svelte ignores unknown props in dev mode) but fail strict type checking.

5. **TypeScript can't narrow** array index access through `.filter()` — it doesn't track that `section[sid]` was already checked for existence. Non-null assertion `!` is the standard pattern here.

## Prevention

- **Always include `svelte-kit sync`** before `svelte-check` in CI pipelines. Add it as a step between `pnpm install` and `check`.
- **Run `pnpm check` locally** before pushing frontend changes (or rely on the new CI job to catch it).
- **When using Clerk SDK**, check the installed version's types — deprecated props won't error at runtime but will fail type-check.
- **When using shared @netz/ui components**, check the component's Props interface before passing props. Don't assume props exist based on what renders visually.
- **For dictionary access after `.filter()`**, always use `!` non-null assertion when the filter guarantees the key exists.

## Related Issues

- See also: [playwright-e2e-5-failures-initial-setup-E2EInfrastructure-20260323.md](../test-failures/playwright-e2e-5-failures-initial-setup-E2EInfrastructure-20260323.md) — same session, E2E test failures with similar root causes (assumptions about component text/structure)
