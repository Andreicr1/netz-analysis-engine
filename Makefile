.PHONY: check test lint typecheck architecture serve migrate migration help pipeline \
       dev-ui build-ui dev-credit build-credit dev-wealth build-wealth \
       dev-terminal build-terminal check-terminal lint-terminal \
       dev-all build-all lint-frontend check-all types coverage-runtime \
       tokens-sync loadtest

# ── Unified gate ──────────────────────────────────────────
check: lint architecture typecheck tokens-sync test
	@echo "All checks passed."

# ── Terminal token drift sentinel ─────────────────────────
# Compares packages/investintell-ui/src/lib/tokens/terminal.css
# against DEFAULT_TOKENS in terminal-options.ts. Fails the gate
# if either side adds, renames, or removes a chart-relevant
# token without updating the other. Pure Node — no install.
tokens-sync:
	node scripts/check-terminal-tokens-sync.mjs

# ── Python backend ────────────────────────────────────────
lint:
	cd backend && python -m ruff check .

typecheck:
	cd backend && python -m mypy app/ --ignore-missing-imports

test:
	cd backend && python -m pytest tests/ $(ARGS)

# Coverage report for the Stability Guardrails runtime kit
# (design spec §2 + §2.8, acceptance criterion C2 ≥ 95%).
# Both --cov flags are required: the runtime package AND the
# p95_guard middleware living one directory over. Using a slash
# path (`app/core/middleware/p95_guard`) silently drops the
# middleware as "module-not-imported" — always use dotted paths.
coverage-runtime:
	cd backend && python -m pytest tests/runtime/ \
		--cov=app.core.runtime \
		--cov=app.core.middleware.p95_guard \
		--cov-report=term-missing $(ARGS)

architecture:
	cd backend && lint-imports --config ../pyproject.toml

# ── Serve (dev) ───────────────────────────────────────────
serve:
	cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# ── Load test — screener ELITE fast path ─────────────────
# Proves the Phase 3 Screener hot path stays under 300ms p95
# and that the mv_fund_risk_latest partial index is actually
# used by the query planner. Must be green before every ship.
#
# Expects a backend already running on the port specified by
# NETZ_LOADTEST_BASE_URL (default http://127.0.0.1:8765). Start
# the backend with RATE_LIMIT_ENABLED=false so the throughput
# phase is not gated by the production per-org rate cap. Example:
#
#   RATE_LIMIT_ENABLED=false ENV=development \
#       uvicorn app.main:app --port 8765 --log-level warning &
#   make loadtest
#
# Env vars:
#   NETZ_LOADTEST_BASE_URL (default http://127.0.0.1:8765)
#   NETZ_LOADTEST_P95_MS   (default 300 — DO NOT raise)
#   NETZ_LOADTEST_DURATION (default 30 seconds)
#   NETZ_LOADTEST_CONCURRENCY (default 20 workers)
loadtest:
	cd backend && python -m tests.loadtest.screener_elite

# ── Database ──────────────────────────────────────────────
migrate:
	cd backend && alembic upgrade head

migration:
	cd backend && alembic revision --autogenerate -m "$(MSG)"

# ── Docker ────────────────────────────────────────────────
up:
	docker-compose up -d

down:
	docker-compose down

# ── Frontend (pnpm + Turborepo) ──────────────────────────
dev-ui:
	pnpm --filter @investintell/ui dev

build-ui:
	pnpm --filter @investintell/ui build

dev-credit:
	pnpm --filter netz-credit-intelligence dev

build-credit:
	pnpm --filter netz-credit-intelligence build

dev-wealth:
	pnpm --filter netz-wealth-os dev

build-wealth:
	pnpm --filter netz-wealth-os build

dev-terminal:
	pnpm --filter ii-terminal dev

build-terminal:
	pnpm --filter ii-terminal build

check-terminal:
	pnpm --filter ii-terminal check

lint-terminal:
	pnpm --filter ii-terminal lint

dev-all:
	pnpm exec turbo run dev

build-all:
	pnpm exec turbo run build

lint-frontend:
	pnpm exec turbo run lint

check-all:
	pnpm exec turbo run lint check

types:
	npx openapi-typescript http://localhost:8000/openapi.json -o packages/investintell-ui/src/types/api.d.ts

# ── Help ──────────────────────────────────────────────────
help:
	@echo "make check       - Full gate: lint + architecture + typecheck + test"
	@echo "make test        - pytest (ARGS for extra flags)"
	@echo "make lint        - ruff check"
	@echo "make typecheck   - mypy"
	@echo "make architecture - import-linter DAG enforcement"
	@echo "make serve       - uvicorn dev server on :8000"
	@echo "make migrate     - alembic upgrade head"
	@echo "make migration   - generate new migration (MSG=description)"
	@echo "make up          - docker-compose up -d"
	@echo "make down        - docker-compose down"
	@echo ""
	@echo "── Frontend ────────────────────────────────────────"
	@echo "make dev-ui      - @investintell/ui watch mode"
	@echo "make build-ui    - Build @investintell/ui package"
	@echo "make dev-credit  - Credit frontend dev server"
	@echo "make dev-wealth  - Wealth frontend dev server"
	@echo "make dev-terminal - II Terminal frontend dev server (:5175)"
	@echo "make build-terminal - Build II Terminal frontend"
	@echo "make check-terminal - svelte-check on II Terminal"
	@echo "make lint-terminal  - ESLint on II Terminal"
	@echo "make dev-all     - All packages in parallel (Turborepo)"
	@echo "make build-all   - Build all packages (topological order)"
	@echo "make lint-frontend - ESLint all frontend packages"
	@echo "make check-all   - Lint + check all frontend packages"
	@echo "make types       - Generate TS types from OpenAPI schema"
	@echo ""
	@echo "── Performance ────────────────────────────────────"
	@echo "make loadtest    - Screener ELITE p95 gate (must be <300ms)"
