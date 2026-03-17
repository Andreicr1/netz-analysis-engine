---
title: "feat: Credit Frontend Design Refresh — Institutional Token System + Dark Theme + ContextSidebar"
type: feat
status: active
date: 2026-03-17
deepened: 2026-03-17
origin: docs/brainstorms/2026-03-17-credit-frontend-design-refresh-brainstorm.md
---

# Credit Frontend Design Refresh — Institutional Token System + Dark Theme + ContextSidebar

## Enhancement Summary

**Deepened on:** 2026-03-17
**Research agents used:** 8 (dark theme FOUC patterns, Svelte 5 store/layout bridging, CSS token audit best practices, security sentinel, architecture strategist, performance oracle, pattern recognition specialist, code simplicity reviewer)

### Key Improvements from Research

1. **ARCHITECTURE: Context + `$state` hybrid replaces writable store** — Svelte 5 idiomatic pattern using `setContext`/`getContext` with `$state` rune. SSR-safe (per-request instance), matches existing `setContext("netz:getToken", ...)` precedent in AppLayout. Module-level `writable` is a singleton that leaks state across SSR requests. (Svelte 5 Store Research)
2. **ARCHITECTURE: Extract `createThemeHook()` into `@netz/ui/utils`** — Parallels existing `createClerkHook()`. Eliminates hook duplication between Wealth and Credit. Parameterized by `defaultTheme`. (Pattern Recognition)
3. **STRUCTURE: Collapse 6 phases → 3 phases** — Phases 1-3 are all "search-replace tokens/colors" + 25 lines of dark infra. Touching each file once is more efficient. Phase 5 is 2 lines of deletion (fold in). Phase 6 is PR acceptance criteria, not implementation. (Simplicity Review)
4. **SECURITY: Cookie attributes must be explicit** — `httpOnly: false` (client JS needs access), `SameSite=Lax`, `Secure` in production, `path=/`. SvelteKit defaults `httpOnly: true` which would break client-side theme reads. (Security Sentinel)
5. **PERFORMANCE: Guard store updates with structural equality** — `$effect` re-runs on every `$page.url.pathname` change, creating new object reference each time. Use `.update()` with guard or separate static config from dynamic `activeHref`. (Performance Oracle)
6. **FOUC: Add `prefers-color-scheme` fallback** — First-time visitors with no localStorage get OS preference instead of hardcoded default. (Dark Theme Research)
7. **TOOLING: Add `stylelint-value-no-unknown-custom-properties`** — Enforces D4 (no undeclared tokens) in CI. `importFrom` points at `tokens.css`. (CSS Token Audit Research)
8. **CRITICAL: First production use of ContextSidebar** — Neither frontend currently uses `contextNav` in AppLayout. Credit will be the first consumer. Add cold-start deep-link testing. (Architecture Review)

### New Considerations Discovered

- **Tailwind config has undeclared tokens** — `netz.navy`, `netz.blue`, `netz.orange` in `tailwind.config.ts` reference `--netz-navy`, `--netz-blue` etc. which are NOT in `tokens.css`. Fix during Phase 1.
- **Todo #129 (theme cookie XSS) is already fixed** — `VALID_THEMES` allowlist was added. Can be closed.
- **`transformPageChunk` is streaming-safe** — First chunk always contains `<html>` tag. No risk with SvelteKit streaming SSR.
- **Color mapping rules are undocumented** — Add explicit mapping table to design decisions doc.
- **`--netz-primary` alias should be marked DEPRECATED** — Add CSS comment after all references are normalized.

---

## Overview

Migrate `frontends/credit/` to the institutional design system established in the Wealth OS design refresh (PR #52). The `@netz/ui` package already contains all needed tokens, components, and layout primitives. This plan covers token normalization, dark theme infrastructure, hardcoded color elimination, ContextSidebar for fund detail pages, and minor Svelte 5 cleanup.

**Not in scope:** navigation structure changes (credit keeps current TopNav via AppLayout), new pages, component redesigns, investor portal (`(investor)` routes), theme toggle UI.

## Problem Statement

The Credit frontend was built before the institutional design system was finalized. It has:

1. **7+ files referencing `var(--netz-primary)`** — an alias that works but is not the canonical token (`--netz-brand-primary`)
2. **Emoji icons in navigation** — `📊 📈 💼 📄 📑 🤖` in navItems violate the institutional text-only standard
3. **No dark theme support** — no `data-theme` attribute, no FOUC prevention, no `themeHook` in SSR
4. **Hardcoded `bg-white`** in at least 7 additional locations — breaks dark mode completely
5. **No ContextSidebar** on fund detail pages — `[fundId]/+layout.svelte` uses inline `PageHeader` tabs instead of the shared `ContextSidebar` component
6. **Undeclared tokens in `tailwind.config.ts`** — `--netz-navy`, `--netz-blue`, `--netz-orange` referenced but never declared in `tokens.css` (D4 violation)
7. **Minor Svelte 5 anti-patterns** — 2 passthrough `$derived` in ICMemoViewer

## Proposed Solution

Three phases (collapsed from 6 per simplicity review — touching each file once is more efficient):

| Phase | Description | Dependency |
|-------|-------------|------------|
| 1 | Token migration + dark theme infra + hardcoded color audit | Foundation — blocks Phase 2 |
| 2 | ContextSidebar for `[fundId]` routes | Independent after Phase 1 |
| 3 | PR validation gate (acceptance criteria, not implementation) | After all phases |

> **Why 3 phases instead of 6:** Phases 1-3 of the original plan all touch the same `.svelte` files for token/color work. Dark theme infra is 2 files, 25 lines — not a separate phase. The Svelte 5 cleanup is 2 lines of deletion in `ICMemoViewer.svelte` — fold into Phase 1 while editing that file. Validation is PR criteria, not implementation work. (Simplicity Review)

## Technical Approach

### Architecture

The Credit frontend already uses `AppLayout` from `@netz/ui` with `TopNav` rendering. This is the correct pattern and will not change.

> **Brainstorm clarification:** The brainstorm states "Credit usa Sidebar como navegação global (não migra para TopNav)." However, the actual code at `frontends/credit/src/routes/+layout.svelte` already uses `AppLayout` which renders `TopNav`. This has been the state since the platform PRs (#37-#45). The instruction "don't migrate to TopNav" is interpreted as "don't change the current navigation structure" — which is already TopNav-based. No navigation architecture change is needed.

**ContextSidebar bridging mechanism:** The `AppLayout` accepts `contextNav?` as a prop, but it's instantiated in the root `+layout.svelte`, while the fund context data lives in `[fundId]/+layout.svelte` (3 levels deep). Svelte has no upward prop mechanism.

### Research Insight: Context + `$state` Hybrid (replaces writable store)

The original plan proposed a `writable` store from `svelte/store`. Research identified three problems:

1. **SSR safety** — Module-level `writable` is a singleton. In SSR, it persists across requests and can leak state between users.
2. **Svelte 5 idiom** — The Svelte team has positioned `$app/state` (runes-based) as the replacement for `$app/stores`. New code should use runes.
3. **Precedent** — `AppLayout` already uses `setContext("netz:getToken", ...)` for auth. The contextNav bridge should follow the same pattern.

**Solution: Context + `$state` hybrid** (SSR-safe, Svelte 5 idiomatic):

```
frontends/credit/src/lib/state/context-nav.svelte.ts  (NEW)
  ↓ initContextNav() called by root +layout.svelte (creates per-request instance via setContext)
  ↓ useContextNav() called by [fundId]/+layout.svelte (reads via getContext, writes .current)
  ↓ root +layout.svelte reads contextNavState.current → passes to AppLayout contextNav prop
```

**Why this wins over `writable`:**
- SSR-safe (new instance per request via `setContext`, not module singleton)
- Idiomatic Svelte 5 (`$state` rune, not deprecated store API)
- Matches existing auth context pattern (`setContext("netz:getToken", ...)`)
- No race conditions (SvelteKit navigation serializes route transitions)

Sources: [Mainmatter: Runes and Global State](https://mainmatter.com/blog/2025/03/11/global-state-in-svelte-5/), [Joy of Code: Share State in Svelte 5](https://joyofcode.xyz/how-to-share-state-in-svelte-5), [SvelteKit State Management docs](https://svelte.dev/docs/kit/state-management)

### Research Insight: Extract `createThemeHook()` into `@netz/ui/utils`

The pattern recognition review identified that both frontends will have identical `themeHook` logic (only default value differs). This parallels `createClerkHook()` which is already shared.

**Recommendation:** Add to `packages/ui/src/lib/utils/auth.ts` (or a new `theme.ts`):

```typescript
export function createThemeHook(options: { defaultTheme?: "dark" | "light" } = {}): Handle {
  const defaultTheme = options.defaultTheme ?? "light";
  const VALID_THEMES = new Set(["dark", "light"]);
  return async ({ event, resolve }) => {
    const raw = event.cookies.get("netz-theme") || defaultTheme;
    const theme = VALID_THEMES.has(raw) ? raw : defaultTheme;
    return resolve(event, {
      transformPageChunk: ({ html }) =>
        html.replace(`data-theme="${defaultTheme}"`, `data-theme="${theme}"`),
    });
  };
}
```

This is the **one exception** to "zero changes to `@netz/ui`" — it's a net simplification that prevents hook duplication. Both frontends then use:

```typescript
// Credit hooks.server.ts
export const handle = sequence(authHook, createThemeHook({ defaultTheme: "light" }));

// Wealth hooks.server.ts (refactor)
export const handle = sequence(authHook, createThemeHook({ defaultTheme: "dark" }));
```

> **Note:** If extracting to `@netz/ui` is out of scope for this PR, inline the hook in Credit's `hooks.server.ts` and create a follow-up to extract. The inline version is in Phase 1 below.

### Implementation Phases

---

#### Phase 1: Token Migration + Dark Theme Infrastructure + Hardcoded Color Audit

**Goal:** Single pass through all Credit `.svelte` files: normalize tokens, remove emojis, replace hardcoded colors, add dark theme infra, fix Svelte 5 anti-patterns. Also fix `tailwind.config.ts` undeclared tokens.

##### 1a. Token Normalization + Emoji Removal

| File | Changes |
|------|---------|
| `src/routes/+layout.svelte` | Remove `icon` property from all 6 navItems |
| `src/routes/+error.svelte` | 3x `--netz-primary` → `--netz-brand-primary` |
| `src/lib/components/CopilotChat.svelte` | 2x `--netz-primary` → `--netz-brand-primary` |
| `src/lib/components/ICMemoViewer.svelte` | 1x `--netz-primary` → `--netz-brand-primary` + remove 2 passthrough `$derived` (Svelte 5 fix) |
| `src/lib/components/ICMemoStreamingChapter.svelte` | 1x `--netz-primary` → `--netz-brand-primary` |
| `src/routes/(team)/copilot/+page.svelte` | 2x `--netz-primary` → `--netz-brand-primary` |
| `src/routes/(team)/funds/[fundId]/+layout.svelte` | 2x `--netz-primary` → `--netz-brand-primary` |
| `src/routes/(team)/funds/[fundId]/documents/upload/+page.svelte` | 1x `--netz-primary` → `--netz-brand-primary` |
| `src/routes/auth/sign-in/+page.svelte` | Replace `var(--netz-navy,#1b365d)` and `var(--netz-primary,#1b365d)` with `var(--netz-brand-primary)` |
| `tailwind.config.ts` | Remove undeclared `netz.navy`, `netz.blue`, `netz.slate`, `netz.light`, `netz.orange` color references |

##### 1b. Dark Theme Infrastructure

**File: `src/app.html`**

```html
<!doctype html>
<!-- data-theme="light" is the SSR baseline. themeHook in hooks.server.ts replaces it. -->
<!-- Do NOT remove data-theme — it is the sentinel for transformPageChunk. -->
<html lang="en" data-theme="light">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="icon" href="%sveltekit.assets%/favicon.png" />
    <title>Netz Credit Intelligence</title>
    <script>
      // FOUC prevention — set theme before first paint (Pattern: see D2 in design-decisions)
      (function() {
        var theme = localStorage.getItem('netz-theme');
        if (theme !== 'dark' && theme !== 'light') {
          // First-time visitor: respect OS preference, default to light
          theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        document.documentElement.setAttribute('data-theme', theme);
      })();
    </script>
    %sveltekit.head%
  </head>
  <body data-sveltekit-preload-data="hover">
    <div style="display: contents">%sveltekit.body%</div>
  </body>
</html>
```

**Research improvements over original:**
- `prefers-color-scheme` fallback for first-time visitors (Dark Theme Research)
- Sentinel comments linking `data-theme` to `themeHook` (Architecture Review, Security Sentinel)

**File: `src/hooks.server.ts`**

```typescript
import { createClerkHook } from "@netz/ui/utils";
import type { Handle } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";

const CLERK_JWKS_URL = process.env.CLERK_JWKS_URL ?? import.meta.env.VITE_CLERK_JWKS_URL;

const authHook: Handle = createClerkHook({
  jwksUrl: CLERK_JWKS_URL,
  devBypass: import.meta.env.DEV,
  publicPrefixes: ["/auth/", "/health"],
}) as Handle;

const VALID_THEMES = new Set(["dark", "light"]);

/** Inject data-theme attribute into SSR HTML to prevent FOUC.
 *  Must match data-theme value in app.html (currently "light"). */
const themeHook: Handle = async ({ event, resolve }) => {
  const raw = event.cookies.get("netz-theme") || "light";
  const theme = VALID_THEMES.has(raw) ? raw : "light";
  return resolve(event, {
    transformPageChunk: ({ html }) =>
      html.replace('data-theme="light"', `data-theme="${theme}"`),
  });
};

export const handle: Handle = sequence(authHook, themeHook);
```

**Research insight — `transformPageChunk` is streaming-safe:** The first chunk always contains the `<html>` tag. `String.replace()` with a literal needle on a ~500 byte chunk is sub-microsecond. No performance concern. (Dark Theme Research, Performance Oracle)

**Cookie/localStorage sync:** No toggle UI in this PR. The blocking script (localStorage) is the primary FOUC prevention. The themeHook (cookie) optimizes SSR. A future theme toggle must write BOTH with these cookie attributes: `path=/; max-age=31536000; SameSite=Lax` (client-side), or via SvelteKit `cookies.set()` with `httpOnly: false` (server-side — SvelteKit defaults `httpOnly: true` which would break client reads). (Security Sentinel)

##### 1c. Hardcoded Color Audit + Replacement

**Complete inventory (from SpecFlow analysis + grep + pattern recognition):**

| File | Issue | Replacement |
|------|-------|-------------|
| `CopilotChat.svelte` L30 | `bg-white` (assistant bubble) | `bg-[var(--netz-surface)]` |
| `copilot/+page.svelte` L68 | `bg-white` (input field) | `bg-[var(--netz-surface)]` |
| `auth/sign-in/+page.svelte` ~L10 | `bg-white` (card background) | `bg-[var(--netz-surface)]` |
| `dashboard/+page.svelte` ~L97, ~L109 | `bg-white` (card containers) | `bg-[var(--netz-surface)]` |
| `DealStageTimeline.svelte` ~L19 | `bg-white` | `bg-[var(--netz-surface)]` |
| Any file | `text-gray-*` patterns | `text-[var(--netz-text-secondary)]` or `text-[var(--netz-text-muted)]` |
| Any file | `border-gray-*` patterns | `border-[var(--netz-border)]` |
| Any file | `bg-gray-*` patterns | `bg-[var(--netz-surface-alt)]` or `bg-[var(--netz-surface-inset)]` |
| Any file | `text-white` on brand-primary bg | Keep (intentional contrast) |

**Token migration mapping table (from CSS Token Audit Research):**

| Hardcoded Class | Semantic Intent | Token Replacement |
|---|---|---|
| `bg-white` | Main surface background | `bg-[var(--netz-surface)]` |
| `bg-gray-50`, `bg-gray-100` | Alternate/subtle background | `bg-[var(--netz-surface-alt)]` |
| `bg-gray-200`, `bg-gray-300` | Inset/recessed background | `bg-[var(--netz-surface-inset)]` |
| `text-gray-900` | Primary body text | `text-[var(--netz-text-primary)]` |
| `text-gray-500`, `text-gray-600` | Secondary/supporting text | `text-[var(--netz-text-secondary)]` |
| `text-gray-400` | Muted/caption text | `text-[var(--netz-text-muted)]` |
| `border-gray-200`, `border-gray-300` | Standard borders | `border-[var(--netz-border)]` |
| `#10B981` (green hex) | Success status | `var(--netz-success)` |
| `#EF4444` (red hex) | Danger/error status | `var(--netz-danger)` |
| `#F59E0B` (amber hex) | Warning status | `var(--netz-warning)` |

> **Pitfall: Opacity modifiers** — `text-gray-500/80` (Tailwind opacity) does not translate to `text-[var(--netz-text-secondary)]` directly because CSS custom properties don't support Tailwind's opacity modifier. If encountered, use `opacity-80` as a separate utility or `color-mix()`. (CSS Token Audit Research)

**Approach:** Run full grep, fix file by file, one commit per file for clean revert granularity:

```bash
# Diagnostic: find all hardcoded colors in credit frontend
grep -rn "bg-white\|bg-gray\|bg-slate\|text-gray\|text-slate\|border-gray\|border-slate" \
  frontends/credit/src/ --include="*.svelte" | grep -v "text-white"
```

##### 1d. Svelte 5 Mini-Fixes (folded in)

While editing files already touched in 1a/1c:

| File | Fix |
|------|-----|
| `ICMemoViewer.svelte` L30-31 | Remove `let memo = $derived(icMemo)` and `let voting = $derived(votingStatus)` — use props directly |

> Index keys in `CopilotChat.svelte` (`{#each messages as message, i (i)}`) are safe — messages are append-only. No change needed. (Simplicity Review)

**Phase 1 Acceptance Criteria:**
- [x] `grep -r "netz-primary\b" frontends/credit/src/` returns ZERO matches
- [x] `grep -r "netz-navy\|netz-blue\|netz-orange\|netz-slate\|netz-light" frontends/credit/src/` returns ZERO matches
- [x] `grep -r "icon:" frontends/credit/src/routes/+layout.svelte` returns ZERO matches
- [x] `grep -rn "bg-white\|bg-gray\|bg-slate\|text-gray\|text-slate\|border-gray\|border-slate" frontends/credit/src/ --include="*.svelte" | grep -v "text-white"` returns ZERO matches
- [x] `<html>` tag has `data-theme="light"` in source HTML with sentinel comment
- [x] `hooks.server.ts` exports `sequence(authHook, themeHook)` with `VALID_THEMES` allowlist
- [ ] Setting `localStorage.setItem('netz-theme', 'dark')` + reload renders dark surfaces
- [ ] No FOUC visible on reload (both themes)
- [x] No passthrough `$derived` in ICMemoViewer
- [ ] `pnpm --filter netz-credit-intelligence check` passes
- [ ] Visual validation: Dashboard, Copilot, Documents, Pipeline, IC Memo, Error pages, Sign-in — both themes

---

#### Phase 2: ContextSidebar for Fund Detail Pages

**Goal:** Replace inline `PageHeader` tabs in `[fundId]/+layout.svelte` with `ContextSidebar` via `AppLayout` prop using the context + `$state` hybrid pattern.

> **CRITICAL: First production use of ContextSidebar in AppLayout.** Neither frontend currently uses `contextNav`. Credit will be the first consumer. This phase requires explicit navigation-sequence testing. (Architecture Review)

**New file: `src/lib/state/context-nav.svelte.ts`**

```typescript
import { getContext, setContext } from "svelte";
import type { ContextNav } from "@netz/ui/utils";

const KEY = Symbol("netz:contextNav");

interface ContextNavState {
  current: ContextNav | null;
}

/** Call once in root +layout.svelte to create the per-request instance. */
export function initContextNav(): ContextNavState {
  const state: ContextNavState = $state({ current: null });
  setContext(KEY, state);
  return state;
}

/** Call in any descendant layout/component to read or write contextNav. */
export function useContextNav(): ContextNavState {
  return getContext<ContextNavState>(KEY);
}
```

**Why `.svelte.ts`:** Svelte 5 `$state` rune requires the `.svelte.ts` extension for non-component files. The rune creates fine-grained reactivity — when `state.current` changes, only the reading components re-render. (Svelte 5 Store Research)

**Modified file: `src/routes/+layout.svelte`**

```svelte
<script lang="ts">
  import "../app.css";
  import { AppLayout } from "@netz/ui";
  import type { NavItem } from "@netz/ui/utils";
  import type { LayoutData } from "./$types";
  import { initContextNav } from "$lib/state/context-nav.svelte";

  let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

  const contextNavState = initContextNav();

  const navItems: NavItem[] = [
    { label: "Dashboard", href: "/dashboard" },
    { label: "Pipeline", href: "/pipeline" },
    { label: "Portfolio", href: "/portfolio" },
    { label: "Documents", href: "/documents" },
    { label: "Reporting", href: "/reporting" },
    { label: "Copilot", href: "/copilot" },
  ];
</script>

<AppLayout
  {navItems}
  appName="Netz Credit"
  branding={data.branding}
  token={data.token}
  contextNav={contextNavState.current}
  {children}
/>
```

**Modified file: `src/routes/(team)/funds/[fundId]/+layout.svelte`**

```svelte
<script lang="ts">
  import { page } from "$app/state";
  import { PageHeader } from "@netz/ui";
  import { useContextNav } from "$lib/state/context-nav.svelte";
  import type { Snippet } from "svelte";
  import type { LayoutData } from "./$types";

  let { data, children }: { data: LayoutData; children: Snippet } = $props();
  const nav = useContextNav();

  $effect(() => {
    const fundId = data.fund.id;
    const fundName = data.fund.name;
    const pathname = page.url.pathname;

    nav.current = {
      backHref: "/funds",
      backLabel: fundName,
      items: [
        { label: "Pipeline", href: `/funds/${fundId}/pipeline` },
        { label: "Portfolio", href: `/funds/${fundId}/portfolio` },
        { label: "Documents", href: `/funds/${fundId}/documents` },
        { label: "Reporting", href: `/funds/${fundId}/reporting` },
      ],
      activeHref: pathname,
    };

    return () => {
      nav.current = null;
    };
  });
</script>

<PageHeader title={data.fund.name} />

<div class="flex-1 overflow-y-auto">
  {@render children()}
</div>
```

**Research insights applied:**
- Uses `$app/state` (runes-based `page`) instead of `$app/stores` (deprecated `$page`). (Svelte 5 Store Research)
- `$effect` tracks `data.fund.id`, `data.fund.name`, and `page.url.pathname` as reactive dependencies. Re-runs on any change. Cleanup fires on re-run AND on component unmount. (Svelte 5 Store Research)
- SvelteKit layout persistence: the layout is reused (not destroyed/recreated) when navigating between fund sub-routes. The `$effect` correctly re-runs because its dependencies change. (Architecture Review)
- No race conditions: SvelteKit navigation serializes route transitions. A superseded `load` function's result is discarded. (Svelte 5 Store Research)

**Performance note:** The `$effect` creates a new `ContextNav` object on every pathname change within fund context. Svelte 5's fine-grained `$state` proxy handles this efficiently — only the `ContextSidebar` active item class updates. The `TopNav`, branding injection, and session monitor are unaffected. (Performance Oracle)

**ContextSidebar items — matching existing routes:**

| ContextSidebar Item | Route | Exists? |
|---------------------|-------|---------|
| Pipeline | `/funds/[fundId]/pipeline` | Yes |
| Portfolio | `/funds/[fundId]/portfolio` | Yes |
| Documents | `/funds/[fundId]/documents` | Yes |
| Reporting | `/funds/[fundId]/reporting` | Yes |
| ~~Resumo~~ | — | No route (brainstorm aspirational) |
| ~~IC Memo~~ | — | Lives at deal level, not fund level |
| ~~Histórico~~ | — | No route exists |

> Per brainstorm rule "Não criar novas páginas", we use only existing routes.

**Phase 2 Acceptance Criteria:**
- [x] `initContextNav()` / `useContextNav()` exported from `$lib/state/context-nav.svelte.ts`
- [ ] Navigating to `/funds/[fundId]/pipeline` shows ContextSidebar with 4 items + back link
- [ ] Active item has left-border indicator matching current pathname
- [ ] Navigating away from `/funds/[fundId]/` clears the ContextSidebar (list pages get full width)
- [ ] **Cold-start deep-link:** Directly navigating to `/funds/abc/pipeline` (bookmark) renders ContextSidebar correctly
- [ ] **Fund-to-fund navigation:** Navigating from `/funds/abc/pipeline` to `/funds/xyz/documents` updates sidebar items and active state
- [ ] **Fund-to-list navigation:** Navigating from `/funds/abc/pipeline` to `/funds` clears sidebar
- [ ] Responsive: ContextSidebar hidden on mobile (< 1024px)
- [ ] `pnpm --filter netz-credit-intelligence check` passes

---

#### Phase 3: PR Validation Gate

**Not an implementation phase — these are PR-blocking acceptance criteria.**

**Token audit diagnostic:**

```bash
# Find all var(--netz-*) usages not declared in tokens.css
grep -roh "var(--netz-[a-z-]*)" frontends/credit/src/ --include="*.svelte" --include="*.css" \
  | sort -u > /tmp/credit-used.txt
grep -oh "\-\-netz-[a-z-]*:" packages/ui/src/lib/styles/tokens.css \
  | sed 's/://' | sort -u > /tmp/tokens-declared.txt
comm -23 /tmp/credit-used.txt /tmp/tokens-declared.txt
# MUST return empty
```

**Visual validation checklist (both themes):**
- [ ] Dashboard — surfaces dark, text readable, no white artifacts
- [ ] Copilot — chat bubbles and input use tokens, not `bg-white`
- [ ] Fund detail — ContextSidebar with correct items and active state
- [ ] Fund sub-navigation — Pipeline/Portfolio/Documents/Reporting updates active state
- [ ] Documents upload — drop zone border uses token, hover works in dark
- [ ] IC Memo — chapter badges and streaming cursor use `--netz-brand-primary`
- [ ] Error pages (403, 404, 500) — both themes
- [ ] Sign-in page — no raw white/gray artifacts

**PR-blocking gates:**
- [ ] Token audit: zero undeclared tokens
- [ ] Hardcoded color grep: zero results (excluding `text-white`)
- [ ] `pnpm --filter netz-credit-intelligence check` passes
- [ ] `make check` passes (full gate — backend unaffected but verify)

---

## System-Wide Impact

### Interaction Graph

- `packages/ui/tokens.css` → consumed by credit via `app.css` import → no changes needed (aliases exist)
- `packages/ui/AppLayout.svelte` → receives optional `contextNav` prop → first production use
- `packages/ui/ContextSidebar.svelte` → rendered by AppLayout when `contextNav` is truthy
- `packages/ui/branding.ts` → `injectBranding()` → no changes needed
- `hooks.server.ts` → new `themeHook` in `sequence()` → affects all SSR responses
- **Optional `@netz/ui` change:** `createThemeHook()` factory (reduces duplication with Wealth)

### Error Propagation

- `themeHook` failure → HTML baseline `data-theme="light"` (no crash)
- `contextNavState.current` is null → AppLayout renders without sidebar (full-width, graceful)
- Invalid cookie → `VALID_THEMES` Set rejects → falls back to `"light"` (no XSS, confirmed by Security Sentinel)

## Acceptance Criteria

### Functional Requirements

- [x] Navigation items are text-only (no emojis)
- [x] All `var(--netz-primary)` replaced with `var(--netz-brand-primary)`
- [ ] Dark theme renders correctly via localStorage
- [x] First-time visitors get OS preference via `prefers-color-scheme` fallback
- [ ] No FOUC on page reload in either theme
- [ ] Fund detail pages show ContextSidebar with 4 items
- [ ] ContextSidebar disappears when navigating away from fund context
- [x] No hardcoded `bg-white`, `bg-gray-*`, `text-gray-*` in `.svelte` files

### Non-Functional Requirements

- [ ] `pnpm --filter netz-credit-intelligence check` passes
- [x] `make check` passes (full gate)
- [x] Token audit: zero undeclared `var(--netz-*)` tokens

## Dependencies & Prerequisites

- PR #52 merged (delivers `@netz/ui` components and tokens)
- `AppLayout` accepts `contextNav?` prop (verified present)
- `ContextSidebar` component exists (verified present)
- `tokens.css` has `--netz-primary` alias (verified present)

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **First production use of ContextSidebar** | Certain | Medium | Cold-start deep-link + fund-to-fund + fund-to-list navigation tests |
| Missed hardcoded color in obscure route | Medium | Low | Phase 3 grep audit catches strays |
| `themeHook` replace pattern mismatch with `app.html` | Low | High | Sentinel comments in both files link them |
| Investor routes have hardcoded colors | Certain | Low | Tracked as follow-up (separate persona) |
| Theme toggle missing (dark unreachable by users) | Certain | Low | Infrastructure-only PR; toggle in follow-up |
| contextNavState cleanup on rapid navigation | Very Low | Low | Svelte effect teardown is synchronous; SvelteKit serializes navigation |

## Future Considerations

### Follow-up PRs (not in this scope)

1. **Extract `createThemeHook()` to `@netz/ui/utils`** — parameterized by `defaultTheme`, parallels `createClerkHook()`. Refactor both frontends.
2. **Theme toggle component** — add to TopNav trailing slot, write both localStorage + cookie with `SameSite=Lax; httpOnly: false; Secure; path=/; max-age=31536000`.
3. **Investor portal theme** — audit `(investor)` routes for hardcoded colors.
4. **ContextSidebar for deal detail** — `[dealId]` pages could use ContextSidebar if deals get sub-routes.
5. **`stylelint-value-no-unknown-custom-properties`** — add to CI with `importFrom: ["packages/ui/src/lib/styles/tokens.css"]` to enforce D4 automatically.
6. **Document color mapping table** — add to `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md`.
7. **Mark `--netz-primary` alias as DEPRECATED** — add CSS comment in `tokens.css` after all references normalized.
8. **Close todo #129** — theme cookie XSS is already mitigated by `VALID_THEMES` allowlist.

## Out of Scope (explicit exclusions)

Per brainstorm (see: `docs/brainstorms/2026-03-17-credit-frontend-design-refresh-brainstorm.md`):

- **No navigation architecture change** — credit keeps current TopNav via AppLayout
- **No component redesign** — CopilotChat, ICMemoViewer, DealStageTimeline etc. get token normalization only
- **No new pages** — ContextSidebar items must match existing routes
- **No `defaultBranding` change** — light remains the credit default
- **No investor portal changes** — `(investor)` routes deferred
- **No theme toggle UI** — infrastructure only

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-17-credit-frontend-design-refresh-brainstorm.md](docs/brainstorms/2026-03-17-credit-frontend-design-refresh-brainstorm.md) — Key decisions: credit keeps current nav, light default, ContextSidebar for [fundId], token normalization only

### Design Decisions (binding)

- **D2:** Dark + light for ALL frontends — [docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md](docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md)
- **D4:** No undeclared `var(--netz-*)` tokens
- **D5:** No hardcoded hex/Tailwind colors in components

### Institutional Learnings

- **Wealth design refresh patterns:** [docs/solutions/architecture-patterns/wealth-os-design-refresh-multi-agent-review-patterns.md](docs/solutions/architecture-patterns/wealth-os-design-refresh-multi-agent-review-patterns.md) — Lock token file before delegation, agents miss undeclared CSS vars, specialist review agents outperform generalist

### Research References (from deepening)

- [SvelteKit Hooks — transformPageChunk streaming safety](https://svelte.dev/docs/kit/hooks)
- [Mainmatter: Runes and Global State — SSR-safe state patterns](https://mainmatter.com/blog/2025/03/11/global-state-in-svelte-5/)
- [Joy of Code: Share State in Svelte 5 — context + $state hybrid](https://joyofcode.xyz/how-to-share-state-in-svelte-5)
- [SvelteKit State Management — SSR singleton risks](https://svelte.dev/docs/kit/state-management)
- [Captain Codeman: Dark Mode in SvelteKit — FOUC dual mechanism](https://www.captaincodeman.com/implementing-dark-mode-in-sveltekit)
- [stylelint-value-no-unknown-custom-properties — CI token enforcement](https://github.com/csstools/stylelint-value-no-unknown-custom-properties)
- [DTCG Design Tokens Specification 2025.10](https://www.designtokens.org/tr/2025.10/format/)
- [Tailwind CSS v4 Dark Mode — @custom-variant](https://tailwindcss.com/docs/dark-mode)

### Internal References

- `packages/ui/src/lib/styles/tokens.css` — all declared tokens (light + dark)
- `packages/ui/src/lib/layouts/AppLayout.svelte` — `contextNav?` prop interface
- `packages/ui/src/lib/layouts/ContextSidebar.svelte` — `ContextNav` type contract
- `packages/ui/src/lib/utils/branding.ts` — `defaultBranding`, `injectBranding()`
- `frontends/wealth/src/hooks.server.ts` — themeHook reference implementation
- `frontends/wealth/src/app.html` — FOUC prevention script reference
