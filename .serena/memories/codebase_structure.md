# Codebase Structure

Root layout:
- `backend/`: Python backend packages and tests.
- `backend/app/`: FastAPI application. `app/main.py` creates the FastAPI app and registers `/api/v1` routers.
- `backend/app/core/`: auth/tenancy/RLS, DB engine and migrations, config, runtime guardrail primitives, jobs, middleware.
- `backend/app/domains/`: API/domain layers. `wealth/` has models, queries, routes, schemas, services, utils, workers. `credit/` has actions, ai, dashboard, dataroom, deals, documents, global_agent, modules, portfolio, reporting.
- `backend/app/services/`: shared app services such as storage client.
- `backend/ai_engine/`: vertical-agnostic ingestion/classification/extraction/validation/prompt/LLM/knowledge pipeline.
- `backend/quant_engine/`: quantitative services: CVaR/tail VaR, optimizer, risk budgeting, Black-Litterman, factor models/PCA/IPCA, GARCH, scoring, regime, rebalance, macro/FRED/Treasury/OFR, fixed income analytics, drawdown/return stats, correlation, stress, momentum.
- `backend/vertical_engines/credit/`: credit vertical packages such as critic, deal_conversion, deep_review, domain_ai, edgar, kyc, market_data, memo, pipeline, portfolio, quant, retrieval, sponsor, underwriting. Package convention: `models.py`, `service.py`, helpers; `service.py` is entry point.
- `backend/vertical_engines/wealth/`: wealth vertical packages such as asset_universe, attribution, correlation, critic, dd_report, fact_sheet, fee_drag, long_form_report, mandate_fit, model_portfolio, monitoring, monthly_report, peer_group, rebalancing, screener, watchlist, plus standalone engines.
- `backend/app/core/db/migrations/versions/`: Alembic migrations. Latest files observed include `0199_q165_consolidate_aggressive_into_growth.py`; docs may mention older heads, so verify with Alembic/files before relying on a documented head.
- `frontends/credit/`: SvelteKit app `netz-credit-intelligence`.
- `frontends/wealth/`: SvelteKit app `netz-wealth-os`.
- `frontends/terminal/`: SvelteKit app `ii-terminal`.
- `packages/ui/`: shared Credit/Netz design system package `@netz/ui`.
- `packages/investintell-ui/`: Wealth/InvestIntell design system package `@investintell/ui`.
- `packages/ii-terminal-core/`: terminal shared core package.
- `packages/eslint-plugin-netz-runtime/`: custom ESLint/runtime linting package.
- `profiles/` and `calibration/`: YAML seed configuration only.
- `docs/`: plans, audits, prompts, diagnostics, references. Relevant reference docs include `docs/reference/frontend-architecture-reference.md`, `docs/reference/wealth-math-conventions.md`, and `docs/reference/stability-guardrails.md`.
- `scripts/`: root scripts including token drift sentinel.
- `infra/`, `.github/`, `e2e/`, `tests/`: infrastructure, CI, E2E and auxiliary tests.

Frontend workspace:
- `pnpm-workspace.yaml` includes `packages/*` and `frontends/*`.
- Turborepo `build` and `check` are topological; `dev` is persistent and uncached.
- Credit uses `@netz/ui`; Wealth and Terminal use `@investintell/ui` and terminal core. Frontends share via design system packages and backend API, not direct cross-imports.