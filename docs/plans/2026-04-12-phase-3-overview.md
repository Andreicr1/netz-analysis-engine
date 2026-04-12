# Phase 3 — Screener Fast Path Overview

**Date:** 2026-04-12
**Status:** Planning complete, briefs ready for execution
**Branch target:** `feat/phase-3-session-{a,b,c}`
**Depends on:** Phase 2 Data Plane complete (main at `eacf065e` or later)

## Mission

Ship the Screener as the **first real consumer** of Phase 1 shell foundations + Phase 2 data plane. After Phase 3, the terminal has a working institutional-grade screener that:

- Shows 9k+ funds in a virtualized grid with inline sparklines
- Filters by ELITE (300 best-scored, proportional to strategic allocation) as a first-class chip
- Opens FocusMode on row click (replacing the legacy FundWarRoomModal)
- Sends liquid funds directly to Approved Universe in one click (`[→ UNIVERSE]`)
- Queues DD for illiquid funds in one click (`[+ DD]`)
- Persists all filter/sort/page state in URL (reload-safe, shareable)
- Responds to keyboard shortcuts (`/`, `↑↓`, `Enter`, `u`, `d`, `e`)
- Reads from `mv_fund_risk_latest` + `v_screener_org_membership` for sub-100ms responses

## Key decisions (locked)

1. **Backend before frontend** — Session A (backend) ships and merges before Session B (frontend) starts. Per mandate `feedback_infra_before_visual.md`: visual polish only valid when infrastructure correct.
2. **`registerFocusTrigger`** — Part C did NOT ship this. Session B creates it as a `use:action` directive that any row element can attach to trigger `openFocus()`.
3. **`FundWarRoomModal` deletion** — Session B deletes it after rewiring to `FundFocusMode`. The legacy modal pattern dies here.
4. **Keyset pagination** — replaces offset-based. Mandatory for stable sort at high page counts. Frontend sends `cursor` param; backend uses `(composite_score, aum_usd, external_id) > (:cursor)` tiebreaker.
5. **Batch sparkline endpoint** — returns NAV monthly data for N instruments in one request. Grid renders sparklines only for visible rows.

## Audit-derived scope

Full audit at `docs/audits/Phase-3-Scope-Audit-Investigation-Report.md`. Key findings:

| Area | Current state | Phase 3 action |
|---|---|---|
| `GET /screener/catalog` route | Reads `mv_unified_funds` via `catalog_sql.py`, no MV join | Refactor to JOIN `mv_fund_risk_latest` + `v_screener_org_membership` |
| `GET /screener/catalog/elite` | EXISTS, reads `mv_fund_risk_latest` | Preserve, extend if needed |
| `elite_flag` in response | Missing from main catalog response | Add to schema |
| Batch sparkline endpoint | Missing | Create |
| Fast-track `/universe/approve` | Exists but requires pre-existing record | Add liquid fast-track |
| Pagination | Offset-based | Migrate to keyset |
| DataGrid virtualization | None (standard `{#each}`) | Add IntersectionObserver |
| ELITE filter chip | Missing | Create |
| URL state sync | Missing (local state) | Add |
| Row click → FocusMode | Legacy `onOpenWarRoom` → `FundWarRoomModal` | Rewire to `openFocus` → `FundFocusMode` |
| `registerFocusTrigger` | Missing from codebase | Create as `use:action` |
| Inline sparklines | Missing | Add via batch endpoint |
| Action column `[→ UNIVERSE]`/`[+ DD]` | Missing | Create |
| Keyboard shortcuts | None in screener | Wire |
| Backend integration tests | Zero | Create |
| Frontend tests | Zero | Deferred (Phase 4+) |

## 3-session split

**Session A — Backend alignment (6 commits).** Refactor screener routes to consume Phase 2 MVs, create batch sparkline endpoint, add fast-track liquid support, migrate to keyset pagination, ship integration tests. After merge: screener backend returns ELITE flag, org membership marker, sparkline batch data, accepts universe approval fast-track.

**Session B — Screener shell refactor (5 commits).** Create `registerFocusTrigger`, rewire row click to `FundFocusMode`, add ELITE filter chip with amber badge, implement URL state sync, delete `FundWarRoomModal`. After merge: screener uses Part C FocusMode, ELITE filter works, URL is deep-linkable, War Room modal deleted.

**Session C — DataGrid features (5 commits).** DataGrid virtualization for 9k+ rows, inline sparklines (visible rows only), action column (`[→ UNIVERSE]`/`[+ DD]`), keyboard shortcuts, integration smoke test. After merge: screener is production-grade institutional terminal.

## Dependency flow

```
Session A (Backend) ──merge──→ Session B (Shell refactor) ──merge──→ Session C (DataGrid features)
```

Each session is a merge gate. Backend ships and proves correct before frontend consumes. Frontend shell refactor proves correct before DataGrid features are layered on top.

## Project mandates (binding)

All mandates from Phase 2 overview apply:
- `mandate_high_end_no_shortcuts.md` — install any deps, iterate as needed
- `feedback_infra_before_visual.md` — backend correct before frontend consumes
- `feedback_smart_backend_dumb_frontend.md` — no CVaR/DTW/regime jargon in API responses
- `feedback_screener_macro_ux.md` — screener = ONE unified filter (no provider-named categories)
- `feedback_datagrid_vs_viewer.md` — selection tables show 4-6 cols max; detail goes to Focus Mode
- `feedback_echarts_no_localstorage.md` — svelte-echarts mandatory, no localStorage

## Shared read-first list

1. `docs/plans/2026-04-11-terminal-unification-master-plan.md` — Appendix B §2.3 Screener
2. `docs/plans/2026-04-12-phase-3-overview.md` — this file
3. `docs/audits/Phase-3-Scope-Audit-Investigation-Report.md`
4. `backend/app/domains/wealth/routes/screener.py` — current catalog endpoint
5. `backend/app/domains/wealth/schemas/catalog.py` — current response schema
6. `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.svelte`
7. `frontends/wealth/src/lib/components/screener/terminal/` — all 4 shell components
8. `backend/app/domains/wealth/schemas/sanitized.py` — sanitize layer (Phase 2)
9. `CLAUDE.md` or `GEMINI.md` — Critical Rules, Data Ingestion Workers
