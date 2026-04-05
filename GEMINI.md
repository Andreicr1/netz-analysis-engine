# GEMINI.md

## Project Identity
**Netz Analysis Engine** is an institutional-grade investment operating system designed for Wealth Management and Private Credit. It integrates regulatory, quantitative, and documentary data into a unified multi-tenant environment.

### Core Verticals
- **Wealth (Portfolio Management)**: Macro intelligence (FRED, BIS, IMF), portfolio optimization, fund screening (SEC, ESMA), and automated Due Diligence reports.
- **Credit (Underwriting)**: Document ingestion (OCR), semantic chunking, and Deep Review IC memos with evidence tracking.

---

## Foundational Mandates

### 1. Multi-Tenancy & Security
- **Strict Isolation**: Tenant data (portfolios, documents, reports) MUST be segregated. Shared global data (SEC, ESMA, Macro) is accessible to all, but private data must never leak across organizations.
- **RLS & Versioning**: Row-Level Security and versioning are critical for auditability.
- **Credential Protection**: Never log or commit secrets. Protect `.env` and configuration files rigorously.

### 2. Architecture & Performance
- **Zero Latency Requests**: User requests MUST NOT trigger external API calls (e.g., Yahoo Finance, FRED). All external data ingestion must be handled by background workers.
- **Time-Series Native**: Use TimescaleDB features (hyper-tables, compression, continuous aggregates) for all market and economic data.
- **Import Linter DAG**: Strictly follow the architecture enforced in `pyproject.toml`:
  - `models` (leaf) → `domain modules` → `persist` → `portfolio` → `service` (top).
  - Verticals (Credit vs. Wealth) must remain independent.
  - Domain helpers must not import the entry-point `service`.

### 3. Engineering Standards
- **Backend**: Python 3.12+, FastAPI, SQLAlchemy (AsyncIO), Pydantic v2.
  - **Strict Typing**: All new code must pass `mypy --strict`.
  - **Linting**: Adhere to Ruff configurations.
  - **AsyncIO**: Use async/await for all I/O bound operations (DB, Redis, S3).
- **Frontend**: Turborepo managed with `pnpm`.
  - Prefer established UI patterns in `packages/ui` and `packages/investintell-ui`.
- **Validation**: 
  - Every bug fix requires a reproduction script/test.
  - Run `turbo run check` and `pytest` before declaring a task complete.

### 4. Workflow & Verification
- **Task Tracking**: Refer to the `todos/` directory for the backlog and historical context of completed tasks.
- **Testing**:
  - **Backend**: Pytest with `pytest-asyncio`.
  - **E2E**: Playwright tests for cross-vertical flows.
- **Documentation**: Keep `docs/` updated with architectural changes or new domain integrations.

---

## Security First
- **JWT Verification**: Always verify tokens in frontend hooks and backend dependencies.
- **XSS/Injection**: Sanitize all HTML content (using `nh3` or equivalent) before rendering reports.
- **Data Leakage**: Ensure error messages do not leak internal system details or tenant-specific metadata.
