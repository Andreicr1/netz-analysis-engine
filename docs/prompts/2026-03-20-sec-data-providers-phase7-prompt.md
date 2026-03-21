Read `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md` before doing anything.

Phase 6 (13F Service) is DONE. Exit criteria met:
- `ThirteenFService` class created in `backend/data_providers/sec/thirteenf_service.py` with all 4 public methods
- `fetch_holdings()` parses 13F-HR filings via edgartools `Company(cik).get_filings(form="13F-HR")`, dispatched via `run_in_sec_thread()`
- `has_infotable()` check before accessing `.holdings` — 13F-NT filings safely skipped
- `Value` column multiplied ×1000 for USD storage (`market_value = int(float(raw_value) * 1_000)`)
- Amendment handling via `seen_periods` set — first filing per `report_period` wins, duplicates skipped
- Holdings capped at 15K per filing (`_MAX_HOLDINGS_PER_FILING`) to prevent memory issues with large portfolios (Vanguard 24K+)
- edgartools lazy-imported inside `_parse_13f_filings()` (nest-asyncio isolation)
- Staleness check: compares most recent `report_date` against `staleness_ttl_days` (default 45 days)
- DB cache: `_read_holdings_from_db()` returns cached holdings if not stale, avoiding unnecessary EDGAR calls
- Bulk upsert via `pg_insert().on_conflict_do_update()` on `(cik, report_date, cusip)` with `WHERE data_fetched_at < excluded.data_fetched_at` guard
- Upsert chunks at 2000 rows (`_CHUNK_SIZE`)
- `compute_diffs()` reads holdings from DB for both quarters, computes manual diffs (edgartools `compare_holdings()` does NOT map to `sec_13f_diffs` schema — missing weight calculation)
- Diff actions: NEW_POSITION, INCREASED, DECREASED, EXITED, UNCHANGED
- Weight calculation: `value / total_portfolio_value` per quarter
- Diff upsert in SEPARATE transaction from holdings upsert (`_upsert_diffs` has own `session.begin()`)
- Diff conflict on `(cik, cusip, quarter_from, quarter_to)` — full column update on conflict
- `get_sector_aggregation()` returns `{asset_class: weight}` sorted by value descending
- `get_concentration_metrics()` returns `{hhi, top_10_concentration, position_count}`
- Never-raises pattern: all public methods catch exceptions, log, return empty
- CIK validated as `^\d{1,10}$` on all public methods
- `data_providers/sec/thirteenf_service.py` added to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS` in `test_global_table_isolation.py` with rationale
- Service receives `db_session_factory` (callable) in `__init__` — same pattern as `AdvService`
- Architecture: 31 contracts KEPT, 0 broken
- Tests: 1484 pass, 54 pre-existing failures (admin inspect, investor portal, watchlist, wealth contracts, wealth documents, fund membership, batched risk)
- Lint: zero errors in new file
- Mypy: zero new errors (pre-existing bare `dict` in `MacroRegionalSnapshot`/`MacroSnapshot` unchanged)

Execute Phase 7 next: Institutional Service (`institutional_service.py`).

Key references for Phase 7:
- Plan Phase 7 details: `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md` (search for "Phase 7")
- ORM models: `backend/app/shared/models.py` — `SecInstitutionalAllocation`
- Shared infra: `backend/data_providers/sec/shared.py` — `check_edgar_rate()`, `SEC_USER_AGENT`, `run_in_sec_thread()`
- Data models: `backend/data_providers/sec/models.py` — `InstitutionalAllocation`, `CoverageType`, `InstitutionalOwnershipResult`
- 13F service to delegate to: `backend/data_providers/sec/thirteenf_service.py` — `ThirteenFService.fetch_holdings()` for parsing 13F holdings (zero duplication)
- `InstitutionalService` goes in `backend/data_providers/sec/institutional_service.py`
- Service needs DB session for upserts — will import from `app.shared.models` (ORM)
- Add `data_providers/sec/institutional_service.py` to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS` in `test_global_table_isolation.py` with rationale
- EFTS filer discovery: keyword search for "endowment", "pension", "foundation", "sovereign", "insurance"
- `filer_type` classification from entity name keywords (log WARNING on ambiguous)
- `find_investors_in_manager()` with 3-way coverage detection: FOUND, PUBLIC_SECURITIES_NO_HOLDERS, NO_PUBLIC_SECURITIES
- Feeder→master look-through heuristic (best-effort, non-blocking)
- Bulk upsert via `pg_insert().on_conflict_do_update()` (same pattern as `thirteenf_service.py`)
- Dispatch via `run_in_sec_thread()` (dedicated SEC thread pool, `max_workers=4`)
- Never-raises pattern on all public methods

After the phase passes all exit criteria, mark it DONE in the backlog and write the continuation prompt for Phase 8 as a standalone file at `docs/prompts/2026-03-20-sec-data-providers-phase8-prompt.md` before closing the session.
