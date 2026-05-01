# Style and Conventions

General engineering stance:
- Treat this as an institutional asset/wealth management system: deterministic math, auditability, tenant isolation, performance envelopes, and operational safety are first-class requirements.
- Prefer existing repo patterns and domain boundaries over new abstractions.
- Do not revert unrelated user changes in the worktree.

Python/backend style:
- Python target is 3.12; line length is 100. Ruff selects E/F/I/B/SIM, with several migration-era ignores in `pyproject.toml`.
- Mypy is strict for backend app code. Use type hints consistently.
- FastAPI route handlers should be `async def`, use `AsyncSession` from `get_db_with_rls`, declare `response_model=`, and return Pydantic objects via `model_validate()` rather than raw inline dict serialization.
- SQLAlchemy relationships should use `lazy="raise"`; load explicitly with `selectinload()`/`joinedload()`.
- Use `expire_on_commit=False`; avoid implicit async ORM I/O.
- RLS context must use `SET LOCAL`, not `SET`. RLS policies should use `(SELECT current_setting(...))` to avoid per-row performance cliffs.
- Avoid module-level asyncio primitives (`Semaphore`, `Lock`, `Event`); create lazily in async context.
- Extract scalar values/frozen dataclasses before crossing async/thread boundaries with ORM data.
- Advisory lock keys must be deterministic (e.g. `zlib.crc32`), never Python `hash()`.

Architecture/import rules:
- `vertical_engines.credit` and `vertical_engines.wealth` must remain independent.
- In vertical engine packages, `service.py` is the entry point. Models/helpers must not import from `service.py`; `service.py` imports helpers.
- Quant services should stay vertical-agnostic and should not import `app.domains.wealth`.
- Credit business logic in `vertical_engines/credit/` should not be rewritten casually; only narrow session injection is called out as allowed in docs.

Data/config/storage rules:
- Use `ConfigService.get(vertical, config_type, org_id)` for runtime config. YAML in `profiles/` and `calibration/` is seed-only.
- Use `StorageClient` abstraction; do not call R2/ADLS SDKs directly from business code.
- Storage path construction must go through `storage_routing.py` helpers such as `bronze_document_path()`, `silver_chunks_path()`, `silver_metadata_path()`, `gold_memo_path()`.
- Storage write is source of truth and should happen before pgvector upsert. pgvector is a derived index that can be rebuilt from silver Parquet.
- Silver Parquet must include `embedding_model` and `embedding_dim`.
- Tenant-scoped vector/DuckDB queries must filter by `organization_id`; global wealth vector data has `organization_id IS NULL` and should be handled intentionally.
- Global tables such as `instruments_universe`, `nav_timeseries`, `fund_risk_metrics`, SEC tables, macro/benchmark data have no RLS and no tenant ownership. Org scoping for instruments is via `instruments_org`.

External data and workers:
- User-facing routes and vertical engines read from DB. Do not call external APIs such as FRED, Treasury, OFR, Yahoo/Tiingo, SEC EDGAR in request hot paths.
- SEC provider services expose DB-only and fetch methods; routes/DD reports must use DB-only reads and leave fetch/discovery calls to ingestion workers.

Frontend style:
- SvelteKit/Svelte 5 + TypeScript. Use existing design systems and tokens.
- Wealth/Terminal use `@investintell/ui` (`--ii-*`, dark-first, Urbanist/Geist). Credit uses `@netz/ui` (`--netz-*`, light-first, IBM Plex).
- Frontends never cross-import each other. Wealth should not directly import `@netz/ui` components unless using the documented compatibility bridge; Credit should not import `@investintell/ui`.
- Number/date/currency formatting in frontend code must use exported formatters from the design system (`formatNumber`, `formatCurrency`, `formatPercent`, `formatDate`, etc.). Avoid `.toFixed()`, `.toLocaleString()`, and direct `new Intl.*` in app code.
- For routes/detail pages with failure states, prefer RouteData load contracts and boundary/error components per stability guardrails.

Wealth math conventions:
- Drawdowns are negative throughout the codebase; max drawdown is the most negative point.
- Sterling ratio uses original Kestner convention: `ann_return / |avg_max_dd - 0.10|` with negative drawdowns.
- Attribution cash residual uses `r_cash = 0.0` unless an IC policy explicitly introduces overnight/SOFR attribution.