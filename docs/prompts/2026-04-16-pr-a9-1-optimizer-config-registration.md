# PR-A9.1 — Register `("wealth", "optimizer")` Config Domain (Unblock Smoke)

**Branch:** `feat/pr-a9-1-optimizer-config-registration` (cut from `main`, NOT from `feat/pr-a9-kappa-calibration`)
**Estimated effort:** ~15 minutes (1 file, 8 lines added, 1 test addition)
**Predecessor:** PR-A8 merged (#187, commit `e5fa3190`)
**Successor:** PR-A9 (κ calibration) — blocked on this PR until smoke F.2 passes

---

## Context

Commit `809b56d1` (2026-04-10, "feat(optimizer): parameterize Phase 2 CF relaxation factor per tenant") added a runtime call to `ConfigService.get("wealth", "optimizer", str(org_id))` in `backend/app/domains/wealth/routes/model_portfolios.py:2190` (inside `_run_construction_async`).

**The bug:** the `("wealth", "optimizer")` domain was never registered in `backend/app/core/config/registry.py`. ConfigRegistry currently has zero entries with `vertical="wealth"` (only `liquid_funds`, `private_credit`, `_admin`).

**Effect:** `ConfigService.get()` calls `ConfigRegistry.validate_lookup()` (logs warning), then `_handle_miss()`. Because `domain is None` → `is_required = True` (default) → `ConfigMissError` raised every single construction run.

**Empirical evidence (2026-04-16, post PR-A8 smoke attempt on local DB head 0141):**

```
Conservative Preservation: status=failed wall=2099ms
Balanced Income:           status=failed wall=2099ms
Dynamic Growth:            status=failed wall=2099ms

All three failed at model_portfolios.py:2190:
  app.shared.exceptions.ConfigMissError:
      Required config missing: (wealth, optimizer). Check migration 0004 seed data.
```

This is a 6-day-old pre-existing bug, not a PR-A9 regression. PR-A9's κ-calibration code is correct, but cannot run smoke F.2 against live DB until this is fixed.

---

## Why this fix (and not the alternatives)

The previous Opus session proposed: register domain + add seed migration + relax `ck_defaults_config_type` CHECK constraint. That is a 3-file, schema-touching change with avoidable surface area.

**Minimal correct fix:** register `("wealth", "optimizer")` as `required=False` in `registry.py`. Then:

1. `ConfigRegistry.validate_lookup()` no longer warns (registered).
2. `_handle_miss()` reads `domain.required = False` → returns `ConfigResult(value={}, state=MISSING_OPTIONAL, source="miss")` instead of raising.
3. Existing call site at line 2190-2192 already handles this correctly:
   ```python
   optimizer_result = await config_svc.get("wealth", "optimizer", str(org_id))
   optimizer_config = optimizer_result.value if optimizer_result else {}  # MISSING_OPTIONAL → value={}
   cf_factor = float(optimizer_config.get("cf_relaxation_factor", 1.3))    # falls through to default 1.3
   ```
4. **Zero migration. Zero seed data. Zero CHECK constraint surgery.** `vertical_config_defaults` table stays untouched. When a tenant later wants a non-default `cf_relaxation_factor`, they insert via `VerticalConfigOverride` and the override is picked up automatically.

This matches the pre-existing pattern: `("liquid_funds", "screening_layer1|2|3")` and `("_admin", "branding")` are all `required=False` and ship with no seed.

---

## Scope (single file)

### File: `backend/app/core/config/registry.py`

Add one `ConfigDomain` entry to the `_REGISTRY` tuple. Place it after the `_admin` block (line 127, just before the closing `)`), inside a new `# ── wealth: ConfigService-managed ──` section comment to keep registry organized.

**Insertion (between current line 127 and 128):**

```python
    # ── wealth: ConfigService-managed ────────────────────────────────────
    ConfigDomain(
        vertical="wealth",
        config_type="optimizer",
        ownership="config_service",
        client_visible=False,
        description="Wealth construction-engine optimizer tunables (cf_relaxation_factor, etc.)",
        required=False,
    ),
```

**Field rationale:**
- `vertical="wealth"` — matches the literal in `model_portfolios.py:2190`. Do NOT rename to `liquid_funds`; the call site is the source of truth and changing it expands scope.
- `client_visible=False` — optimizer internals are quant IP, not surfaced to tenants in admin UI.
- `required=False` — total miss returns `MISSING_OPTIONAL` with empty `{}`; the call site already defaults `cf_relaxation_factor` to `1.3`.

**Do NOT:**
- Add a migration. There is no row to seed; defaults live in code.
- Touch `ck_defaults_config_type` CHECK constraint. We are not inserting into the table.
- Modify the call site at `model_portfolios.py:2190-2192`. It is already correct.
- Add `("wealth", "optimizer")` to any YAML fallback map.

---

## Tests

### Test addition: `backend/tests/test_config_registry.py`

Locate the existing `test_verticals` test (around line 78-81). Add `assert "wealth" in verticals` to it. Then add one new test below it:

```python
def test_wealth_optimizer_registered_as_optional(self):
    """PR-A9.1: wealth/optimizer must be registered (otherwise construction
    runs raise ConfigMissError). It must be required=False so that absence
    of seed/override falls through to in-code default cf_relaxation_factor=1.3.
    """
    domain = ConfigRegistry.get("wealth", "optimizer")
    assert domain is not None, "wealth/optimizer must be registered"
    assert domain.required is False, "must be optional — no seed data exists"
    assert domain.client_visible is False, "optimizer internals are IP-protected"
    assert domain.ownership == "config_service"
```

### Test addition: `backend/tests/test_cfg01_config_result.py`

If the file has a parametrized "optional miss returns MISSING_OPTIONAL with value={}" test, add `("wealth", "optimizer")` to its parameter list. If not, leave it alone — the registry test above is sufficient.

### No other test changes expected.

---

## Verification (mandatory, in order)

### V.1 — Lint + typecheck (must be green)

```bash
make lint
make typecheck
```

Both must complete with **no NEW errors** in `backend/app/core/config/registry.py`. Pre-existing baseline failures (Azure, benchmark_ingest) may stay red.

### V.2 — Targeted unit tests

```bash
pytest backend/tests/test_config_registry.py -v
pytest backend/tests/test_config_service.py -v
pytest backend/tests/test_cfg01_config_result.py -v
```

All green. Specifically the new `test_wealth_optimizer_registered_as_optional` must pass.

### V.3 — Live DB smoke (the actual unblock proof)

Pre-condition: docker-compose up, alembic head = `0141_portfolio_status_degraded`, the 3 model_portfolios from `project_worker_population_complete.md` exist.

Trigger one construction run via existing endpoint (use whichever invocation method is wired locally — typically a POST to `/api/wealth/portfolios/{id}/build` or directly enqueueing the worker). Then:

```python
# python -X utf8
import psycopg
with psycopg.connect('postgresql://netz:netz@localhost:5434/netz_engine') as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT mp.display_name, pcr.status, pcr.wall_clock_ms,
                   pcr.failure_reason
            FROM portfolio_construction_runs pcr
            JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
            WHERE pcr.started_at > NOW() - INTERVAL '10 minutes'
            ORDER BY pcr.started_at DESC
            LIMIT 5
        """)
        for r in cur.fetchall():
            print(r)
```

**Pass criterion:** at least one run exits the `ConfigMissError` failure mode. The new `failure_reason` (if any) must NOT contain the substring `"Required config missing: (wealth, optimizer)"`. The run is allowed to fail for OTHER reasons (κ thresholds, optimizer convergence, etc.) — those are PR-A9's territory, not A9.1's.

The minimum bar for A9.1 is: the smoke advances PAST line 2190 of `model_portfolios.py`. Whatever happens after that is downstream.

---

## Pass criteria summary

| # | Criterion | How verified |
|---|---|---|
| 1 | `("wealth", "optimizer")` returned by `ConfigRegistry.get()` | `test_wealth_optimizer_registered_as_optional` |
| 2 | Domain has `required=False` | same test |
| 3 | `make lint` + `make typecheck` produce no NEW errors | manual run |
| 4 | All `test_config_*` files green | pytest |
| 5 | Smoke construction run advances past `model_portfolios.py:2190` | live DB query of `failure_reason` |
| 6 | No migration added, no CHECK constraint modified | `git diff --stat` shows ONE file changed (`registry.py`) plus test files |

---

## Commit + PR

**Branch:** `feat/pr-a9-1-optimizer-config-registration` (cut from `main`, NOT from PR-A9 branch — this must merge first and independently).

**Commit message:**

```
fix(config): register wealth/optimizer domain as optional (PR-A9.1)

Commit 809b56d1 (2026-04-10) added a ConfigService.get("wealth",
"optimizer", ...) call inside _run_construction_async but never
registered the domain in ConfigRegistry. Every construction run
since has failed with ConfigMissError before reaching the optimizer.

Register ("wealth", "optimizer") as required=False so total miss
returns ConfigResult(value={}, state=MISSING_OPTIONAL). The existing
call site already defaults cf_relaxation_factor to 1.3 when the
config dict is empty, so no seed migration is needed.

Unblocks PR-A9 smoke (F.2) and any tenant attempting a portfolio
construction run on a database without wealth/optimizer override.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

**PR title:** `fix(config): register wealth/optimizer domain as optional (PR-A9.1)`

**PR body:**

```markdown
## Summary
- Register ("wealth", "optimizer") in ConfigRegistry as required=False
- Add test_wealth_optimizer_registered_as_optional
- Unblocks PR-A9 (κ calibration) smoke F.2 and any production tenant attempting portfolio construction

## Root cause
Commit 809b56d1 added `config_svc.get("wealth", "optimizer", ...)` without registering the domain. CFG-01 default is required=True → every construction run raises ConfigMissError before reaching the optimizer. Pre-existing bug, not introduced by PR-A9.

## Fix shape
Single ConfigDomain entry, required=False. Call site at model_portfolios.py:2190-2192 already handles MISSING_OPTIONAL correctly (defaults cf_relaxation_factor to 1.3 from the in-code literal). No migration, no seed, no CHECK constraint changes.

## Test plan
- [x] `pytest backend/tests/test_config_registry.py` green (incl. new test_wealth_optimizer_registered_as_optional)
- [x] `pytest backend/tests/test_config_service.py` green
- [x] `pytest backend/tests/test_cfg01_config_result.py` green
- [x] `make lint` no new errors
- [x] `make typecheck` no new errors in registry.py
- [x] Live DB smoke: construction run advances past model_portfolios.py:2190 (no more ConfigMissError on (wealth, optimizer))

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

**Auto-merge:** `gh pr merge <n> --squash --delete-branch --auto` once CI green AND all 6 pass criteria above met.

---

## What happens after merge

1. Rebase `feat/pr-a9-kappa-calibration` onto new `main`.
2. Re-run PR-A9 smoke F.1 query.
3. Evaluate PR-A9 F.2 pass criteria on real data:
   - 3 portfolios `status=succeeded`
   - `solver=clarabel`
   - `n_weights >= 20`
   - `covariance_source in ("sample", "factor_model")`
   - `kappa_sample in [1e3, 1e5]`
   - `wall_clock_ms in [45_000, 120_000]`
4. If pass → merge PR-A9. If fail → diagnose downstream (κ recalibration is genuine work; A9.1 only removes the upstream block).

---

## Out of scope (do NOT do in A9.1)

- Renaming the call site from `"wealth"` to `"liquid_funds"` (registry naming consistency cleanup — file separate ticket).
- Adding any seed row to `vertical_config_defaults` (no default values worth persisting; in-code 1.3 is the default).
- Building admin UI for `("wealth", "optimizer")` overrides (`client_visible=False`, intentionally hidden).
- Any change to `optimizer_service.py` or κ thresholds (that's PR-A9).
- Touching `_run_construction_async` beyond the existing call site (already correct).

---

**End of spec. Execute exactly. Brutal honesty on smoke results — if construction runs still fail with ConfigMissError after this change, the registry import is being shadowed somewhere and we need to find it. Do not invent a workaround.**
