# PR-Q94 Re-Dispatch — Fix Test Fixtures (post-fail)

**Status:** READY FOR DISPATCH (fresh Opus 4.7 1M session)
**Context:** First Q94 dispatch produced PR #395 with code fix that compiled and pushed, but **5 of 5 reactivation tests fail in CI** with `InvalidColumnReferenceError: there is no unique or exclusion constraint matching the ON CONFLICT specification`. This is a test fixture bug — the production fix is presumably correct, but tests cannot exercise it.

PR #395 is currently OPEN with the failing CI. Re-dispatch this prompt to a fresh Opus 4.7 (1M) session; the agent should either commit a fixture fix on top of the existing branch (`fix/pr-q94-universe-sync-reactivation`) or close #395 and open a fresh PR.

---

## STAGE — Q94 Re-dispatch

You are implementing the test-fixture fix for PR-Q94, an in-flight remediation for Wave 6 Session 09 finding C-01 (universe_sync ON CONFLICT omits is_active reactivation, Crit).

The production code fix already shipped to branch `fix/pr-q94-universe-sync-reactivation` (PR #395, currently failing CI). Your job is to **fix the test fixtures** so the existing 5 reactivation tests pass against a complete schema.

## CI failure diagnosis

CI run: https://github.com/Andreicr1/netz-analysis-engine/actions/runs/25085620619/job/73500421949

Failing tests (all 5 in `backend/tests/wealth/workers/test_universe_sync_reactivation.py`):
- `test_sec_etf_reactivation_after_deactivate`
- `test_sec_registered_reactivation_after_deactivate`
- `test_sec_bdc_reactivation_after_deactivate`
- `test_esma_fund_reactivation_after_deactivate`
- `test_sec_mmf_reactivation_after_deactivate`

Error (identical for all 5):
```
asyncpg.exceptions.InvalidColumnReferenceError:
  there is no unique or exclusion constraint matching the ON CONFLICT specification
```

## Root cause hypothesis

The production code uses `INSERT ... ON CONFLICT (ticker) DO UPDATE SET ...` (and similar for non-ticker keys per sync function). For Postgres to accept `ON CONFLICT (ticker)`, there must be a UNIQUE or EXCLUSION constraint on the `ticker` column.

In the production schema (migration 0012), `instruments_universe.ticker` has a UNIQUE constraint via `uq_iu_ticker`.

**Likely failure mode:** the test fixture creates a synthetic `instruments_universe` table without the UNIQUE constraint (e.g. via `CREATE TABLE` shortcut, or `metadata.create_all` against a stripped-down model), so `ON CONFLICT (ticker)` is rejected.

## Required fix

Use the **real schema** in tests. The project pattern is to apply all alembic migrations to the test DB once at session-scope. There are two viable approaches:

### Approach A — use existing `db_session` fixture (preferred if available)

Look for a project fixture that yields an `AsyncSession` against a Docker-compose `netz-analysis-engine-db-1` test DB with all migrations applied. Examples in repo:
- `backend/tests/db/test_migration_0096.py` — uses raw `asyncpg.connect` against settings.database_url; no fixture.
- `backend/tests/db/test_migration_0194_q91.py` — same pattern.
- Other tests under `backend/tests/wealth/` — check for `conftest.py` with `db_session` or `async_db_session` fixture.

If a session-scoped fixture exists that runs `alembic upgrade head` and yields a clean session, USE IT. Each test wraps inserts/updates in a transaction that rolls back.

### Approach B — create test data via SQLAlchemy ORM models, not raw CREATE TABLE

If no fixture exists, your test should:
```python
from app.domains.wealth.models.instrument import Instrument

@pytest.mark.asyncio
async def test_sec_etf_reactivation_after_deactivate(db_session):
    # Insert via ORM — uses the real table with all constraints
    inst = Instrument(
        instrument_type="fund",
        name="Test ETF",
        ticker="TEST_ETF_REACT",
        asset_class="equity",
        geography="US",
        attributes={"aum_usd": 1000000000, "manager_name": "Test", "inception_date": "2020-01-01"},
    )
    db_session.add(inst)
    await db_session.commit()

    # Manually deactivate (simulate _deactivate_no_nav)
    inst.is_active = False
    await db_session.commit()

    # Insert NAV row to simulate "data arrived"
    # ...

    # Re-run the sync function (or simulate its upsert path)
    # ...

    # Refresh and assert
    await db_session.refresh(inst)
    assert inst.is_active is True
```

The key is: **never create a synthetic `instruments_universe` table** in the test. Always use the migrated schema.

## Constraints

- Do NOT modify the production code in `backend/app/domains/wealth/workers/universe_sync.py` (Q94 fix already applied and reviewed).
- Do NOT widen the test scope — the 5 tests already exist and have correct assertions; only the fixture/setup needs correction.
- If you find that the project genuinely lacks a session-scoped DB fixture for tests of this style, you may add one in `backend/tests/conftest.py` or `backend/tests/wealth/conftest.py`, but keep it minimal: yield a clean `AsyncSession` against the migrated DB, with `expire_on_commit=False`, wrapped in a transaction that rolls back at end of test.
- Run lint: `.venv/Scripts/python.exe -m ruff check backend/tests/wealth/workers/test_universe_sync_reactivation.py`
- Run the 5 tests locally before pushing:
  `cd backend && ../.venv/Scripts/python.exe -m pytest tests/wealth/workers/test_universe_sync_reactivation.py -v`
- Confirm 5/5 pass with no `InvalidColumnReferenceError`.

## Acceptance

- 5 reactivation tests pass against migrated schema
- CI test-backend goes green on the existing PR #395 (or new PR if you closed and reopened)
- Lint clean
- No production code changes

## PR description

If you commit on the existing branch, no new PR description needed (current #395 description still applies). If you opened a fresh PR (closing #395), title:

`fix(wealth): PR-Q94' — universe_sync reactivation tests use migrated schema (Crit, fixture fix)`

Reference Wave 6 Session 09 C-01 verdict + the original #395 PR with explanation that fixtures were the only blocker.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
