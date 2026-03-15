.PHONY: check test lint typecheck architecture serve migrate migration help pipeline

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
