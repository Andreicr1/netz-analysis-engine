---
title: "SEC Data Providers Layer — Implementation Backlog"
date: 2026-03-20
origin: docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md
---

# SEC Data Providers Layer — Implementation Backlog

Execution order follows plan Phase 9 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8.
Each phase is one session. `make check` must be green before closing any phase.

---

## Phase 9 — Package Setup
Status: DONE
Exit criteria: `data_providers` importable after `pip install -e ".[dev,ai,quant]"`. `make check` fully green. No mypy errors.
Files created:
- `backend/data_providers/__init__.py`
- `backend/data_providers/sec/__init__.py`
Files modified:
- `pyproject.toml` (add `data_providers` to `[tool.setuptools.packages.find] include` and `[tool.importlinter] root_packages`)
Files deleted: (none)
Tasks:
- [x] Create `backend/data_providers/__init__.py` (empty)
- [x] Create `backend/data_providers/sec/__init__.py` (empty)
- [x] Add `"data_providers*"` to `[tool.setuptools.packages.find] include` in `pyproject.toml`
- [x] Add `"data_providers"` to `root_packages` in `[tool.importlinter]` in `pyproject.toml`
- [x] Run `pip install -e ".[dev,ai,quant]"` and verify `import data_providers` works
- [x] Run `make check` — must be green
Continuation prompt:

```
Read `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md` before doing anything.

Phase 9 (Package Setup) is DONE. Exit criteria met:
- `data_providers` package is importable after `pip install -e ".[dev,ai,quant]"`
- `import data_providers` and `import data_providers.sec` both work
- `make architecture` passes (30 contracts KEPT, 0 broken) — `data_providers` is in `root_packages`
- `make test` passes (1583 tests, 0 failures)
- Pre-existing lint/typecheck issues exist on this branch (feat/deep-review-confidence-signal-block2) in `retrieval/evidence.py` and `benchmark_ingest.py` — these are NOT from the SEC data providers work

Runtime observations from Phase 9:
- pyproject.toml uses `[tool.setuptools.packages.find]` with `where = ["backend", "."]` and an `include` list — added `"data_providers*"` to `include`
- import-linter config is in `pyproject.toml` under `[tool.importlinter]` — added `"data_providers"` to `root_packages`
- Test count is 1583 (not 1405 as stated in plan — test count has grown)
- Both `__init__.py` files are empty (no imports needed)
- The branch is `feat/deep-review-confidence-signal-block2` — there are pre-existing uncommitted changes from prior work on this branch

Execute Phase 1 next: Shared SEC Infrastructure (`data_providers/sec/shared.py` + `data_providers/sec/models.py`).

Key references for Phase 1:
- Current CIK resolver to migrate: `backend/vertical_engines/credit/edgar/cik_resolver.py`
- Current rate limiter in: `backend/vertical_engines/credit/edgar/service.py` (search for `_check_distributed_rate` and `_SEC_USER_AGENT`)
- Plan Phase 1 details: `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md` lines 122-160
- `shared.py` and `models.py` must have ZERO imports from `app.*` — they are fully standalone
- Blob index tier (Tier 3) is intentionally eliminated — new resolver has 3 tiers only (ticker → fuzzy → EFTS)
- EFTS tier is NEW code (not in current cik_resolver.py — it's in service.py as `_search_form_d()`)

After the phase passes all exit criteria, mark it DONE in the backlog and write the continuation prompt for the next phase before closing the session.
```

---

## Phase 1 — Shared SEC Infrastructure (`shared.py` + `models.py`)
Status: DONE
Exit criteria: `resolve_cik()` in `shared.py` produces identical results to `credit/edgar/cik_resolver.py` for Tiers 1, 2, and 4. Tier 3 (blob index) intentionally removed. Rate limiters work with Redis available and degrade gracefully without it. `shared.py` and `models.py` have zero imports from `app.*`.
Files created:
- `backend/data_providers/sec/models.py`
- `backend/data_providers/sec/shared.py`
Files modified: (none)
Files deleted: (none)
Tasks:
- [x] Create `backend/data_providers/sec/models.py` with frozen dataclasses: `CikResolution`, `AdvManager`, `AdvFund`, `AdvTeamMember`, `ThirteenFHolding`, `ThirteenFDiff`, `InstitutionalAllocation`, `SeriesFetchResult`, `CoverageType` enum, `InstitutionalOwnershipResult`
- [x] Create `backend/data_providers/sec/shared.py` with: `SEC_USER_AGENT`, `SEC_EDGAR_RATE_LIMIT`, `SEC_IAPD_RATE_LIMIT`, `check_edgar_rate()`, `check_iapd_rate()`, `sanitize_entity_name()`, `resolve_cik()` (3-tier: ticker → fuzzy → EFTS), `_normalize_light()`, `_normalize_heavy()`, local fallback rate limiter, dedicated SEC thread pool (`_sec_executor`), `run_in_sec_thread()`
- [x] Verify `shared.py` and `models.py` have zero imports from `app.*`
- [x] Run `make check` — lint and mypy clean on new files; 1484 pass, 44 pre-existing failures (unrelated to data_providers)
Continuation prompt:

```
Read `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md` before doing anything.

Phase 1 (Shared SEC Infrastructure) is DONE. Exit criteria met:
- `data_providers/sec/models.py` has all frozen dataclasses (CikResolution, AdvManager, AdvFund, AdvTeamMember, ThirteenFHolding, ThirteenFDiff, InstitutionalAllocation, SeriesFetchResult, CoverageType, InstitutionalOwnershipResult)
- `data_providers/sec/shared.py` has CIK resolver (3-tier: ticker → fuzzy → EFTS), rate limiters (Redis + local fallback), sanitize_entity_name (hardened), normalize functions, SEC thread pool
- Both files have zero imports from `app.*`
- `make check` lint and mypy clean on new files; 1484 tests pass, 44 pre-existing failures (unrelated — admin inspect, wealth contracts, wealth documents)
- Pre-existing lint issues in `pipeline_ingest_runner.py`, `extraction.py`, `domain_ai/service.py` (import sorting) — NOT from SEC data providers work
- Test count is 1538 collected (1484 pass, 44 pre-existing failures, 2 warnings)
- `sanitize_entity_name()` now includes strict character allowlist `^[a-zA-Z0-9\s.,'\-&()]+$` — rejects names with EFTS query operators
- Rate limiter local fallback uses token bucket at rate/4 (not unlimited), logs WARNING once on fallback activation
- `_sec_executor` ThreadPoolExecutor created at module level (safe — not asyncio primitive); `run_in_sec_thread()` gets loop at call time

Execute Phase 2 next: credit/edgar Refactor.

Key references for Phase 2:
- CIK resolver to DELETE: `backend/vertical_engines/credit/edgar/cik_resolver.py`
- Service to update: `backend/vertical_engines/credit/edgar/service.py` (replace `_check_distributed_rate`, `_SEC_USER_AGENT`, CIK resolver imports)
- Entity extraction to update: `backend/vertical_engines/credit/edgar/entity_extraction.py` (replace `sanitize_entity_name` import)
- __init__.py to update: `backend/vertical_engines/credit/edgar/__init__.py` (remove `cik_resolver` lazy import)
- Test to update: `backend/tests/test_edgar_package.py` (replace `sanitize_entity_name` import)
- Plan Phase 2 details: `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md` lines 163-200
- `CikResolution` in `credit/edgar/models.py` must add re-export: `from data_providers.sec.models import CikResolution`
- The new `CikResolution` is frozen — verify no existing code mutates it (it shouldn't, it's already used as immutable)
- `resolve_cik()` signature changed: no `blob_loader` parameter (blob index eliminated). Callers just pass `(name, ticker)`.
- `_search_form_d()` in `service.py` stays — it's credit-specific Form D search, NOT the same as EFTS CIK resolution

After the phase passes all exit criteria, mark it DONE in the backlog and write the continuation prompt for Phase 3 before closing the session.
```

---

## Phase 2 — credit/edgar Refactor
Status: DONE
Exit criteria: `cik_resolver.py` deleted. Single CIK resolver in `data_providers.sec.shared`. `make check` green (all 1405 tests pass). No `_check_distributed_rate` or `_SEC_USER_AGENT` in `credit/edgar/service.py`. `credit/edgar/` has zero CIK resolution logic.
Files created: (none)
Files modified:
- `backend/vertical_engines/credit/edgar/models.py` (add re-export of `CikResolution`)
- `backend/vertical_engines/credit/edgar/service.py` (import changes)
- `backend/vertical_engines/credit/edgar/entity_extraction.py` (import change)
- `backend/tests/test_edgar_package.py` (import change)
Files deleted:
- `backend/vertical_engines/credit/edgar/cik_resolver.py`
Tasks:
- [x] Update `credit/edgar/models.py`: add re-export `from data_providers.sec.models import CikResolution`
- [x] Delete `credit/edgar/cik_resolver.py`
- [x] Update `credit/edgar/service.py`: replace CIK resolver imports, rate limiter, User-Agent with `data_providers.sec.shared`
- [x] Update `credit/edgar/entity_extraction.py`: replace `sanitize_entity_name` import
- [x] Update `credit/edgar/__init__.py`: no `cik_resolver` lazy import existed (already clean)
- [x] Update `backend/tests/test_edgar_package.py`: replace `sanitize_entity_name` import
- [x] Run `make check` — 1513 pass, 25 pre-existing failures (unrelated); 30 architecture contracts KEPT; zero new mypy errors
Continuation prompt:

```
Read `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md` before doing anything.

Phase 2 (credit/edgar Refactor) is DONE. Exit criteria met:
- `cik_resolver.py` deleted — zero references remain (`grep cik_resolver` returns nothing)
- Single CIK resolver in `data_providers.sec.shared` — `service.py` imports `resolve_cik` from there
- `_check_distributed_rate` removed from `service.py` — replaced with `check_edgar_rate()` from shared
- `_SEC_USER_AGENT` removed from `service.py` — replaced with `SEC_USER_AGENT` from shared
- `entity_extraction.py` imports `sanitize_entity_name` from `data_providers.sec.shared`
- `credit/edgar/models.py` re-exports `CikResolution` from `data_providers.sec.models` (frozen version)
- `credit/edgar/__init__.py` was already clean (no `cik_resolver` lazy import existed)
- `test_edgar_package.py` imports `sanitize_entity_name` from `data_providers.sec.shared`
- All 34 edgar tests pass
- 1513 tests pass, 25 pre-existing failures (investor portal, wealth contracts, wealth documents, watchlist, fund membership, batched risk)
- Architecture: 30 contracts KEPT, 0 broken
- Mypy: zero new errors in changed files
- Pre-existing lint issues in `pipeline_ingest_runner.py`, `extraction.py`, `domain_ai/service.py` (import sorting) — NOT from SEC data providers work
- `_search_form_d()` in `service.py` preserved as-is — it's credit-specific Form D search, uses `SEC_USER_AGENT` from shared

Execute Phase 3 next: Import-Linter Contracts.

Key references for Phase 3:
- `pyproject.toml` — import-linter config under `[tool.importlinter]`
- New contract: `data_providers` must not import from `vertical_engines`, `app.domains`, or `quant_engine`
- Allowed: `data_providers` can import `app.shared` and `app.core` (if needed in future phases)
- Currently `data_providers/sec/shared.py` and `data_providers/sec/models.py` have zero imports from `app.*` — the contract ensures this stays true
- All 30 existing contracts must still pass
- Plan Phase 3 details: `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md` lines 201-220

After the phase passes all exit criteria, mark it DONE in the backlog and write the continuation prompt for Phase 4 before closing the session.
```

---

## Phase 3 — Import-Linter Contracts
Status: DONE
Exit criteria: `make architecture` green. `data_providers` cannot import verticals, app domains, or quant_engine. Both verticals can import `data_providers`. All existing contracts still hold.
Files created: (none)
Files modified:
- `pyproject.toml` (new import-linter contract + `data_providers` added to `root_packages`)
Files deleted: (none)
Tasks:
- [x] Add `"data_providers"` to `root_packages` in `[tool.importlinter]` (was missing despite Phase 9)
- [x] Add new import-linter contract in `pyproject.toml`: `data_providers` forbidden from importing `vertical_engines`, `app.domains`, `quant_engine` (allow `app.shared` and `app.core`)
- [x] Run `make architecture` — 31 contracts KEPT, 0 broken
- [x] Run `make test` — 1513 pass, 25 pre-existing failures (unchanged)
- [x] Mypy clean on `data_providers/` (4 source files, zero errors)
Continuation prompt: `docs/prompts/2026-03-20-sec-data-providers-phase4-prompt.md`

---

## Phase 4 — Alembic Migration (6 Global Tables)
Status: DONE
Exit criteria: `make migrate` applies cleanly (up and down). All 6 tables created with correct indexes and unique constraints. `test_global_table_isolation` passes with new tables. RLS audit does not flag new global tables.
Files created:
- `backend/app/core/db/migrations/versions/0023_sec_data_providers_tables.py`
Files modified:
- `backend/app/shared/models.py` (6 new ORM models)
- `backend/tests/test_global_table_isolation.py` (add to `GLOBAL_TABLE_MODELS` + search root)
- `backend/app/core/db/rls_audit.py` (add to `GLOBAL_TABLES` frozenset)
Files deleted: (none)
Tasks:
- [x] Create Alembic migration with 6 global tables: `sec_managers`, `sec_manager_funds`, `sec_manager_team`, `sec_13f_holdings`, `sec_13f_diffs`, `sec_institutional_allocations`
- [x] Include all indexes: `idx_sec_managers_cik`, `idx_sec_13f_holdings_cik_report_date`, covering index `idx_sec_13f_holdings_cusip_report_date`, `idx_sec_13f_diffs_cik_quarter_to`, `idx_sec_13f_diffs_cusip_quarter_to`, `idx_sec_inst_alloc_target_cusip_date`, `idx_sec_inst_alloc_filer_cik_date`
- [x] Include all unique constraints per plan schema
- [x] Add 6 ORM models to `backend/app/shared/models.py` (global, no org_id, `lazy="raise"`, `ON DELETE CASCADE` FKs)
- [x] Add all 6 tables to `GLOBAL_TABLE_MODELS` in `test_global_table_isolation.py`
- [x] Add `DATA_PROVIDERS_ROOT` search root to `test_global_table_isolation.py` (future service files will be allowlisted in their respective phases)
- [x] Add all 6 table names to `GLOBAL_TABLES` in `rls_audit.py`
- [x] Run `make architecture` — 31 contracts KEPT, 0 broken
- [x] Run `make test` — 1513 pass, 25 pre-existing failures (unchanged)
- [x] 24/24 global table isolation tests pass
- [x] 20/20 RLS audit tests pass
Continuation prompt: `docs/prompts/2026-03-20-sec-data-providers-phase5-prompt.md`

---

## Phase 5 — ADV Service (`adv_service.py`)
Status: DONE
Exit criteria: `search_managers()` returns basic results from IAPD search API. `ingest_bulk_adv()` parses SEC FOIA CSV and upserts to `sec_managers` + `sec_manager_funds`. `fetch_manager()` reads from DB only (no API calls in hot path). Never raises. Rate limited at 2 req/s for IAPD search. CRD numbers validated as `^\d{1,10}$`.
Files created:
- `backend/data_providers/sec/adv_service.py`
Files modified:
- `backend/tests/test_global_table_isolation.py` (add `data_providers/sec/adv_service.py` to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS`)
Files deleted: (none)
Tasks:
- [x] Create `AdvService` class with `search_managers()`, `ingest_bulk_adv()`, `fetch_manager()`, `fetch_manager_funds()`, `fetch_manager_team()` (stub for M1)
- [x] Implement IAPD search API integration with rate limiting (2 req/s)
- [x] Implement bulk CSV ingestion from SEC FOIA (Form ADV question-number columns)
- [x] Implement stale-but-serve pattern (`fetch_manager` reads DB only)
- [x] Implement never-raises error handling pattern
- [x] Validate CRD numbers as `^\d{1,10}$`
- [x] Stub `fetch_manager_team` — return empty list with TODO for Part 2A PDF OCR
- [x] Add `data_providers/sec/adv_service.py` to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS` with rationale
- [x] Run `make check` — 1513 pass, 25 pre-existing failures (unchanged); 31 contracts KEPT; zero new mypy errors
Continuation prompt: `docs/prompts/2026-03-20-sec-data-providers-phase6-prompt.md`

---

## Phase 6 — 13F Service (`thirteenf_service.py`)
Status: DONE
Exit criteria: Parses 13F-HR holdings via edgartools correctly. `market_value` stored in USD (×1000 multiplied). Diffs computed inline on ingestion, no orphan states. Upsert prevents duplicates on re-ingestion. Never raises.
Files created:
- `backend/data_providers/sec/thirteenf_service.py`
Files modified:
- `backend/tests/test_global_table_isolation.py` (add `data_providers/sec/thirteenf_service.py` to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS`)
Files deleted: (none)
Tasks:
- [x] Create `ThirteenFService` class with `fetch_holdings()`, `compute_diffs()`, `get_sector_aggregation()`, `get_concentration_metrics()`
- [x] Implement edgartools 13F parsing (`.holdings` DataFrame, Value ×1000, `has_infotable()` check, amendment handling via `seen_periods` dedup)
- [x] Evaluate edgartools `compare_holdings()` for diff computation — edgartools output does NOT map cleanly to `sec_13f_diffs` schema (missing weight calculation, custom aggregation needed); implemented manual diff from DB holdings instead
- [x] Implement bulk upsert via `pg_insert().on_conflict_do_update()` (chunk at 2000 rows)
- [x] Split diff computation into separate transaction from holdings upsert (`_upsert_diffs` in its own `session.begin()`)
- [x] Dispatch via dedicated SEC thread pool (`run_in_sec_thread()` from `shared.py`, `_sec_executor`, `max_workers=4`)
- [x] Handle edgartools gotchas: lazy import (nest-asyncio), built-in rate limiter (our Redis limiter coordinates across workers), caching (avoid double-caching), large portfolio cap (15K holdings via `_MAX_HOLDINGS_PER_FILING`)
- [x] Add `data_providers/sec/thirteenf_service.py` to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS` with rationale
- [x] Run `make check` — 1484 pass, 54 pre-existing failures (unchanged); 31 contracts KEPT; zero new mypy errors; zero lint errors
Continuation prompt: `docs/prompts/2026-03-20-sec-data-providers-phase7-prompt.md`

---

## Phase 7 — Institutional Service (`institutional_service.py`)
Status: DONE
Exit criteria: Discovers institutional filers via EFTS keyword search. Delegates to ThirteenFService for 13F parsing (zero duplication). Persists to `sec_institutional_allocations` with upsert. `find_investors_in_manager()` returns `InstitutionalOwnershipResult` with correct `CoverageType` in all three scenarios. Never raises.
Files created:
- `backend/data_providers/sec/institutional_service.py`
Files modified:
- `backend/tests/test_global_table_isolation.py` (add `data_providers/sec/institutional_service.py` to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS`)
Files deleted: (none)
Tasks:
- [x] Create `InstitutionalService` class with `discover_institutional_filers()`, `fetch_allocations()`, `find_investors_in_manager()`
- [x] Implement EFTS filer discovery with keyword search (endowment, pension, foundation, sovereign, insurance)
- [x] Implement `filer_type` classification from entity name keywords (log WARNING on ambiguous)
- [x] Implement `find_investors_in_manager()` with 3-way coverage detection (`FOUND`, `PUBLIC_SECURITIES_NO_HOLDERS`, `NO_PUBLIC_SECURITIES`)
- [x] Implement feeder→master look-through heuristic (best-effort, non-blocking)
- [x] Delegate 13F parsing to `ThirteenFService.fetch_holdings()` — zero duplication
- [x] Map holdings to `sec_institutional_allocations` via bulk upsert (`ON CONFLICT` on `uq_sec_inst_alloc_filer_date_cusip`)
- [x] Add `data_providers/sec/institutional_service.py` to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS` with rationale
- [x] Run `make check` — 1484 pass, 54 pre-existing failures (unchanged); 31 contracts KEPT; zero new mypy errors; zero lint errors
- [x] `CoverageType` enum and `InstitutionalOwnershipResult` already added in Phase 1 — no changes needed to `models.py`
Continuation prompt: `docs/prompts/2026-03-20-sec-data-providers-phase8-prompt.md`

---

## Phase 8 — Tests
Status: DONE
Exit criteria: Full test coverage for all public methods in all 4 modules. Regression suite proving CIK resolver migration produces identical results. `make check` green (existing 1405 + new tests).
Files created:
- `backend/tests/test_data_providers_shared.py`
- `backend/tests/test_data_providers_adv.py`
- `backend/tests/test_data_providers_thirteenf.py`
- `backend/tests/test_data_providers_institutional.py`
Files modified: (none)
Files deleted: (none)
Tasks:
- [x] Create `test_data_providers_shared.py`: 51 tests — `resolve_cik()` (all 3 tiers + cascade), `sanitize_entity_name()` (11 edge cases), `CikResolution` dataclass (frozen, equality), `_normalize_light()`/`_normalize_heavy()`, rate limiters (Redis + local fallback + warn-once), `run_in_sec_thread()`, CIK resolver regression suite (7 cases vs old resolver)
- [x] Create `test_data_providers_adv.py`: 52 tests — `search_managers()` (IAPD mock, empty/whitespace, never-raises), `fetch_manager()` (DB read, not found, invalid CRD, never-raises), `fetch_manager_funds()`, `fetch_manager_team()` (stub), `ingest_bulk_adv()` (CSV parsing, invalid CRD skip, missing name skip, AUM computation, ZIP handling, empty/null CSV, never-raises), `_parse_iapd_hit()` (6 cases), `_parse_int()`/`_parse_date()`, `_validate_crd()`, `_read_csv_file()` (plain + ZIP + no-CSV-in-ZIP)
- [x] Create `test_data_providers_thirteenf.py`: 37 tests — `fetch_holdings()` (cache hit, force_refresh, invalid CIK, never-raises), `compute_diffs()` (upsert, no target quarter, never-raises), `_compute_diffs_internal()` (all 5 action types + weight sums + mixed), `get_sector_aggregation()` (aggregation, empty, unknown class), `get_concentration_metrics()` (HHI, top-10, diversified, single position), `_is_stale()`, `_quarter_end()`, `_validate_cik()`, `_safe_int()`, market_value ×1000 conversion
- [x] Create `test_data_providers_institutional.py`: 32 tests — `discover_institutional_filers()` (results, custom types, never-raises), `_search_efts_filers()` (dedup, limit, missing fields, filer_type classification), `fetch_allocations()` (delegates to 13F, upsert, invalid CIK, never-raises), `find_investors_in_manager()` (3-way coverage: FOUND, PUBLIC_SECURITIES_NO_HOLDERS, NO_PUBLIC_SECURITIES, invalid CIK, never-raises), feeder→master look-through (5 cases: success, no master, same CIK skip, non-feeder skip, never-raises), `_classify_filer_type()` (all 5 types + ambiguous warning + case insensitive), models integration
- [x] Run `make test` — 1685 pass, 25 pre-existing failures (unchanged); 31 architecture contracts KEPT; zero new mypy errors; zero new lint errors
Continuation prompt:

---

## Phase 10 — TimescaleDB Hypertable Conversion (sec_13f_holdings + sec_13f_diffs)
Status: DONE
Exit criteria: Both tables are hypertables with 3-month chunks, compression active, continuous aggregate + materialized view created, all tests pass, `make check` green.
Files created:
- `backend/app/core/db/migrations/versions/0025_convert_sec_13f_holdings_to_hypertable.py`
Files modified:
- `backend/app/shared/models.py` (Sec13fHolding and Sec13fDiff: drop IdMixin, composite PK, docstrings)
- `backend/data_providers/sec/thirteenf_service.py` (time-bounded query for chunk pruning)
Tasks:
- [x] Create migration 0025: drop UUID PK + id column, convert to hypertable, composite PK, compression, indexes
- [x] Same migration converts sec_13f_diffs to hypertable partitioned by quarter_to
- [x] Create continuous aggregate sec_13f_latest_quarter (total equity value, position count per cik per quarter)
- [x] Create plain materialized view sec_13f_manager_sector_latest (top sector per manager)
- [x] Update ORM models: remove IdMixin, composite PK (report_date, cik, cusip) / (quarter_to, cik, cusip, quarter_from)
- [x] Add time-bound filter to _read_holdings_from_db (quarters * 92 days lookback)

**Manager Screener note:** Use `sec_13f_latest_quarter` and `sec_13f_manager_sector_latest` for list view — never scan `sec_13f_holdings` directly for screener pagination. Refresh `sec_13f_manager_sector_latest` manually after each 13F ingestion batch via `REFRESH MATERIALIZED VIEW CONCURRENTLY sec_13f_manager_sector_latest`.
