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
- [ ] Create `backend/data_providers/sec/models.py` with frozen dataclasses: `CikResolution`, `AdvManager`, `AdvFund`, `AdvTeamMember`, `ThirteenFHolding`, `ThirteenFDiff`, `InstitutionalAllocation`, `SeriesFetchResult`, `CoverageType` enum, `InstitutionalOwnershipResult`
- [ ] Create `backend/data_providers/sec/shared.py` with: `SEC_USER_AGENT`, `SEC_EDGAR_RATE_LIMIT`, `SEC_IAPD_RATE_LIMIT`, `check_edgar_rate()`, `check_iapd_rate()`, `sanitize_entity_name()`, `resolve_cik()` (3-tier: ticker → fuzzy → EFTS), `_normalize_light()`, `_normalize_heavy()`, local fallback rate limiter, dedicated SEC thread pool (`_sec_executor`), `run_in_sec_thread()`
- [ ] Verify `shared.py` and `models.py` have zero imports from `app.*`
- [ ] Run `make check`
Continuation prompt:

---

## Phase 2 — credit/edgar Refactor
Status: DONE
Exit criteria: `cik_resolver.py` deleted. Single CIK resolver in `data_providers.sec.shared`. `make check` green (all 1405 tests pass). No `_check_distributed_rate` or `_SEC_USER_AGENT` in `credit/edgar/service.py`. `credit/edgar/` has zero CIK resolution logic.
Files created: (none)
Files modified:
- `backend/vertical_engines/credit/edgar/models.py` (add re-export of `CikResolution`)
- `backend/vertical_engines/credit/edgar/service.py` (import changes)
- `backend/vertical_engines/credit/edgar/entity_extraction.py` (import change)
- `backend/vertical_engines/credit/edgar/__init__.py` (remove cik_resolver lazy import)
- `backend/tests/test_edgar_package.py` (import change)
Files deleted:
- `backend/vertical_engines/credit/edgar/cik_resolver.py`
Tasks:
- [ ] Update `credit/edgar/models.py`: add re-export `from data_providers.sec.models import CikResolution`
- [ ] Delete `credit/edgar/cik_resolver.py`
- [ ] Update `credit/edgar/service.py`: replace CIK resolver imports, rate limiter, User-Agent with `data_providers.sec.shared`
- [ ] Update `credit/edgar/entity_extraction.py`: replace `sanitize_entity_name` import
- [ ] Update `credit/edgar/__init__.py`: remove `cik_resolver` from lazy imports
- [ ] Update `backend/tests/test_edgar_package.py`: replace `sanitize_entity_name` import
- [ ] Run `make check` — all 1405 tests must pass
Continuation prompt:

---

## Phase 3 — Import-Linter Contracts
Status: DONE
Exit criteria: `make architecture` green. `data_providers` cannot import verticals, app domains, or quant_engine. Both verticals can import `data_providers`. All existing contracts still hold.
Files created: (none)
Files modified:
- `pyproject.toml` (new import-linter contract)
Files deleted: (none)
Tasks:
- [ ] Add new import-linter contract in `pyproject.toml`: `data_providers` forbidden from importing `vertical_engines`, `app.domains`, `quant_engine` (allow `app.shared` and `app.core`)
- [ ] Run `make architecture` — all contracts green
- [ ] Run `make check` — full gate green
Continuation prompt:

---

## Phase 4 — Alembic Migration (6 Global Tables)
Status: DONE
Exit criteria: `make migrate` applies cleanly (up and down). All 6 tables created with correct indexes and unique constraints. `test_global_table_isolation` passes with new tables. RLS audit does not flag new global tables.
Files created:
- `backend/app/core/db/migrations/versions/XXXX_sec_data_providers_tables.py`
Files modified:
- `backend/app/shared/models.py` (6 new ORM models)
- `backend/tests/test_global_table_isolation.py` (add to `GLOBAL_TABLE_MODELS` + allowlist)
- `backend/app/core/db/rls_audit.py` (add to `GLOBAL_TABLES` frozenset)
Files deleted: (none)
Tasks:
- [ ] Create Alembic migration with 6 global tables: `sec_managers`, `sec_manager_funds`, `sec_manager_team`, `sec_13f_holdings`, `sec_13f_diffs`, `sec_institutional_allocations`
- [ ] Include all indexes: `idx_sec_managers_cik`, `idx_sec_13f_holdings_cik_report_date`, covering index `idx_sec_13f_holdings_cusip_report_date`, `idx_sec_13f_diffs_cik_quarter_to`, `idx_sec_13f_diffs_cusip_quarter_to`, `idx_sec_inst_alloc_target_cusip_date`, `idx_sec_inst_alloc_filer_cik_date`
- [ ] Include all unique constraints per plan schema
- [ ] Add 6 ORM models to `backend/app/shared/models.py` (global, no org_id, `lazy="raise"`, `ON DELETE CASCADE` FKs)
- [ ] Add all 6 tables to `GLOBAL_TABLE_MODELS` in `test_global_table_isolation.py`
- [ ] Add allowlisted consumers to `test_global_table_isolation.py`
- [ ] Add all 6 table names to `GLOBAL_TABLES` in `rls_audit.py`
- [ ] Run `make migrate` — verify up and down
- [ ] Run `make check`
Continuation prompt:

---

## Phase 5 — ADV Service (`adv_service.py`)
Status: DONE
Exit criteria: `search_managers()` returns basic results from IAPD search API. `ingest_bulk_adv()` parses SEC FOIA CSV and upserts to `sec_managers` + `sec_manager_funds`. `fetch_manager()` reads from DB only (no API calls in hot path). Never raises. Rate limited at 2 req/s for IAPD search. CRD numbers validated as `^\d{1,10}$`.
Files created:
- `backend/data_providers/sec/adv_service.py`
Files modified: (none)
Files deleted: (none)
Tasks:
- [ ] Create `AdvService` class with `search_managers()`, `ingest_bulk_adv()`, `fetch_manager()`, `fetch_manager_funds()`, `fetch_manager_team()` (stub for M1)
- [ ] Implement IAPD search API integration with rate limiting (2 req/s)
- [ ] Implement bulk CSV ingestion from SEC FOIA (Form ADV question-number columns)
- [ ] Implement stale-but-serve pattern (`fetch_manager` reads DB only)
- [ ] Implement never-raises error handling pattern
- [ ] Validate CRD numbers as `^\d{1,10}$`
- [ ] Stub `fetch_manager_team` — return empty list with TODO for Part 2A PDF OCR
- [ ] Run `make check`
Continuation prompt:

---

## Phase 6 — 13F Service (`thirteenf_service.py`)
Status: DONE
Exit criteria: Parses 13F-HR holdings via edgartools correctly. `market_value` stored in USD (×1000 multiplied). Diffs computed inline on ingestion, no orphan states. Upsert prevents duplicates on re-ingestion. Never raises.
Files created:
- `backend/data_providers/sec/thirteenf_service.py`
Files modified: (none)
Files deleted: (none)
Tasks:
- [ ] Create `ThirteenFService` class with `fetch_holdings()`, `compute_diffs()`, `get_sector_aggregation()`, `get_concentration_metrics()`
- [ ] Implement edgartools 13F parsing (`.holdings` DataFrame, Value ×1000, `has_infotable()` check, amendment handling)
- [ ] Evaluate edgartools `compare_holdings()` for diff computation — use if output maps to `sec_13f_diffs` schema
- [ ] Implement bulk upsert via UNNEST (chunk at 2000 rows)
- [ ] Split diff computation into separate transaction from holdings upsert
- [ ] Dispatch via dedicated SEC thread pool (`_sec_executor`, `max_workers=4`)
- [ ] Handle edgartools gotchas: `nest-asyncio`, built-in rate limiter, caching, large portfolio cap (15K holdings)
- [ ] Run `make check`
Continuation prompt:

---

## Phase 7 — Institutional Service (`institutional_service.py`)
Status: DONE
Exit criteria: Discovers institutional filers via EFTS keyword search. Delegates to ThirteenFService for 13F parsing (zero duplication). Persists to `sec_institutional_allocations` with upsert. `find_investors_in_manager()` returns `InstitutionalOwnershipResult` with correct `CoverageType` in all three scenarios. Never raises.
Files created:
- `backend/data_providers/sec/institutional_service.py`
Files modified:
- `backend/data_providers/sec/models.py` (add `CoverageType` enum + `InstitutionalOwnershipResult` if not already added in Phase 1)
Files deleted: (none)
Tasks:
- [ ] Create `InstitutionalService` class with `discover_institutional_filers()`, `fetch_allocations()`, `find_investors_in_manager()`
- [ ] Implement EFTS filer discovery with keyword search (endowment, pension, foundation, sovereign, insurance)
- [ ] Implement `filer_type` classification from entity name keywords (log WARNING on ambiguous)
- [ ] Implement `find_investors_in_manager()` with 3-way coverage detection (`FOUND`, `PUBLIC_SECURITIES_NO_HOLDERS`, `NO_PUBLIC_SECURITIES`)
- [ ] Implement feeder→master look-through heuristic (best-effort, non-blocking)
- [ ] Delegate 13F parsing to `ThirteenFService.fetch_holdings()` — zero duplication
- [ ] Map holdings to `sec_institutional_allocations` via bulk upsert
- [ ] Run `make check`
Continuation prompt:

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
- [ ] Create `test_data_providers_shared.py`: test `resolve_cik()` (all 3 tiers), `sanitize_entity_name()`, rate limiters (Redis available + unavailable), `CikResolution` dataclass, regression suite vs old resolver
- [ ] Create `test_data_providers_adv.py`: test `fetch_manager()`, `search_managers()`, upsert semantics, `httpx.MockTransport` pattern
- [ ] Create `test_data_providers_thirteenf.py`: test `fetch_holdings()`, `compute_diffs()`, market_value ×1000, weight computation, staleness check
- [ ] Create `test_data_providers_institutional.py`: test `discover_institutional_filers()`, `fetch_allocations()`, `find_investors_in_manager()`, coverage type scenarios
- [ ] Run `make check` — all tests pass including existing 1405+
Continuation prompt:
