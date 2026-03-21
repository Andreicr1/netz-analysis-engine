---
status: pending
priority: p2
issue_id: "203"
tags: [frontend, wealth, svelte, manager-screener]
dependencies: ["201"]
---

# Manager Screener frontend page (Wealth OS)

## Problem Statement

The Wealth OS frontend needs a Manager Screener page for discovering, filtering, and comparing SEC-registered investment managers.

## Proposed Solution

### Approach

Create SvelteKit page at `frontends/wealth/src/routes/(team)/manager-screener/`:

1. **`+page.server.ts`** — server load function calling `GET /api/v1/manager-screener` with query params from URL searchParams. Handles pagination, filter serialization.

2. **`+page.svelte`** — main page with:
   - **Filter sidebar** (5 collapsible blocks matching backend filter groups):
     - Firma: AUM range slider, strategy types multi-select, states/countries, compliance toggle, ADV date range, text search
     - Portfolio: sectors multi-select, HHI range, position count range, portfolio value min
     - Drift: style drift toggle, turnover range, high activity quarters
     - Institutional: has holders toggle, holder types
     - Universe: status multi-select
   - **Results table** with VirtualList-compatible pagination (server-side)
   - **Manager detail drawer/modal** with tabs: Profile, Holdings, Drift, Institutional, Universe
   - **Compare mode:** checkbox selection (2-5), compare button triggers `POST /managers/compare`
   - **Add to Universe button** on detail view → `POST /managers/{crd}/add-to-universe` with asset class/geography dialog

3. **Formatting:** Use `@netz/ui` formatters (`formatNumber`, `formatCurrency`, `formatPercent`) — never `.toFixed()` or inline `Intl`.

4. **SSE not needed** — all data is request/response, no streaming.

## Technical Details

**Affected files:**
- `frontends/wealth/src/routes/(team)/manager-screener/+page.server.ts` — new
- `frontends/wealth/src/routes/(team)/manager-screener/+page.svelte` — new

**Constraints:**
- Svelte 5 runes syntax (`$state`, `$derived`, `$effect`)
- Use `@netz/ui` components and formatters exclusively
- No cross-import from credit frontend
- URL-driven filters (searchParams → server load → API call) for shareable URLs

## Acceptance Criteria

- [ ] Page renders with filter sidebar and results table
- [ ] All 5 filter blocks functional and reflected in URL searchParams
- [ ] Pagination works with total count display
- [ ] Manager detail view shows all 5 tabs (profile, holdings, drift, institutional, universe)
- [ ] Compare mode allows 2-5 manager selection with side-by-side view
- [ ] Add to Universe action opens dialog and calls POST endpoint
- [ ] All formatting uses `@netz/ui` formatters
- [ ] `make check-all` passes
