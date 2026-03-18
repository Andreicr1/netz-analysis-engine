# System Map Validation Report

## 1. Section Validation

### Architecture
- Status: `PARTIALLY VALIDATED`
- Validated:
  - Monorepo structure matches the map: pnpm workspace + Turborepo with `packages/*` and `frontends/*`.
    - Evidence: `package.json`, `pnpm-workspace.yaml`, `turbo.json`
  - All three frontends use SvelteKit, Svelte 5, and `@sveltejs/adapter-node`.
    - Evidence: `frontends/credit/package.json`, `frontends/wealth/package.json`, `frontends/admin/package.json`
    - Evidence: `frontends/credit/svelte.config.js:1`, `frontends/wealth/svelte.config.js:1`, `frontends/admin/svelte.config.js:1`
  - CSP is configured in all three frontend Svelte configs.
    - Evidence: `frontends/credit/svelte.config.js:9`, `frontends/wealth/svelte.config.js:9`, `frontends/admin/svelte.config.js:9`
- Invalid / overstated:
  - Clerk JWT verification exists, but Clerk UI integration is not actually implemented.
    - Map claim: auth uses Clerk JWT + `svelte-clerk` UI.
    - Code reality: sign-in pages are placeholders; no mounted Clerk components; no `svelte-clerk` dependency in frontend manifests.
    - Evidence: `packages/ui/src/lib/utils/auth.ts:115`
    - Evidence: `frontends/credit/src/routes/auth/sign-in/+page.svelte:1`
    - Evidence: `frontends/wealth/src/routes/auth/sign-in/+page.svelte:1`
    - Evidence: `frontends/admin/src/routes/auth/sign-in/+page.svelte:1`
    - Evidence: `frontends/credit/package.json`
    - Evidence: `frontends/wealth/package.json`
    - Evidence: `frontends/admin/package.json`

### Routing
- Status: `INVALID`
- Invalid:
  - Route inventory counts in the system map are wrong.
    - Map claim: 51 pages total, with 19 credit, 22 wealth, 10 admin.
    - Code reality: 54 page-route directories total, with 20 credit, 24 wealth, 10 admin.
    - Evidence:
      - Credit actual route directories include `/` root redirect:
        - `frontends/credit/src/routes/+page.server.ts:1`
      - Wealth actual route directories include `/` root redirect and `/auth/sign-out`:
        - `frontends/wealth/src/routes/+page.server.ts:1`
        - `frontends/wealth/src/routes/auth/sign-out/+page.svelte:1`
  - Admin root redirect is client-side, not a server redirect.
    - Map claim: `(admin)/` redirects to `/health`.
    - Code reality: redirect is performed in `onMount`.
    - Evidence: `frontends/admin/src/routes/(admin)/+page.svelte:1`
- Validated:
  - Admin route matchers exist for `orgId` and `vertical`.
    - Evidence: `frontends/admin/src/params/orgId.ts:1`
    - Evidence: `frontends/admin/src/params/vertical.ts:1`
- Missing from map:
  - Wealth dynamic `profile` route has no matcher-based validation.
    - Evidence: `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.server.ts:5`

### State Management
- Status: `PARTIALLY VALIDATED`
- Validated:
  - Shared token context is provided by `AppLayout`.
    - Evidence: `packages/ui/src/lib/layouts/AppLayout.svelte:43`
  - Wealth team layout creates and provides a shared `riskStore` via Svelte context.
    - Evidence: `frontends/wealth/src/routes/(team)/+layout.svelte:15`
  - Credit and admin use `contextNav` in scoped layouts.
    - Evidence: `frontends/credit/src/routes/(team)/funds/[fundId]/+layout.svelte:12`
    - Evidence: `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+layout.svelte:10`
- Invalid / inconsistent:
  - Admin does not consistently use shared token context; it passes `token` through page data and props.
    - Map claim: auth token lives in AppLayout context for all pages.
    - Code reality: admin components repeatedly construct client APIs from `data.token` / prop `token`.
    - Evidence: `frontends/admin/src/routes/+layout.server.ts:21`
    - Evidence: `frontends/admin/src/routes/(admin)/health/+page.svelte:21`
    - Evidence: `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte:106`
    - Evidence: `frontends/admin/src/lib/components/ConfigEditor.svelte:31`
    - Evidence: `frontends/admin/src/lib/components/PromptEditor.svelte:46`
    - Evidence: `frontends/admin/src/lib/components/WorkerLogFeed.svelte:9`
- Validated:
  - No `localStorage` usage beyond theme bootstrap was found.
    - Evidence: `frontends/credit/src/app.html:13`
    - Evidence: `frontends/wealth/src/app.html:13`
    - Evidence: `frontends/admin/src/app.html:11`

### Data Fetching / SSE / Polling
- Status: `INVALID`
- Validated:
  - Shared API client exists and provides typed error handling, timeout, 401 redirect, 409 conflict hook.
    - Evidence: `packages/ui/src/lib/utils/api-client.ts:147`
  - Shared SSE client exists and uses `fetch()` + `ReadableStream`, not `EventSource`.
    - Evidence: `packages/ui/src/lib/utils/sse-client.svelte.ts:1`
  - Shared poller utility exists.
    - Evidence: `packages/ui/src/lib/utils/poller.svelte.ts:28`
  - Many server loaders do use `createServerApiClient` + `Promise.allSettled`.
    - Evidence: `frontends/wealth/src/routes/(team)/dashboard/+page.server.ts:20`
    - Evidence: `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.server.ts:7`
- Invalid / inconsistent:
  - Server loader pattern is not universal.
    - Map claim: all `+page.server.ts` use `createServerApiClient(token) -> Promise.allSettled()`.
    - Code reality: multiple loaders use sequential `try/catch`, single fetches, or pure redirects.
    - Evidence: `frontends/admin/src/routes/(admin)/health/+page.server.ts:22`
    - Evidence: `frontends/admin/src/routes/(admin)/tenants/+page.server.ts:7`
    - Evidence: `frontends/credit/src/routes/(investor)/documents/+page.server.ts:14`
    - Evidence: `frontends/credit/src/routes/(team)/funds/+page.server.ts:16`
    - Evidence: `frontends/credit/src/routes/+page.server.ts:5`
  - SSE implementation is not standardized.
    - Map claim: SSE behavior is governed by shared utilities and registry.
    - Code reality: some flows use `createSSEStream`, while others hand-roll fetch-stream parsing and bypass registry behavior.
    - Evidence: `frontends/credit/src/lib/components/ICMemoViewer.svelte:55`
    - Evidence: `frontends/credit/src/lib/components/IngestionProgress.svelte:28`
    - Evidence: `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:117`
    - Evidence: `frontends/admin/src/lib/components/WorkerLogFeed.svelte:37`
    - Evidence: `frontends/wealth/src/lib/components/FundDetailPanel.svelte:93`
  - SSE registry cap is not architecture-wide.
    - Map claim: registry-enforced max 4 connections per tab.
    - Code reality: only shared `createSSEStream` registers; manual streaming code ignores the registry entirely.
    - Evidence: `packages/ui/src/lib/utils/sse-registry.svelte.ts:16`
    - Evidence: `packages/ui/src/lib/utils/sse-client.svelte.ts:74`
    - Evidence: `frontends/admin/src/lib/components/WorkerLogFeed.svelte:29`
    - Evidence: `frontends/wealth/src/lib/components/FundDetailPanel.svelte:87`
  - Polling implementation is inconsistent.
    - Map claim: risk store uses self-scheduling polling, backtest uses `createPoller`.
    - Code reality:
      - Risk store does self-scheduling `setTimeout`.
        - Evidence: `frontends/wealth/src/lib/stores/risk-store.svelte.ts:175`
      - Analytics backtest does not use `createPoller`; it uses a manual async retry loop.
        - Evidence: `frontends/wealth/src/routes/(team)/analytics/+page.svelte:199`
      - Content page uses raw `setInterval`.
        - Evidence: `frontends/wealth/src/routes/(team)/content/+page.svelte:103`
      - Admin health page uses raw `setInterval`.
        - Evidence: `frontends/admin/src/routes/(admin)/health/+page.svelte:18`
  - `createSSEWithSnapshot` is exported but unused.
    - Map claim: available, not yet used.
    - Code reality: confirmed unused in frontends.
    - Evidence: `packages/ui/src/lib/index.ts:88`
    - Evidence: `packages/ui/src/lib/utils/sse-client.svelte.ts:207`

### Component Structure
- Status: `PARTIALLY VALIDATED`
- Validated:
  - `@netz/ui` exports the shared design system primitives, composites, layouts, charts, and utilities described by the map.
    - Evidence: `packages/ui/src/lib/index.ts:5`
  - Domain-local component counts match the map.
    - Credit: 8 components
      - Evidence: `frontends/credit/src/lib/components`
    - Wealth: 4 components
      - Evidence: `frontends/wealth/src/lib/components`
    - Admin: 7 components
      - Evidence: `frontends/admin/src/lib/components`
- Invalid / incomplete:
  - Shared-component discipline is weaker than the map suggests because duplicated local glue exists outside `@netz/ui`.
    - Duplicated API wrappers:
      - `frontends/credit/src/lib/api/client.ts:1`
      - `frontends/wealth/src/lib/api/client.ts:1`
      - `frontends/admin/src/lib/api/client.ts:1`
    - Duplicated context-nav implementation:
      - `frontends/credit/src/lib/state/context-nav.svelte.ts:1`
      - `frontends/admin/src/lib/state/context-nav.svelte.ts:1`
    - Duplicated investor layouts:
      - `frontends/credit/src/routes/(investor)/+layout.svelte:1`
      - `frontends/wealth/src/routes/(investor)/+layout.svelte:1`
      - Shared shell already exists in `packages/ui`:
        - `packages/ui/src/lib/layouts/InvestorShell.svelte:1`
- Cross-import policy:
  - No cross-import violations were found between frontend apps.
  - Evidence:
    - `frontends/credit/package.json`
    - `frontends/wealth/package.json`
    - `frontends/admin/package.json`

## 2. Confirmed Elements

- Monorepo structure with `packages/ui` and three frontend apps is real.
  - Evidence: `pnpm-workspace.yaml`, `package.json`, `turbo.json`
- All three frontends use SvelteKit + adapter-node.
  - Evidence: `frontends/credit/svelte.config.js:1`, `frontends/wealth/svelte.config.js:1`, `frontends/admin/svelte.config.js:1`
- CSP is configured in all three frontends.
  - Evidence: `frontends/credit/svelte.config.js:9`, `frontends/wealth/svelte.config.js:9`, `frontends/admin/svelte.config.js:9`
- Shared `AppLayout` provides `netz:getToken`, session-expiry warning, conflict handler, branding injection.
  - Evidence: `packages/ui/src/lib/layouts/AppLayout.svelte:43`
- Wealth team routes create and share a risk store via context.
  - Evidence: `frontends/wealth/src/routes/(team)/+layout.svelte:15`
- Credit and admin detail routes use context navigation sidebars.
  - Evidence: `frontends/credit/src/routes/(team)/funds/[fundId]/+layout.svelte:19`
  - Evidence: `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+layout.svelte:18`
- Shared API client supports timeout, typed errors, and conflict/auth hooks.
  - Evidence: `packages/ui/src/lib/utils/api-client.ts:89`
- Shared SSE client uses authenticated `fetch()` + `ReadableStream`.
  - Evidence: `packages/ui/src/lib/utils/sse-client.svelte.ts:85`
- Shared poller utility exists.
  - Evidence: `packages/ui/src/lib/utils/poller.svelte.ts:28`
- Route matchers exist for admin `orgId` and `vertical`.
  - Evidence: `frontends/admin/src/params/orgId.ts:1`
  - Evidence: `frontends/admin/src/params/vertical.ts:1`
- DOMPurify is used on admin prompt preview and wealth DD report HTML rendering.
  - Evidence: `frontends/admin/src/lib/components/PromptEditor.svelte:9`
  - Evidence: `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte:12`
- Tailwind v4 `@source` for `packages/ui` is configured in all three frontend `app.css` files.
  - Evidence: `frontends/credit/src/app.css:6`
  - Evidence: `frontends/wealth/src/app.css:6`
  - Evidence: `frontends/admin/src/app.css:6`

## 3. Contradictions

### Route Inventory
- Claim:
  - System map reports 19 credit routes and 22 wealth routes.
- Reality:
  - Credit has 20 route directories with page files.
  - Wealth has 24 route directories with page files.
  - Omitted routes:
    - credit `/`
    - wealth `/`
    - wealth `/auth/sign-out`
- Evidence:
  - `frontends/credit/src/routes/+page.server.ts:1`
  - `frontends/wealth/src/routes/+page.server.ts:1`
  - `frontends/wealth/src/routes/auth/sign-out/+page.svelte:1`

### Admin Redirect Semantics
- Claim:
  - `(admin)/` redirects to `/health`.
- Reality:
  - Redirect is client-side in `onMount`, not server-side.
- Evidence:
  - `frontends/admin/src/routes/(admin)/+page.svelte:1`

### Clerk UI Integration
- Claim:
  - Auth uses Clerk UI / `svelte-clerk`.
- Reality:
  - Shared hook verifies JWTs, but sign-in pages are placeholders and sign-out pages just redirect.
  - No frontend package declares `svelte-clerk`.
- Evidence:
  - `packages/ui/src/lib/utils/auth.ts:115`
  - `frontends/credit/src/routes/auth/sign-in/+page.svelte:27`
  - `frontends/wealth/src/routes/auth/sign-in/+page.svelte:27`
  - `frontends/credit/src/routes/auth/sign-out/+page.svelte:8`
  - `frontends/wealth/src/routes/auth/sign-out/+page.svelte:8`
  - `frontends/credit/package.json`
  - `frontends/wealth/package.json`
  - `frontends/admin/package.json`

### Copilot Streaming
- Claim:
  - Credit copilot uses SSE streaming.
- Reality:
  - It performs a standard POST to `/ai/answer` and replaces the pending assistant message when the full response returns.
- Evidence:
  - `frontends/credit/src/routes/(team)/copilot/+page.svelte:35`

### Server Load Pattern
- Claim:
  - All `+page.server.ts` use `createServerApiClient(token) -> Promise.allSettled()`.
- Reality:
  - Several loaders use direct single calls, sequential `try/catch`, or pure redirects.
- Evidence:
  - `frontends/admin/src/routes/(admin)/health/+page.server.ts:22`
  - `frontends/admin/src/routes/(admin)/tenants/+page.server.ts:7`
  - `frontends/credit/src/routes/(investor)/documents/+page.server.ts:14`
  - `frontends/credit/src/routes/(team)/funds/+page.server.ts:16`
  - `frontends/credit/src/routes/+page.server.ts:5`

### SSE Registry Enforcement
- Claim:
  - Shared SSE registry enforces max 4 connections per tab.
- Reality:
  - Only streams created through `createSSEStream` participate; ad hoc stream readers bypass registry limits.
- Evidence:
  - `packages/ui/src/lib/utils/sse-registry.svelte.ts:16`
  - `packages/ui/src/lib/utils/sse-client.svelte.ts:74`
  - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:29`
  - `frontends/wealth/src/lib/components/FundDetailPanel.svelte:87`

### Backtest Polling Pattern
- Claim:
  - Analytics backtest polling uses `createPoller`.
- Reality:
  - The page comment says it does, but the implementation is a manual loop with `setTimeout` via awaited promises and a stop flag.
- Evidence:
  - `frontends/wealth/src/routes/(team)/analytics/+page.svelte:199`
  - `frontends/wealth/src/routes/(team)/analytics/+page.svelte:213`

### Document Review Confirmation Workflow
- Claim:
  - Credit document review reject uses `ConfirmDialog`.
- Reality:
  - Reject and revision-request actions call `submitDecision` directly; only finalize uses `ConfirmDialog`.
- Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:153`
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:243`

### Theme Persistence Model
- Claim:
  - Theme is persisted in cookie and SSR hook prevents FOUC.
- Reality:
  - Server hook reads cookie, but client bootstrap reads `localStorage`.
  - No code in the inspected frontend layer writes either cookie or `localStorage`, so persistence flow is not described accurately.
- Evidence:
  - `packages/ui/src/lib/utils/theme.ts:13`
  - `frontends/credit/src/app.html:13`
  - `frontends/wealth/src/app.html:13`
  - `frontends/admin/src/app.html:11`

### Wealth Dashboard Robustness
- Claim:
  - Wealth dashboard has a NAV chart.
- Reality:
  - The chart is an empty placeholder with `series={[]}` and `empty={true}`.
- Evidence:
  - `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:192`

### Config Diff Robustness
- Claim:
  - Admin config editor includes diff viewer in a robust optimistic-lock workflow.
- Reality:
  - Diff viewer requests a hard-coded placeholder `org_id`, not the active tenant/org context.
- Evidence:
  - `frontends/admin/src/lib/components/ConfigDiffViewer.svelte:32`

## 4. Hidden Patterns

- Token handling is split between context-based access and explicit token prop drilling.
  - Evidence:
    - Shared context: `packages/ui/src/lib/layouts/AppLayout.svelte:44`
    - Admin token props: `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte:106`, `frontends/admin/src/lib/components/PromptEditor.svelte:20`

- Multiple polling strategies solve the same problem differently.
  - Shared poller:
    - `packages/ui/src/lib/utils/poller.svelte.ts:28`
  - Self-scheduling timeout:
    - `frontends/wealth/src/lib/stores/risk-store.svelte.ts:175`
  - Raw `setInterval` invalidate loop:
    - `frontends/wealth/src/routes/(team)/content/+page.svelte:103`
  - Raw `setInterval` API refresh:
    - `frontends/admin/src/routes/(admin)/health/+page.svelte:18`
  - Manual async polling loop:
    - `frontends/wealth/src/routes/(team)/analytics/+page.svelte:213`

- Multiple streaming implementations solve the same problem differently.
  - Shared `createSSEStream`:
    - `frontends/credit/src/lib/components/IngestionProgress.svelte:28`
    - `frontends/credit/src/lib/components/ICMemoViewer.svelte:55`
    - `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:117`
  - Ad hoc fetch-stream:
    - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:37`
    - `frontends/wealth/src/lib/components/FundDetailPanel.svelte:93`

- Component composition is less centralized than the map implies.
  - Shared `InvestorShell` exists, but each frontend duplicates the layout wrapper logic.
    - `packages/ui/src/lib/layouts/InvestorShell.svelte:1`
    - `frontends/credit/src/routes/(investor)/+layout.svelte:1`
    - `frontends/wealth/src/routes/(investor)/+layout.svelte:1`

- API client glue is duplicated across apps instead of centralized.
  - `frontends/credit/src/lib/api/client.ts:1`
  - `frontends/wealth/src/lib/api/client.ts:1`
  - `frontends/admin/src/lib/api/client.ts:1`

- Context-nav state implementation is duplicated.
  - `frontends/credit/src/lib/state/context-nav.svelte.ts:1`
  - `frontends/admin/src/lib/state/context-nav.svelte.ts:1`

- Table implementations are inconsistent.
  - Shared `DataTable`:
    - `packages/ui/src/lib/components/DataTable.svelte:1`
  - Raw table:
    - `frontends/wealth/src/routes/(team)/funds/+page.svelte:223`
    - `frontends/admin/src/routes/(admin)/health/+page.svelte:63`
  - Virtualized bespoke table:
    - `frontends/wealth/src/routes/(team)/screener/+page.svelte:102`

## 5. Missing Critical Elements

- Silent error handling and empty fallbacks are not captured as a systemic pattern.
  - Evidence:
    - `frontends/admin/src/routes/(admin)/health/+page.server.ts:22`
    - `frontends/admin/src/routes/(admin)/tenants/+page.server.ts:7`
    - `frontends/credit/src/routes/(investor)/documents/+page.server.ts:15`

- Placeholder or no-op UX flows are not described.
  - Wealth fund detail DD report empty-state action is a no-op.
    - Evidence: `frontends/wealth/src/lib/components/FundDetailPanel.svelte:342`
  - Clerk auth UI mounting is not implemented.
    - Evidence: `frontends/credit/src/routes/auth/sign-in/+page.svelte:27`
    - Evidence: `frontends/wealth/src/routes/auth/sign-in/+page.svelte:27`

- Worker logs are not live by default; operator must manually connect.
  - Evidence:
    - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:103`

- Route-param validation coverage is incomplete and not described honestly.
  - Admin uses matchers, but wealth `profile` does not.
  - Evidence:
    - `frontends/admin/src/params/orgId.ts:1`
    - `frontends/admin/src/params/vertical.ts:1`
    - `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.server.ts:8`

- Theme persistence mechanism is incomplete in the map.
  - SSR hook uses cookie, client bootstrap uses `localStorage`, and the persistence writer path is absent from the inspected frontend code.
  - Evidence:
    - `packages/ui/src/lib/utils/theme.ts:13`
    - `frontends/credit/src/app.html:13`
    - `frontends/wealth/src/app.html:13`
    - `frontends/admin/src/app.html:11`

- Admin config diff behavior lacks active-org awareness.
  - Evidence:
    - `frontends/admin/src/lib/components/ConfigDiffViewer.svelte:32`

## 6. Structural Risks

- Shared abstractions exist but are not enforced consistently.
  - Impact:
    - Architecture drift is already present in streaming, polling, token access, and server loading patterns.
  - Evidence:
    - `packages/ui/src/lib/utils/poller.svelte.ts:28`
    - `frontends/wealth/src/routes/(team)/analytics/+page.svelte:213`
    - `packages/ui/src/lib/utils/sse-client.svelte.ts:34`
    - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:37`

- SSE connection limit is not a reliable system-level invariant.
  - Impact:
    - Real connection pressure can exceed the documented 4-connection narrative because bespoke streams bypass registry accounting.
  - Evidence:
    - `packages/ui/src/lib/utils/sse-registry.svelte.ts:16`
    - `frontends/admin/src/lib/components/WorkerLogFeed.svelte:29`
    - `frontends/wealth/src/lib/components/FundDetailPanel.svelte:87`

- Auth/token handling is fragmented.
  - Impact:
    - Increases coupling to page data shape, duplicates auth access patterns, and weakens the shared context abstraction.
  - Evidence:
    - `packages/ui/src/lib/layouts/AppLayout.svelte:44`
    - `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte:106`
    - `frontends/admin/src/lib/components/ConfigEditor.svelte:31`

- Theme state has dual sources of truth.
  - Impact:
    - Cookie-based SSR and `localStorage`-based client bootstrap can drift; the map overstates robustness.
  - Evidence:
    - `packages/ui/src/lib/utils/theme.ts:13`
    - `frontends/credit/src/app.html:13`
    - `frontends/wealth/src/app.html:13`
    - `frontends/admin/src/app.html:11`

- Route inventory in the map is already stale or manually maintained.
  - Impact:
    - The artifact itself cannot be trusted as a routing source of truth unless generated from the filesystem.
  - Evidence:
    - `frontends/credit/src/routes/+page.server.ts:1`
    - `frontends/wealth/src/routes/+page.server.ts:1`
    - `frontends/wealth/src/routes/auth/sign-out/+page.svelte:1`

- Duplicate wrappers and layout glue add maintainability risk.
  - Impact:
    - Small cross-cutting changes require synchronized edits in multiple apps.
  - Evidence:
    - `frontends/credit/src/lib/api/client.ts:1`
    - `frontends/wealth/src/lib/api/client.ts:1`
    - `frontends/admin/src/lib/api/client.ts:1`
    - `frontends/credit/src/lib/state/context-nav.svelte.ts:1`
    - `frontends/admin/src/lib/state/context-nav.svelte.ts:1`
    - `frontends/credit/src/routes/(investor)/+layout.svelte:1`
    - `frontends/wealth/src/routes/(investor)/+layout.svelte:1`
