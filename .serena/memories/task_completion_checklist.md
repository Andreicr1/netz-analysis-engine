# Task Completion Checklist

Before claiming a backend change is complete:
- Run the narrowest relevant pytest target first, e.g. `make test ARGS="-k pattern"` or `cd backend && python -m pytest path/to/test.py`.
- Run `make lint` for Python lint changes.
- Run `make typecheck` when touching typed backend/domain/service code.
- Run `make architecture` when touching imports, vertical engines, quant_engine dependencies, or package boundaries.
- Run `make check` for broad backend changes or before handoff when feasible.
- If a change touches migrations/schema, verify `make migrate` against local DB when feasible and inspect Alembic revision dependencies/head state.
- If a change touches runtime guardrails, run `make coverage-runtime` or relevant runtime tests.

Before claiming a frontend change is complete:
- Run package-specific checks when scoped: `make check-terminal`, `make lint-terminal`, or `pnpm --filter <package> check` / `lint` / `test`.
- For shared UI packages, run package build/check/tests as relevant (`pnpm --filter @investintell/ui build`, `check`, `test`; similarly for `@netz/ui`).
- For broad frontend changes, run `make check-all` and/or `make build-all` when feasible.
- For route/UI behavior changes, verify in a browser or Playwright when practical. Root Playwright scripts include `pnpm test:e2e`, `pnpm test:e2e:credit`, `pnpm test:e2e:wealth`.
- If generated API types are needed, run backend then `make types`.

Data/domain safety checklist:
- Confirm tenant-scoped reads filter by organization and use RLS/session helpers.
- Confirm global market/SEC/instrument tables are not incorrectly filtered by tenant.
- Confirm user-facing code does not call external data providers directly in hot paths.
- Confirm runtime config uses ConfigService, not YAML seed files.
- Confirm storage writes use StorageClient and path helpers.
- Confirm prompts or proprietary prompt content are not exposed to clients.

Git/worktree hygiene:
- Inspect `git status --short` and relevant diffs before final summary.
- Do not revert unrelated dirty worktree changes.
- Mention tests/checks actually run. If not run, state that clearly and why.