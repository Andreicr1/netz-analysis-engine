Read `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md` before doing anything.

Phase 5 (ADV Service) is DONE. Exit criteria met:
- `AdvService` class created in `backend/data_providers/sec/adv_service.py` with all 5 public methods
- `search_managers()` calls IAPD search API via `run_in_sec_thread()`, rate limited at 2 req/s via `check_iapd_rate()`
- `ingest_bulk_adv()` parses SEC FOIA bulk CSV (ZIP or raw), upserts to `sec_managers` via `pg_insert().on_conflict_do_update()` in chunks of 2000
- CSV parsing handles Form ADV question-number columns: `Q5F2A` (discretionary AUM), `Q5F2B` (non-discretionary AUM), `Q5F2C` (total AUM), `Q5F2(f)` (total accounts), `Q11` (compliance disclosures)
- `fetch_manager()` reads from DB only (stale-but-serve pattern, no API calls). Returns frozen `AdvManager` dataclass
- `fetch_manager_funds()` reads `SecManagerFund` from DB, returns `list[AdvFund]`
- `fetch_manager_team()` is a stub — returns empty list with TODO for Part 2A PDF OCR (M2 scope)
- CRD numbers validated as `^\d{1,10}$` on all public methods
- Never-raises pattern: all public methods catch exceptions, log, return empty/None
- `data_providers/sec/adv_service.py` added to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS` in `test_global_table_isolation.py` with rationale
- Service receives `db_session_factory` (callable) in `__init__` — instantiate once in FastAPI lifespan
- IAPD search returns basic identification only (CRD, name, address, scope) — no AUM, fees, or fund data
- Bulk CSV download auto-discovers latest ZIP from SEC FOIA page via HTML link parsing
- Architecture: 31 contracts KEPT, 0 broken
- Tests: 1513 pass, 25 pre-existing failures (investor portal, watchlist, wealth contracts, wealth documents, fund membership, batched risk)
- Lint: zero errors in new file
- Mypy: zero new errors (pre-existing bare `dict` in `MacroRegionalSnapshot`/`MacroSnapshot` unchanged)

Execute Phase 6 next: 13F Service (`thirteenf_service.py`).

Key references for Phase 6:
- Plan Phase 6 details: `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md` (search for "Phase 6")
- ORM models: `backend/app/shared/models.py` — `Sec13fHolding`, `Sec13fDiff`
- Shared infra: `backend/data_providers/sec/shared.py` — `check_edgar_rate()`, `SEC_USER_AGENT`, `run_in_sec_thread()`
- Data models: `backend/data_providers/sec/models.py` — `ThirteenFHolding`, `ThirteenFDiff`
- `ThirteenFService` goes in `backend/data_providers/sec/thirteenf_service.py`
- Service needs DB session for upserts — will import from `app.shared.models` (ORM)
- Add `data_providers/sec/thirteenf_service.py` to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS` in `test_global_table_isolation.py` with rationale
- edgartools for 13F parsing: `Company(cik).get_filings(form="13F-HR")`, `.holdings` DataFrame, `Value` column is in thousands (multiply ×1000)
- `has_infotable()` check before accessing holdings — some filings have no info table
- edgartools `compare_holdings()` may be usable for diff computation — evaluate if output maps to `sec_13f_diffs` schema
- Bulk upsert via `pg_insert().on_conflict_do_update()` (same pattern as `adv_service.py`), chunk at 2000 rows
- Diff computation in separate transaction from holdings upsert
- Dispatch via `run_in_sec_thread()` (dedicated SEC thread pool, `max_workers=4`)
- edgartools gotchas: uses `nest-asyncio`, has built-in rate limiter, caching, large portfolio cap (15K holdings)
- Never-raises pattern on all public methods

After the phase passes all exit criteria, mark it DONE in the backlog and write the continuation prompt for Phase 7 as a standalone file at `docs/prompts/2026-03-20-sec-data-providers-phase7-prompt.md` before closing the session.
