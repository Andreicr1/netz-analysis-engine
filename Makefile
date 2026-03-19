.PHONY: check test lint typecheck architecture serve migrate migration help pipeline \
       dev-ui build-ui dev-credit build-credit dev-wealth build-wealth dev-admin build-admin \
       dev-all build-all check-all types

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

architecture:
	cd backend && lint-imports --config ../pyproject.toml

# ── Serve (dev) ───────────────────────────────────────────
serve:
	cd backend && uvicorn app.main:app --reload --port 8000

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
	pnpm --filter @netz/ui dev

build-ui:
	pnpm --filter @netz/ui build

dev-credit:
	pnpm --filter netz-credit-intelligence dev

build-credit:
	pnpm --filter netz-credit-intelligence build

dev-wealth:
	pnpm --filter netz-wealth-os dev

build-wealth:
	pnpm --filter netz-wealth-os build

dev-admin:
	pnpm --filter netz-admin dev

build-admin:
	pnpm --filter netz-admin build

dev-all:
	pnpm exec turbo run dev

build-all:
	pnpm exec turbo run build

check-all:
	pnpm exec turbo run check

types:
	npx openapi-typescript http://localhost:8000/openapi.json -o packages/ui/src/types/api.d.ts

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
	@echo "make dev-ui      - @netz/ui watch mode"
	@echo "make build-ui    - Build @netz/ui package"
	@echo "make dev-credit  - Credit frontend dev server"
	@echo "make dev-wealth  - Wealth frontend dev server"
	@echo "make dev-admin   - Admin frontend dev server"
	@echo "make dev-all     - All packages in parallel (Turborepo)"
	@echo "make build-all   - Build all packages (topological order)"
	@echo "make check-all   - Check all frontend packages"
	@echo "make types       - Generate TS types from OpenAPI schema"
