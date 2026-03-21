Read `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md` before doing anything.

Phase 3 (Import-Linter Contracts) is DONE. Exit criteria met:
- `make architecture` green: 31 contracts KEPT, 0 broken (30 existing + 1 new)
- New contract: `data_providers` forbidden from importing `vertical_engines`, `app.domains`, `quant_engine`
- `app.shared` and `app.core` are NOT forbidden (needed for ORM models and DB sessions in future phases)
- Both verticals can import `data_providers` (no reverse contract blocks this)
- All 30 existing contracts still hold (no regressions)
- `data_providers` added to `root_packages` (was missing despite Phase 9 claiming it was done)
- 1513 tests pass, 25 pre-existing failures (investor portal, watchlist, wealth contracts, wealth documents)
- Mypy: zero errors in `data_providers/` (4 source files clean)
- Pre-existing lint issues in `pipeline_ingest_runner.py`, `extraction.py`, `domain_ai/service.py` (import sorting) — NOT from SEC data providers work
- Pre-existing mypy issues in `benchmark_ingest.py` — NOT from SEC data providers work

Execute Phase 4 next: Alembic Migration (6 Global Tables).

Key references for Phase 4:
- Plan Phase 4 details: `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md` (search for "Phase 4")
- Current migration head: check `backend/app/core/db/migrations/versions/` for latest
- 6 global tables: `sec_managers`, `sec_manager_funds`, `sec_manager_team`, `sec_13f_holdings`, `sec_13f_diffs`, `sec_institutional_allocations`
- All tables are GLOBAL (no `organization_id`, no RLS) — like `macro_data`, `benchmark_nav`
- ORM models go in `backend/app/shared/models.py` with `lazy="raise"` on all relationships
- Add to `GLOBAL_TABLE_MODELS` in `test_global_table_isolation.py`
- Add to `GLOBAL_TABLES` in `rls_audit.py`
- FKs use `ON DELETE CASCADE`
- Indexes and unique constraints per plan schema

After the phase passes all exit criteria, mark it DONE in the backlog and write the continuation prompt for Phase 5 as a standalone file at `docs/prompts/2026-03-20-sec-data-providers-phase5-prompt.md` before closing the session. Follow this pattern for all subsequent phases — each phase saves its successor's prompt to `docs/prompts/`.
