# Live Workbench — API Wiring Fix

## Problem

Three 404 errors in the browser console when the Live Workbench loads:

### Error 1: `GET /api/v1/market-data/quote/{ticker}` → 404
**Root cause:** The endpoint `/market-data/quote/{ticker}` does NOT exist.
The frontend `+page.svelte` (line ~254) calls this to get historical bars for the chart.

**The correct endpoint is:** `GET /api/v1/market-data/historical/{ticker}`

Located at `backend/app/domains/wealth/routes/market_data.py:781`:
```python
@router.get("/historical/{ticker}", response_model=HistoricalResponse)
async def market_historical(ticker, interval="daily", period="1M", ...):
```

**Fix:** In `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte`,
find ALL occurrences of `/market-data/quote/` and replace with `/market-data/historical/`.

There are likely 2-3 occurrences:
1. The main chart historical bars fetch (~line 254)
2. The compare ticker fetch (~line 318)
3. The watchlist ticker search validation (in Watchlist.svelte)

Search for "quote" in both `+page.svelte` and all files in
`frontends/wealth/src/lib/components/terminal/live/` to find every call.

Also check: the `HistoricalResponse` schema may return data in a different shape
than what the chart expects. Read the response model to verify the field names
(it may return `bars` as OHLCV objects, not `{ time, value }` pairs).

If the response shape differs, adapt the frontend mapping. The TerminalPriceChart
expects `BarData[]` which is `{ time: number, value: number }`. The historical
endpoint likely returns `{ date, close, open, high, low, volume }` — map `close`
to `value` and convert `date` string to Unix timestamp.

### Error 2: `GET /api/v1/allocation/growth/regime-bands` → 404
**Root cause:** The route exists (`allocation.py:389`) but returns 404 when no
`TaaRegimeState` row exists for profile "growth". The TAA system may only have
computed regime state for certain profiles.

**Fix options (choose one):**

**Option A (preferred):** In `portfolio-workspace.svelte.ts`, make the regime-bands
fetch failure graceful. It probably already has a `.catch()` but the error may
propagate to the UI. Verify the error is swallowed silently and the Builder/Live
pages render correctly with `regimeBands = null`.

**Option B:** Check what profile the test portfolio uses. If it's "growth", verify
the TAA regime state exists in the database. This is a data issue, not a code issue.

The Builder's RegimeContextStrip already handles `regimeBands = null` with an
"Regime data unavailable" empty state — so the fix is to ensure the workspace
doesn't throw on 404, just sets `regimeBands = null`.

Search `portfolio-workspace.svelte.ts` for "regime-bands" or "regimeBands" and
verify the `.catch()` handler sets state to null instead of letting the error propagate.

### Error 3: `__data.json` SvelteKit fetch failure
**Root cause:** Cascading from Error 1 or Error 2. When `handlePortfolioSelect`
navigates to `/portfolio/live?portfolio={id}`, SvelteKit re-runs the `+page.server.ts`
load function. If that load function catches errors properly, this should not happen.

**Fix:** In `+page.server.ts`, ensure ALL API calls inside the `load` function have
`.catch(() => null)` or `.catch(() => [])` fallbacks so the page always renders,
even when some data is unavailable.

## Branch

`fix/live-workbench-api-wiring` (already created from main)

## Read these files

1. `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte` — find all `/market-data/quote/` calls
2. `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.server.ts` — verify catch handlers
3. `frontends/wealth/src/lib/components/terminal/live/Watchlist.svelte` — may call `/quote/` for ticker search
4. `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` — search for "regime-bands" catch handler
5. `backend/app/domains/wealth/routes/market_data.py:781-830` — read HistoricalResponse schema + actual return shape

## Rules

- Svelte 5 runes. Zero hex. Terminal tokens. All formatters from @investintell/ui.
- Do NOT modify backend routes. These are frontend wiring fixes only.
- Do NOT create new endpoints. Use the existing `/market-data/historical/{ticker}`.

## Gate

1. No 404 errors in browser console when loading `/portfolio/live`
2. Chart loads historical bars for the selected instrument
3. Compare mode works (fetches second ticker's history)
4. Watchlist ticker search works (validates ticker existence)
5. Regime bands 404 is silently handled (no console error, empty state renders)
6. Portfolio selection navigation works without __data.json failure
7. `svelte-check` — zero errors
8. `pnpm build` — clean

## Commit

```
fix(live): correct API paths — /historical/ not /quote/, graceful regime-bands fallback

Frontend called nonexistent /market-data/quote/{ticker} — corrected to
/market-data/historical/{ticker}. Regime-bands 404 now silently falls back
to null state. Page server load catches all errors gracefully.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Push to origin/fix/live-workbench-api-wiring.
