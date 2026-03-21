Read `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md` before doing anything.

Phase 7 (Institutional Service) is DONE. Exit criteria met:
- `InstitutionalService` class created in `backend/data_providers/sec/institutional_service.py` with all 3 public methods
- `discover_institutional_filers()` searches EFTS for 13F filers by keyword (endowment, pension, foundation, sovereign, insurance), dispatched via `run_in_sec_thread()`
- `filer_type` classification from entity name keywords via regex patterns, logs WARNING on ambiguous (multiple types match)
- `fetch_allocations()` delegates to `ThirteenFService.fetch_holdings()` — zero duplication of edgartools logic
- Holdings mapped to `InstitutionalAllocation` with filer context (cik, name, type) attached
- Bulk upsert via `pg_insert().on_conflict_do_update()` on constraint `uq_sec_inst_alloc_filer_date_cusip` (filer_cik, report_date, target_cusip)
- Upsert chunks at 2000 rows (`_CHUNK_SIZE`)
- `find_investors_in_manager()` with 3-way coverage detection:
  - `NO_PUBLIC_SECURITIES`: manager has no 13F holdings in DB (no CUSIPs associated)
  - `PUBLIC_SECURITIES_NO_HOLDERS`: manager has CUSIPs but no institutional filers hold them
  - `FOUND`: institutional holders found, returned as `InstitutionalAllocation` list
- Feeder→master look-through heuristic: when manager has no CUSIPs, checks if company name contains feeder keywords (offshore, Cayman, Ltd), strips them to derive base name, resolves CIK via `resolve_cik()`, queries master's CUSIPs — best-effort, non-blocking, never raises
- Company name lookup via edgartools `Company(cik)` in SEC thread pool
- CIK validated as `^\d{1,10}$` on all public methods
- Never-raises pattern: all public methods catch exceptions, log, return empty/safe defaults
- Service receives `thirteenf_service` (ThirteenFService instance) and `db_session_factory` (callable) in `__init__`
- `CoverageType` enum and `InstitutionalOwnershipResult` already existed in `data_providers/sec/models.py` from Phase 1 — no changes needed
- `data_providers/sec/institutional_service.py` added to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS` in `test_global_table_isolation.py` with rationale
- Architecture: 31 contracts KEPT, 0 broken
- Tests: 1484 pass, 54 pre-existing failures (admin inspect, investor portal, watchlist, wealth contracts, wealth documents, fund membership, batched risk)
- Lint: zero errors in new file
- Mypy: zero new errors (pre-existing bare `dict` in `MacroRegionalSnapshot`/`MacroSnapshot` unchanged)

Execute Phase 8 next: Tests.

Key references for Phase 8:
- Plan Phase 8 details: `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md` (search for "Phase 8")
- Shared infra to test: `backend/data_providers/sec/shared.py` — `resolve_cik()` (3-tier), `sanitize_entity_name()`, rate limiters, `run_in_sec_thread()`
- ADV service to test: `backend/data_providers/sec/adv_service.py` — `search_managers()`, `ingest_bulk_adv()`, `fetch_manager()`, `fetch_manager_funds()`
- 13F service to test: `backend/data_providers/sec/thirteenf_service.py` — `fetch_holdings()`, `compute_diffs()`, `get_sector_aggregation()`, `get_concentration_metrics()`
- Institutional service to test: `backend/data_providers/sec/institutional_service.py` — `discover_institutional_filers()`, `fetch_allocations()`, `find_investors_in_manager()`
- Data models: `backend/data_providers/sec/models.py` — all frozen dataclasses
- ORM models: `backend/app/shared/models.py` — `SecManager`, `SecManagerFund`, `SecManagerTeam`, `Sec13fHolding`, `Sec13fDiff`, `SecInstitutionalAllocation`
- Test patterns in codebase: `backend/tests/test_edgar_package.py` (mock patterns for edgartools)
- All services use `db_session_factory` (callable) — mock with `AsyncMock` returning async context manager
- All services use `run_in_sec_thread()` — can be tested by mocking the sync functions directly
- `httpx.MockTransport` pattern for IAPD and EFTS HTTP mocking (no real network calls in tests)
- Test file naming: `backend/tests/test_data_providers_shared.py`, `test_data_providers_adv.py`, `test_data_providers_thirteenf.py`, `test_data_providers_institutional.py`
- CIK resolver regression suite: compare `resolve_cik()` output against known test cases from the old `cik_resolver.py` (Tier 1 ticker, Tier 2 fuzzy, not_found)

After the phase passes all exit criteria, mark it DONE in the backlog before closing the session.
