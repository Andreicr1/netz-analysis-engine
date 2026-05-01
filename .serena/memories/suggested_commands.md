# Suggested Commands

Environment setup on Windows:
- `.\dev.ps1` - setup helper. Activates `.venv`, loads `.env.dev`, and moves into `backend/`.
- `.\dev.ps1 -Install` - reinstall Python deps as editable package with `[dev,ai,quant,edgar]`.
- `.\dev.ps1 -Reset` - recreate the venv.

Backend development:
- `make serve` - run FastAPI dev server on `127.0.0.1:8000`.
- `make test` - run backend pytest suite under `backend/tests`.
- `make test ARGS="-k pattern"` - run a targeted backend test subset.
- `make lint` - Ruff check on backend.
- `make typecheck` - mypy on `backend/app/`.
- `make architecture` - import-linter contracts.
- `make coverage-runtime` - runtime guardrails coverage gate.
- `make check` - full gate: lint, architecture, typecheck, token sync, test.

Database/local services:
- `make up` - start local PostgreSQL 16 + TimescaleDB + pgvector and Redis via docker-compose.
- `make down` - stop local docker-compose stack.
- `make migrate` - Alembic upgrade head.
- `make migration MSG="description"` - generate Alembic revision.
- Local DB defaults: PostgreSQL on `localhost:5434`, DB `netz_engine`, user `netz`, password `password`; Redis on `localhost:6379`.

Workers:
- Generic CLI: `cd backend && python -m app.workers.cli <worker_name>`.
- Registered worker names include `universe_sync`, `universe_auto_import`, `tiingo_enrichment`, `macro_ingestion`, `benchmark_ingest`, `treasury_ingestion`, `ofr_ingestion`, `bis_ingestion`, `imf_ingestion`, `nport_ingestion`, `nport_fund_discovery`, `esma_aum_sync`, `esma_ingestion`, `sec_refresh`, `sec_13f_ingestion`, `sec_adv_ingestion`, `brochure_download`, `brochure_extract`, `wealth_embedding`, `regime_fit`, `fast_track_eviction`, `instrument_ingestion`, `drift_check`, `risk_calc`, `portfolio_eval`, `portfolio_nav_synthesizer`, `screening_batch`, `watchlist_batch`, `alert_sweeper`.
- SEC seed shortcuts: `python -m data_providers.sec.seed.populate_seed --recent-only`, `--only-ticker-map`, or `--resume`.

Frontend/monorepo:
- `pnpm install` - install JS deps if needed.
- `pnpm run dev` or `make dev-all` - run Turborepo dev tasks.
- `make dev-credit`, `make dev-wealth`, `make dev-terminal` - run individual SvelteKit apps.
- `make build-all` - topological build of frontend packages/apps.
- `make check-all` - frontend lint + check via Turbo.
- `make lint-frontend` - ESLint all frontend packages.
- `make check-terminal`, `make lint-terminal`, `make build-terminal` - terminal-specific gates.
- `make types` - generate TS API types from running backend OpenAPI schema.
- `pnpm test:e2e`, `pnpm test:e2e:credit`, `pnpm test:e2e:wealth`, `pnpm test:e2e:ui` - Playwright scripts.

Windows utility commands:
- `Get-ChildItem -Force` - list files including hidden.
- `rg "pattern" path` and `rg --files` - preferred search/file listing.
- `Get-Content path -TotalCount N` - read first N lines.
- `Get-Content path | Select-Object -Skip S -First N` - read a slice.
- `git status --short`, `git diff -- path`, `git diff --stat` - inspect changes without modifying worktree.