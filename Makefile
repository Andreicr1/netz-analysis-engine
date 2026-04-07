.PHONY: check test lint typecheck architecture serve migrate migration help pipeline \
       dev-ui build-ui dev-credit build-credit dev-wealth build-wealth \
       dev-all build-all lint-frontend check-all types coverage-runtime

# ── Unified gate ──────────────────────────────────────────
check: lint architecture typecheck test
	@echo "All checks passed."

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
	@echo "make dev-all     - All packages in parallel (Turborepo)"
	@echo "make build-all   - Build all packages (topological order)"
	@echo "make lint-frontend - ESLint all frontend packages"
	@echo "make check-all   - Lint + check all frontend packages"
	@echo "make types       - Generate TS types from OpenAPI schema"
