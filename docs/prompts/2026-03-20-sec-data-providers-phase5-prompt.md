Read `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md` before doing anything.

Phase 4 (Alembic Migration — 6 Global Tables) is DONE. Exit criteria met:
- Migration `0023_sec_data_providers_tables.py` created with all 6 global tables, all indexes, all unique constraints, and CHECK constraint on `sec_13f_diffs.action`
- 6 ORM models added to `backend/app/shared/models.py`: `SecManager`, `SecManagerFund`, `SecManagerTeam`, `Sec13fHolding`, `Sec13fDiff`, `SecInstitutionalAllocation`
- All models use `lazy="raise"` on relationships, `ON DELETE CASCADE` on FKs
- `SecManager` uses natural PK (`crd_number`), all others use `IdMixin` (UUID PK)
- `SecManager` has `funds` and `team` relationships (back_populates, lazy="raise", cascade="all, delete-orphan")
- `SecManagerFund` and `SecManagerTeam` have `manager` back-reference (lazy="raise")
- All 6 table names added to `GLOBAL_TABLES` in `rls_audit.py`
- All 6 model classes added to `GLOBAL_TABLE_MODELS` in `test_global_table_isolation.py`
- `DATA_PROVIDERS_ROOT` added as search root in `test_global_table_isolation.py` — future service files will be scanned automatically
- Allowlisted consumers NOT added yet (service files don't exist yet) — add them in Phase 5/6/7 when creating service files
- Architecture: 31 contracts KEPT, 0 broken
- Tests: 1513 pass, 25 pre-existing failures (investor portal, watchlist, wealth contracts, wealth documents, fund membership, batched risk)
- 24/24 global table isolation tests pass
- 20/20 RLS audit tests pass
- Pre-existing lint issues in `pipeline_ingest_runner.py`, `extraction.py`, `domain_ai/service.py` (import sorting) — NOT from SEC data providers work
- Pre-existing mypy issues: bare `dict` in `MacroRegionalSnapshot`/`MacroSnapshot`, `JSONB()` untyped call in migration files — all match pre-existing patterns

Execute Phase 5 next: ADV Service (`adv_service.py`).

Key references for Phase 5:
- Plan Phase 5 details: `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md` (search for "Phase 5")
- ORM models: `backend/app/shared/models.py` — `SecManager`, `SecManagerFund`, `SecManagerTeam`
- Shared infra: `backend/data_providers/sec/shared.py` — `check_iapd_rate()`, `SEC_USER_AGENT`, `run_in_sec_thread()`, `sanitize_entity_name()`
- Data models: `backend/data_providers/sec/models.py` — `AdvManager`, `AdvFund`, `AdvTeamMember`
- `AdvService` goes in `backend/data_providers/sec/adv_service.py`
- Service needs DB session for upserts — will import from `app.shared.models` (ORM) and `app.core` (session)
- Add `data_providers/sec/adv_service.py` to `ALLOWLISTED_GLOBAL_TABLE_CONSUMERS` in `test_global_table_isolation.py` with rationale
- IAPD search API rate limited at 2 req/s via `check_iapd_rate()`
- CRD numbers validated as `^\d{1,10}$`
- `fetch_manager()` reads DB only (stale-but-serve pattern, no API calls in hot path)
- `fetch_manager_team()` is a stub for M1 — return empty list with TODO for Part 2A PDF OCR
- Never-raises error handling: all public methods catch exceptions, log, return empty/None

After the phase passes all exit criteria, mark it DONE in the backlog and write the continuation prompt for Phase 6 as a standalone file at `docs/prompts/2026-03-20-sec-data-providers-phase6-prompt.md` before closing the session.
