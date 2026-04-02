---
title: "fix: Screener N-PORT series_id filtering + route consolidation"
type: fix
status: completed
date: 2026-04-02
---

# fix: Screener N-PORT series_id filtering + route consolidation

## Overview

Three related regressions in the screener pipeline:

1. **Holdings data mixing** — N-PORT holdings queried by CIK only, but one CIK (registrant) can contain multiple fund series. An equity fund (FDTTX) shows "Corporate Bonds" because its CIK shares filings with bond fund series in the same complex.
2. **Global search routes to empty legacy page** — Search sends users to `/screener/{id}` (legacy route using raw `/sec/funds/` endpoints), not `/screener/fund/{id}` (the fact-sheet route with aggregated data).
3. **Manager detail shows "No profile data"** — Data loading works but the page shows fallback title "Manager {crd}" when `sec_managers` lacks the CRD or `sec_adv_ingestion` hasn't run.

## Problem Statement

### Holdings Mixing (Critical)

SEC N-PORT filings are filed **per series**, not per CIK. Each filing's `<genInfo>` contains a `<seriesId>` identifying which fund series the holdings belong to. However:

- `_parse_nport_xml_holdings()` in `nport_service.py:63-116` never extracts `seriesId`
- `_upsert_holdings()` in `nport_service.py:309-350` never writes `series_id` to DB
- `SecNportHolding` ORM model (`models.py:497-526`) has no `series_id` field (column exists in DB via migration 0070)
- All downstream queries (`gather_sec_nport_data`, `gather_nport_sector_history`, holdings endpoints) filter by CIK only

**Result:** For umbrella funds (one CIK, multiple series), ALL series' holdings are mixed. Equity funds show bond sectors, bond funds show equity holdings.

### Route Duplication

Two fund detail routes exist:

| Route | Backend | Data Quality | Access |
|-------|---------|-------------|--------|
| `/screener/fund/[id]` | `GET /screener/catalog/{id}/fact-sheet` | Complete (aggregated) | Screener catalog click |
| `/screener/[cik]` | 7 parallel `/sec/funds/{cik}/*` calls | Partial/empty for many funds | **Global search** |

Global search (`search.py:241`) returns `href = f"/screener/{r.id}"` which matches the legacy `[cik]` route. Users searching for a fund land on an empty page instead of the rich fact-sheet.

### Manager Detail Data

Backend endpoints at `/manager-screener/managers/{crd}/*` are all fully implemented (13 endpoints in `manager_screener.py`). The frontend `ManagerDetailPanel.svelte` correctly fetches data client-side. The issue is:
- `sec_managers` may not have the CRD being queried (data coverage gap from `sec_adv_ingestion`)
- Page title falls back to "Manager {crd}" when SSR profile fetch fails silently
- Not a code bug — it's a data availability / graceful degradation issue

## Proposed Solution

### Phase 1: N-PORT series_id pipeline (Backend)

**1.1 Extract seriesId from N-PORT XML**

In `nport_service.py:_parse_nport_filings()` (lines 196-254), each filing's XML already has `<seriesId>` in `<genInfo>` (same section as `<repPd>` already parsed at line 234). Extract it and pass to `_parse_nport_xml_holdings()`:

```python
# nport_service.py — inside _parse_nport_filings() loop (line 230)
# After extracting report_date_str, before calling _parse_nport_xml_holdings:
series_id = None
for elem in root.iter():
    if elem.tag.endswith("seriesId") and elem.text:
        series_id = elem.text.strip()
        break

holdings = _parse_nport_xml_holdings(root, cik, report_date_str, series_id=series_id)
```

**1.2 Update `_parse_nport_xml_holdings` signature**

Add `series_id: str | None = None` parameter. Set it on each `NportHolding`:

```python
# nport_service.py:63
def _parse_nport_xml_holdings(
    root: Element,
    cik: str,
    report_date: str,
    series_id: str | None = None,  # NEW
) -> list[NportHolding]:
```

**1.3 Add series_id to NportHolding dataclass**

```python
# data_providers/sec/models.py — NportHolding dataclass
series_id: str | None  # NEW field
```

**1.4 Add series_id to SecNportHolding ORM model**

```python
# app/shared/models.py — SecNportHolding class
series_id: Mapped[str | None] = mapped_column(Text)
```

Column already exists in DB (migration 0070). No new migration needed for the column — only the ORM mapping.

**1.5 Update upsert to write series_id**

```python
# nport_service.py:_upsert_holdings() — add to dict and on_conflict_do_update set_
"series_id": h.series_id,
```

**1.6 Update all query points to filter by series_id**

Six locations need `AND series_id = :series_id` when series_id is known:

| # | File | Function | Line |
|---|------|----------|------|
| 1 | `sec_injection.py` | `gather_sec_nport_data()` | 160 |
| 2 | `sec_injection.py` | `gather_nport_sector_history()` | 338 |
| 3 | `screener.py` | `get_fund_fact_sheet()` — pass series_id | 1907 |
| 4 | `sec_funds.py` | `GET /sec/funds/{cik}/holdings` | 330 |
| 5 | `sec_funds.py` | `GET /sec/funds/{cik}/holdings-history` | 456 |
| 6 | `holdings_exploder.py` | `fetch_portfolio_holdings_exploded()` | 130 |

**Pattern for backward compatibility:** When `series_id` is known, add `AND series_id = :series_id`. When NULL (old data not yet backfilled), fall back to CIK-only query.

```python
# sec_injection.py — gather_sec_nport_data()
def gather_sec_nport_data(
    db: Session,
    *,
    fund_cik: str | None,
    series_id: str | None = None,  # NEW
    holdings_limit: int = 10,
) -> dict[str, Any]:
    ...
    filters = [SecNportHolding.cik == fund_cik, SecNportHolding.report_date >= lookback]
    if series_id:
        filters.append(SecNportHolding.series_id == series_id)
    ...
```

**1.7 Pass series_id through fact-sheet route**

`screener.py:1912` already resolves `correct_series_id`. Pass it to `gather_sec_nport_data` and `gather_nport_sector_history`:

```python
# screener.py line 1907-1908
nport_data = gather_sec_nport_data(sync_db, fund_cik=fund_cik, series_id=correct_series_id, holdings_limit=50)
sector_history = gather_nport_sector_history(sync_db, fund_cik=fund_cik, series_id=correct_series_id)
```

**1.8 Backfill script**

Create `backend/scripts/backfill_nport_series_id.py` — reads N-PORT XML from EDGAR for all CIKs in `sec_registered_funds`, extracts `seriesId`, updates `sec_nport_holdings.series_id` for matching `(report_date, cik)` records.

Alternatively (simpler): since `sec_registered_funds` stores `series_id`, and each CIK with only ONE series can be backfilled directly:

```sql
UPDATE sec_nport_holdings h
SET series_id = rf.series_id
FROM sec_registered_funds rf
WHERE h.cik = rf.cik
  AND rf.series_id IS NOT NULL
  AND h.series_id IS NULL;
```

For umbrella CIKs with multiple series, the worker must re-fetch filings to tag correctly. This can be deferred — the query fallback (CIK-only when series_id is NULL) handles the transition.

### Phase 2: Route consolidation (Frontend + Backend)

**2.1 Fix global search href**

```python
# search.py:241 — change:
href = f"/screener/{r.id}"
# to:
href = f"/screener/fund/{r.id}"
```

**2.2 Redirect legacy route**

In `frontends/wealth/src/routes/(app)/screener/[cik]/+page.server.ts`, replace the page load with a redirect:

```typescript
import { redirect } from '@sveltejs/kit';

export const load = async ({ params }) => {
    throw redirect(301, `/screener/fund/${params.cik}`);
};
```

This preserves any bookmarked URLs while funneling all traffic to the fact-sheet route.

**2.3 Remove legacy page component**

Delete `frontends/wealth/src/routes/(app)/screener/[cik]/+page.svelte` — the redirect makes it unreachable.

### Phase 3: Manager detail graceful degradation (Frontend)

**3.1 Improve SSR title resolution**

The page title shows "Manager 105247" when the profile API fails. Add a fallback to `sec_managers` firm_name directly if the profile endpoint fails:

```typescript
// managers/[crd]/+page.server.ts — enhance try/catch
let firmName = `Manager ${crd}`;
try {
    const profile = await api.get<{ firm_name: string }>(`/manager-screener/managers/${crd}/profile`);
    if (profile?.firm_name) firmName = profile.firm_name;
} catch {
    // Profile endpoint failed — ManagerDetailPanel will show appropriate empty states per tab
}
```

This is already correct. The real issue is `sec_managers` not having the CRD. The fix is to ensure `sec_adv_ingestion` worker has run and populated the data.

**3.2 Show informative empty states**

In `ManagerDetailPanel.svelte`, the profile tab should show "Manager not found in SEC filings" rather than generic "No profile data." — allows user to understand it's a data coverage issue, not a bug.

## Acceptance Criteria

### Phase 1 — N-PORT series_id

- [x] `NportHolding` dataclass has `series_id` field — `data_providers/sec/models.py`
- [x] `SecNportHolding` ORM model has `series_id` mapped — `app/shared/models.py`
- [x] `_parse_nport_xml_holdings()` accepts and sets `series_id` — `nport_service.py`
- [x] `_parse_nport_filings()` extracts `seriesId` from XML `<genInfo>` — `nport_service.py`
- [x] `_upsert_holdings()` writes `series_id` — `nport_service.py`
- [x] `gather_sec_nport_data()` accepts and filters by `series_id` — `sec_injection.py`
- [x] `gather_nport_sector_history()` accepts and filters by `series_id` — `sec_injection.py`
- [x] Fact-sheet route passes `correct_series_id` to both gather functions — `screener.py`
- [x] Holdings endpoints accept optional `series_id` query param — `sec_funds.py`
- [x] `holdings_exploder` resolves series_id from instruments — `holdings_exploder.py`
- [x] Backfill SQL for single-series CIKs runs without error
- [ ] FDTTX fact-sheet shows equity holdings, not "Corporate Bonds" (requires backfill + re-ingestion)
- [x] `make check` passes (lint + typecheck + tests)

### Phase 2 — Route consolidation

- [x] Global search `href` points to `/screener/fund/{id}` — `search.py`
- [x] `/screener/[cik]` redirects 301 to `/screener/fund/[cik]` — `+page.server.ts`
- [x] Legacy `+page.svelte` removed from `[cik]/` directory
- [x] Search → click fund → lands on fact-sheet page (not legacy empty page)

### Phase 3 — Manager detail

- [x] Profile tab shows "Manager not found in SEC filings" when profile is null
- [x] Tabs that have no data show specific empty state (not generic "No data")

## Files to Modify

### Phase 1

| File | Change |
|------|--------|
| `backend/data_providers/sec/models.py` | Add `series_id` to `NportHolding` dataclass |
| `backend/app/shared/models.py` | Add `series_id` to `SecNportHolding` ORM |
| `backend/data_providers/sec/nport_service.py` | Extract seriesId from XML, pass to parser, write in upsert |
| `backend/vertical_engines/wealth/dd_report/sec_injection.py` | Add `series_id` param to `gather_sec_nport_data` and `gather_nport_sector_history` |
| `backend/app/domains/wealth/routes/screener.py` | Pass `correct_series_id` to gather functions |
| `backend/app/domains/wealth/routes/sec_funds.py` | Add optional `series_id` query param to holdings endpoints |
| `backend/app/domains/wealth/services/holdings_exploder.py` | Resolve and filter by series_id |
| `backend/scripts/backfill_nport_series_id.py` | NEW — backfill script |

### Phase 2

| File | Change |
|------|--------|
| `backend/app/domains/wealth/routes/search.py` | Change href to `/screener/fund/{id}` |
| `frontends/wealth/src/routes/(app)/screener/[cik]/+page.server.ts` | Replace with redirect |
| `frontends/wealth/src/routes/(app)/screener/[cik]/+page.svelte` | DELETE |

### Phase 3

| File | Change |
|------|--------|
| `frontends/wealth/src/lib/components/screener/ManagerDetailPanel.svelte` | Better empty states |

## Implementation Order

1. **Phase 2 first** (15 min) — immediate UX improvement, zero risk, fixes empty pages from search
2. **Phase 1** (1-2 hours) — series_id pipeline fix, the core data bug
3. **Phase 3** (15 min) — cosmetic empty state improvements

Phase 2 is decoupled from Phase 1 and can ship independently. Phase 1 is the critical data fix. Phase 3 is polish.

## Risk Analysis

| Risk | Mitigation |
|------|------------|
| Backfill for umbrella CIKs requires re-fetching from EDGAR | Graceful fallback: queries work without series_id (CIK-only), umbrella backfill is deferred |
| `seriesId` may not exist in all N-PORT XMLs | Fallback to NULL — existing CIK-only behavior preserved |
| Redirect breaks deep links to legacy page tabs | 301 redirect preserves the path; fact-sheet page has equivalent sections |
| holdings_exploder needs series_id from Instrument.attributes | Resolve via `sec_fund_classes` join on `sec_cik` — same pattern as fact-sheet |

## Sources & References

- `backend/data_providers/sec/nport_service.py` — N-PORT XML parsing (lines 63-254)
- `backend/vertical_engines/wealth/dd_report/sec_injection.py` — holdings/sector gather (lines 129-383)
- `backend/app/domains/wealth/routes/screener.py` — fact-sheet endpoint (lines 1826-2025)
- `backend/app/domains/wealth/routes/search.py` — global search href (line 241)
- `backend/app/core/db/migrations/versions/0070_global_instruments_sync.py` — series_id column already exists (line 108)
- `backend/app/core/db/migrations/versions/0078_consolidated_screener_views.py` — mv_unified_funds external_id resolution
- `docs/reference/fund-centric-model-reference.md` — CIK → Series → Class hierarchy
