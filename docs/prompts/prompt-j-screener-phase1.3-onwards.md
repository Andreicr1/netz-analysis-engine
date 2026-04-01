# Execute: Screener Stabilization — P1.3 + Phase 2–4

## Context

Continuation of `docs/prompts/prompt-i-screener-stabilization-backlog.md`.

**Completed (previous session):**
- P0.1 (alembic varchar), P0.2 (vite OOM), P0.3 (CI green + deploy) — all done
- P1.1 (locale USD/en-US), P1.2 (holdings N-PORT endpoint) — all done
- CI fully green at `ee3df6c`, Railway deployed

**Confirmed broken:** Dashboard and Risk pages still crash in production after deploy.
The riskStore delay (`60e7231`) and ErrorBoundary (`d7f53e7`) were insufficient.

---

## Execute in order

### 1. P1.3 — Fix Dashboard/Risk runtime crashes (PRIORITY)

Dashboard and Risk pages crash when connected to real backend. Dev works because API calls
fail silently → empty state renders. Prod fails because real data shapes don't match
frontend expectations.

**Files to change:**

**1a. `frontends/wealth/src/routes/(app)/dashboard/+page.svelte`:**
- Add null guards on all `data.*` access paths
- The `driftAlerts` derived on line 88 accesses `riskStore.driftAlerts.dtw_alerts` — if
  `driftAlerts` is undefined (SSE not connected), this throws. Wrap with `?.` and `?? []`
- Same for `behaviorAlerts` on line 91
- Guard `getCvar()` — if `data.riskSummary` has unexpected shape (array instead of dict,
  or different key casing), the type assertion crashes. Add runtime type check.
- Guard `getSnapshot()` — same defensive pattern

**1b. `frontends/wealth/src/routes/(app)/risk/+page.svelte`:**
- Create `+page.server.ts` with SSR data load (same endpoints as dashboard `+page.server.ts`)
  as fallback data. Currently this page has NO server load — 100% SSE-dependent.
- Guard `sparkBars()` (line 80) — check `history` is an array before `.slice()`. If
  `riskStore.cvarHistoryByProfile[profileId]` is undefined, `sparkBars(undefined)` crashes.
- Guard `profiles` derived (line 23) — `Object.entries(riskStore.cvarByProfile)` is safe
  when empty `{}`, but if SSE pushes `null`, it throws. Add `?? {}` fallback.
- Add `{#if storeStatus === 'loading'}` skeleton/loading state before rendering data panels
- Guard `regime.regime.toUpperCase()` on line 165 — crashes if `regime.regime` is null

**1c. `frontends/wealth/src/lib/stores/risk-store.svelte.ts`:**
- In `applyUpdate()` (line 151), validate incoming data shape before assigning:
  - `cvarByProfile` should be a plain object (not null, not array)
  - `regime` should have `.regime` string property
  - `driftAlerts` should have `.dtw_alerts` and `.behavior_change_alerts` arrays
- If a field is missing or wrong type, skip that field's update rather than propagating bad data

**Validation:**
- [ ] Dashboard renders without crash when backend returns real data
- [ ] Dashboard renders empty-state gracefully when backend is unreachable
- [ ] Risk page renders loading skeleton while SSE connects
- [ ] Risk page doesn't crash if SSE pushes partial/malformed data
- [ ] No unhandled promise rejections in browser console on either page
- [ ] `pnpm --filter netz-wealth-os run check` passes

---

### 2. P2.1 — Catalog loads on start (default to mutual_fund)

Opening `/screener` with no filter shows "0 FUNDS" (query timeout on 131k rows).

**Fix (Option A):**
- `frontends/wealth/src/routes/(app)/screener/+page.server.ts`: if no `category` URL param,
  default to `fund_universe=mutual_fund` in the API call
- `frontends/wealth/src/routes/(app)/screener/+page.svelte`: initialize `selectedCategories`
  to `["mutual_fund"]` when no URL params present

**Validation:**
- [ ] Opening `/screener` (no params) shows Mutual Funds pre-selected
- [ ] URL reflects `/screener?category=mutual_fund`

---

### 3. P2.2 — Normalize alphabetical sorting

Funds starting with numbers/symbols sort before letters.

**Fix:**
- `backend/app/domains/wealth/queries/catalog_sql.py`: update `_SORT_MAP`:
  ```python
  "name_asc": "REGEXP_REPLACE(name, '^[^a-zA-Z]+', '', 'g') ASC, name ASC",
  "name_desc": "REGEXP_REPLACE(name, '^[^a-zA-Z]+', '', 'g') DESC, name DESC",
  ```

**Validation:**
- [ ] First page starts with "A" names
- [ ] `name_desc` shows Z names first

---

### 4. P3.1 — Add fee/performance data to catalog

`UnifiedFundItem` has no `expense_ratio_pct`, `avg_annual_return_1y`, etc.

**Files:** catalog schema (backend + frontend), `catalog_sql.py` (always LEFT JOIN
`sec_fund_prospectus_stats`), `CatalogTable.svelte` (optional columns),
`CatalogDetailPanel.svelte` (Cost & Performance section).

---

### 5. P3.2 — Fund detail endpoint

New `GET /screener/catalog/{external_id}/detail` returning enriched fund detail with
fee data, performance, risk metrics, manager info, N-CEN flags.

---

### 6. P3.3 — N-CEN flags in catalog table

Surface `is_index_fund`, `is_target_date_fund`, `is_fund_of_fund` as badges + filter toggles.

---

### 7. P4.1 — Error visibility for catalog SSR failures

Show error banner instead of silent "0 FUNDS" when backend is down.

---

### 8. P4.2 — Currency-aware formatting

Pass `fund.currency ?? "USD"` to `formatAUM()` calls in CatalogTable, CatalogDetailPanel,
SecHoldingsTable.

---

## Execution notes

- P1.3 is the blocker — fix first, deploy, verify in production
- P2.1 + P2.2 are quick wins, can follow immediately
- P3.x are feature gaps — larger scope, can be parallelized
- P4.x are polish — safe to defer
- Full spec for each item is in `docs/prompts/prompt-i-screener-stabilization-backlog.md`
- CI is green — all changes should keep it green (`make check` + frontend build)
- After each batch, commit + push to main for Railway auto-deploy

## What NOT to do

- Do NOT change SSE event protocol or riskStore architecture — defensive rendering only
- Do NOT create materialized views without benchmarking first
- Do NOT add fee columns to UNION ALL without matching all 5 branches
- Do NOT hardcode currencies — derive from `fund.currency`
