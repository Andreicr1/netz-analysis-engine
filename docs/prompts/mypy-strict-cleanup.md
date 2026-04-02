# Mypy Strict Cleanup — 2,777 errors to zero

## Context

`pyproject.toml` has `strict = true` for mypy. The codebase has 2,777 errors accumulated over rapid feature development. The goal is to reach **zero errors** so `make typecheck` passes cleanly as part of `make check`.

**Config:** `pyproject.toml` lines 125-136 — `strict = true`, plugins = `pydantic.mypy` + `sqlalchemy.ext.mypy.plugin`, `python_version = "3.12"`, `mypy_path = "backend"`.

**Run command:** `cd backend && python -m mypy . --config-file ../pyproject.toml`

## Strategy: Fix by category, not by file

The errors cluster into a few dominant categories. Fix them in this order — each wave eliminates hundreds of errors at once.

---

### Wave 1 — Missing stubs + ignore_missing_imports (~80 errors)

Add missing libraries to the `[[tool.mypy.overrides]]` ignore list in `pyproject.toml` (line 134-136). These are third-party libs without stubs that will never have them:

```
asyncpg, fitz, pandas, reportlab.*, yaml, jsonschema, dateutil.*, requests,
cachetools, openpyxl.*, boto3, botocore.*, sklearn.*, statsmodels.*,
datacommons_client, aeon.*, pymoo.*, pymc, arviz, svglib.*, pypdf,
edgartools, docx, lmstudio, aiohttp
```

Also add the deprecated Azure modules that are kept for rollback:
```
azure.*
```

And the missing internal modules (stale imports from removed code):
```
app.domains.credit.modules.deals.ai_mode,
app.domains.credit.modules.ai.ingest_job_model,
app.domains.credit.modules.deals.doc_reclassification,
app.domains.credit.modules.actions.models,
app.services.presentation_data,
app.services.presentation_builder
```

**Action:** Update the single `[[tool.mypy.overrides]]` block to include all of these. This alone should eliminate ~80 errors.

---

### Wave 2 — `no-untyped-def` in tests (~1,500 errors)

Tests account for ~1,660 errors total, and ~1,500 are `no-untyped-def` (test functions without return annotations). The fix is a single mypy override:

```toml
[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
disallow_untyped_calls = false
```

This is standard practice — test functions don't need return type annotations. This single override eliminates ~1,500 errors.

---

### Wave 3 — `no-untyped-def` in scripts (~100 errors)

Same pattern for `scripts/` and `tmp_*`:

```toml
[[tool.mypy.overrides]]
module = ["scripts.*", "tmp_*"]
disallow_untyped_defs = false
disallow_untyped_calls = false
```

---

### Wave 4 — `no-untyped-def` in migrations (~50 errors)

Alembic migrations have `upgrade()` and `downgrade()` without annotations:

```toml
[[tool.mypy.overrides]]
module = ["app.core.db.migrations.*"]
disallow_untyped_defs = false
disallow_untyped_calls = false
```

---

### Wave 5 — Missing generic type params (`dict`, `list`, `tuple`) (~430 errors)

These are `dict` without `dict[str, Any]`, `list` without `list[str]`, etc. Fix file by file, starting with the top offenders:

| File | Errors | Typical fix |
|------|--------|-------------|
| `quant_engine/optimizer_service.py` | 40 | `dict` -> `dict[str, Any]`, `list` -> `list[float]` |
| `app/domains/credit/modules/ai/models.py` | 26 | Pydantic model field annotations |
| `app/domains/wealth/services/quant_queries.py` | 20 | `dict` -> `dict[str, Any]` |
| `vertical_engines/wealth/monthly_report/monthly_report_engine.py` | 19 | `dict` -> `dict[str, Any]` |
| `app/domains/wealth/workers/universe_sync.py` | 18 | `dict` -> `dict[str, Any]`, `tuple` -> `tuple[str, ...]` |
| `app/domains/credit/modules/ai/schemas.py` | 18 | Pydantic field annotations |
| `app/domains/wealth/workers/nport_fund_discovery.py` | 17 | `dict` -> `dict[str, Any]` |
| `app/domains/wealth/workers/treasury_ingestion.py` | 14 | `dict` -> `dict[str, Any]` |

**Pattern:** Open each file, find bare `dict`, `list`, `tuple`, `Callable`, `Match`, `Pattern`, `Select`, `Column` and add type parameters. Use `dict[str, Any]` when the shape is heterogeneous, specific types when obvious.

---

### Wave 6 — `union-attr` on DB connections (~50 errors)

Pattern: `Item "None" of "DBAPIConnection | None" has no attribute "commit"`. These are in migration files using `op.get_bind().connect()`. Fix with:

```python
conn = op.get_bind()
assert conn is not None
conn.execute(...)
```

Or add to migration override (Wave 4 already covers this).

---

### Wave 7 — Remaining real type errors (~100 errors)

These are actual type mismatches that need individual fixes:
- `Returning Any from function` — add explicit casts or return annotations
- `Incompatible types in assignment` — fix the type or add a cast
- `attr-defined` on ORM models — verify column exists or fix attribute name
- `arg-type` mismatches — fix caller or callee signature

Fix these file by file. The top files are:
- `vertical_engines/credit/portfolio/covenants.py` (13)
- `vertical_engines/credit/portfolio/drift.py` (12)
- `ai_engine/pdf/memo_md_to_pdf.py` (11)
- `ai_engine/prompts/registry.py` (10)

---

## Execution order

1. Waves 1-4 first (pyproject.toml overrides only, ~1,730 errors eliminated, zero code changes)
2. Wave 5 (mechanical, file-by-file, ~430 errors)
3. Waves 6-7 (targeted fixes, ~150 errors)

After each wave, run `cd backend && python -m mypy . --config-file ../pyproject.toml 2>&1 | grep "error:" | wc -l` to track progress.

## Verification

```bash
make typecheck  # must exit 0
make check      # full gate: lint + architecture + typecheck + test
```

## Rules

- Do NOT weaken `strict = true` globally — use targeted `[[tool.mypy.overrides]]` per module
- Do NOT add `# type: ignore` comments unless there is genuinely no other fix (e.g., third-party lib returning wrong type)
- Do NOT change business logic — this is a typing-only cleanup
- Do NOT change function signatures in ways that affect callers — if a function returns `dict`, annotate it as `dict[str, Any]`, don't restructure it
- Run `make test` after Waves 5-7 to ensure nothing breaks
