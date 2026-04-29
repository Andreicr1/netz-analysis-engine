# PR-Q106 — Codex Auto Review hotfix — Q94 reactivation correctness (P1 + P2 batch)

**Status:** READY FOR DISPATCH (fresh Opus 4.7 1M session)
**Origin:** Codex Auto Review on PR-Q94 commit (Wave 6 S09 C-01) — 1 P1 + 1 P2 catch
**Target files:**
- `backend/app/domains/wealth/workers/universe_sync.py` (`_sync_sec_registered`)
- `backend/tests/wealth/workers/test_universe_sync_reactivation.py`
**Severity:** P1 (Q94 reactivation broken for sec_registered phase) + P2 (test gives false positive)

---

## STAGE — Q106 Hotfix

You are implementing PR-Q106, a narrow hotfix for two Codex Auto Review catches on the Q94 commit (Wave 6 Session 09 finding C-01, universe_sync ON CONFLICT omits is_active reactivation, already shipped to main). Both catches reveal that the Q94 fix is partially broken in production: the `_sync_sec_registered` phase still excludes deactivated rows before the ON CONFLICT path, so they never get reactivated; and the regression test gives a false positive because it asserts on the whole SQL string rather than the ON CONFLICT clause specifically.

## CATCH 1 — P1: `_sync_sec_registered` NOT EXISTS prefilter blocks reactivation

Codex flagged on Q94 commit:
> This phase still excludes any ticker already present in `instruments_universe` via `NOT EXISTS`, so deactivated rows never reach the new `ON CONFLICT ... DO UPDATE` path. In practice, a previously deactivated direct-ticker registered fund will stay inactive even after its source row remains present and should be reactivated, which defeats the intended reactivation behavior for this phase.

Verified: `backend/app/domains/wealth/workers/universe_sync.py:_sync_sec_registered` (around line 313-355) reads:

```sql
INSERT INTO instruments_universe (...)
SELECT gen_random_uuid(), ...
FROM sec_registered_funds rf
WHERE rf.ticker IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM instruments_universe iu WHERE iu.ticker = rf.ticker
  )
ON CONFLICT (ticker) DO UPDATE SET
    is_active = true,
    updated_at = now()
```

The `NOT EXISTS (SELECT 1 FROM instruments_universe iu WHERE iu.ticker = rf.ticker)` filter excludes any ticker already in `instruments_universe`. Result: when a ticker exists but is deactivated, the SELECT produces zero rows for it → INSERT has nothing to insert → ON CONFLICT never fires → row stays `is_active=false` permanently.

The Q94 docstring promises reactivation; this phase silently does not deliver.

**Severity:** P1. The Q94 remediation for C-01 (Crit) is partially broken in production. SEC registered direct-ticker funds (mutual funds with their own ticker) cannot be reactivated.

## CATCH 2 — P2: regression test gives false positive

Codex flagged on the Q94 test:
> These tests assert `"is_active" in sql.lower()`, but `is_active` already appears in the INSERT column list and SELECT `true` portion, so the check passes even if the ON CONFLICT update stops setting `is_active`. This creates false positives and will not catch regressions in the reactivation logic the test claims to validate.

Verified: `backend/tests/wealth/workers/test_universe_sync_reactivation.py` uses `_extract_on_conflict_sql(db.executed_sql)` to find the ON CONFLICT-containing SQL, but then asserts `"is_active" in sql.lower()` against the entire SQL (which includes the INSERT INTO column list `is_active` and the SELECT-side `true` value).

**Severity:** P2. Not a correctness bug today (Q94 ON CONFLICT clauses do contain `is_active`), but the test will not catch a regression that removes the ON CONFLICT clause's `is_active` setting.

## REQUIRED FIX

### Fix 1 — remove the NOT EXISTS prefilter in `_sync_sec_registered`

The prefilter was originally a defensive guard against Phase 2 (`_sync_sec_mf_series`) overwriting Phase 3's data via ON CONFLICT. Q94 already changed Phase 3 to `ON CONFLICT DO UPDATE SET is_active = true, updated_at = now()` — a minimal update that does NOT touch `name`, `attributes`, or other fields, so it cannot override Phase 2's richer data. The NOT EXISTS prefilter is therefore redundant AND breaks reactivation.

Replace:

```sql
WHERE rf.ticker IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM instruments_universe iu WHERE iu.ticker = rf.ticker
  )
ON CONFLICT (ticker) DO UPDATE SET
    is_active = true,
    updated_at = now()
```

With:

```sql
WHERE rf.ticker IS NOT NULL
ON CONFLICT (ticker) DO UPDATE SET
    is_active = true,
    updated_at = now()
```

Add a SQL-level comment documenting the rationale:

```sql
-- Q106: NOT EXISTS prefilter removed. The minimal ON CONFLICT clause
-- (only is_active + updated_at) cannot overwrite Phase 2's name/attributes,
-- so the prefilter that was preventing the conflict path from firing is
-- redundant and broke Q94's reactivation invariant. See Wave 6 S09 C-01
-- + Codex review on PR-Q94 commit.
```

### Fix 2 — assert ON CONFLICT clause specifically, not whole SQL

Refactor `_extract_on_conflict_sql` (or add a sibling helper) to extract only the substring after `ON CONFLICT` until the end of the SQL statement (or until a known terminator):

```python
def _extract_on_conflict_clause(sqls: list[str]) -> str | None:
    """Return the substring from ON CONFLICT to end of statement.

    Q106: tighter than _extract_on_conflict_sql which returns the full
    statement (where is_active appears in INSERT column list, giving
    false positives in the test).
    """
    for sql in sqls:
        upper = sql.upper()
        idx = upper.find("ON CONFLICT")
        if idx >= 0:
            return sql[idx:]
    return None
```

Then update each test (5 tests in the file) to assert the EXCLUDED-pattern reactivation specifically:

```python
async def test_sec_etf_reactivation_sets_is_active():
    db = _CapturingSession()
    await mod._sync_sec_etfs(db)

    clause = _extract_on_conflict_clause(db.executed_sql)
    assert clause is not None, "Expected ON CONFLICT clause from _sync_sec_etfs"
    # Q106: assert the reactivation pattern is in the ON CONFLICT body,
    # not just somewhere in the SQL (which would include the INSERT columns).
    clause_lower = clause.lower()
    assert "is_active" in clause_lower, "ON CONFLICT clause must reference is_active"
    assert (
        "is_active = excluded.is_active" in clause_lower
        or "is_active = true" in clause_lower
    ), (
        f"_sync_sec_etfs ON CONFLICT must reactivate. Clause was:\n{clause}"
    )
```

Apply the same pattern to all 5 test functions:
- `test_sec_etf_reactivation_sets_is_active`
- `test_sec_mf_series_reactivation_sets_is_active`
- `test_sec_registered_reactivation_sets_is_active` (special: Q94 used `is_active = true` literal, not `EXCLUDED`)
- `test_sec_bdc_reactivation_sets_is_active`
- `test_esma_funds_reactivation_sets_is_active`
- `test_sec_mmf_reactivation_sets_is_active`

For the new behavior introduced in Fix 1 (registered phase), add a test that validates the prefilter is gone:

```python
async def test_sec_registered_no_not_exists_prefilter():
    """Q106: _sync_sec_registered must NOT prefilter on NOT EXISTS — that
    blocked the reactivation path the Q94 fix was meant to enable."""
    db = _CapturingSession()
    await mod._sync_sec_registered(db)

    matched = [s for s in db.executed_sql if "FROM sec_registered_funds" in s]
    assert matched, "Expected _sync_sec_registered to issue an INSERT against sec_registered_funds"
    sql = matched[0]
    assert "NOT EXISTS" not in sql.upper(), (
        "_sync_sec_registered must not prefilter via NOT EXISTS — it blocks reactivation"
    )
```

## CONSTRAINTS

- Do NOT change other ON CONFLICT clauses (Phase 1 ETF, Phase 2 MF series, Phase 3b BDCs, Phase 4 ESMA, Phase 5 MMFs). Those are correct after Q94.
- Do NOT remove or refactor `_deactivate_no_nav` — out of scope.
- Do NOT touch the production code in any phase OTHER than `_sync_sec_registered`.
- The new `_extract_on_conflict_clause` helper must be additive — keep `_extract_on_conflict_sql` if any other test uses it (verify via grep).
- Lint clean: `.venv/Scripts/python.exe -m ruff check backend/app/domains/wealth/workers/universe_sync.py backend/tests/wealth/workers/test_universe_sync_reactivation.py`
- Run all 6 tests: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/wealth/workers/test_universe_sync_reactivation.py -v` — assert all pass.
- Run a smoke validation: `cd backend && docker exec netz-analysis-engine-db-1 psql -U netz -d netz_engine -c "UPDATE instruments_universe SET is_active=false WHERE ticker IN (SELECT rf.ticker FROM sec_registered_funds rf WHERE rf.ticker IS NOT NULL LIMIT 1) AND attributes->>'sec_universe' = 'registered_us';"` then `../.venv/Scripts/python.exe -m app.domains.wealth.workers.universe_sync` and verify the row is now `is_active=true`.

## ACCEPTANCE

- `_sync_sec_registered` no longer has `NOT EXISTS` prefilter; SQL comment documents Q106 rationale
- New helper `_extract_on_conflict_clause` extracts ON CONFLICT body specifically
- 6 reactivation tests use the new helper + assert reactivation pattern (`is_active = EXCLUDED.is_active` or `is_active = true`)
- 1 new test (`test_sec_registered_no_not_exists_prefilter`) passes
- All 7 tests pass
- Smoke reproduces (manual deactivate → universe_sync run → row reactivated)
- Lint clean

## PR DESCRIPTION

Title: `fix(wealth): PR-Q106 — Codex P1+P2 — Q94 reactivation correctness (sec_registered prefilter + test assertion)`

Body sketch:

```markdown
## Codex Auto Review on Q94 commit (Wave 6 S09 C-01) — 2 catches

### P1 — `_sync_sec_registered` NOT EXISTS prefilter blocked reactivation
Q94's `ON CONFLICT DO UPDATE SET is_active = true` was DEAD CODE for
deactivated rows because the WHERE clause's `NOT EXISTS` filter excluded
any ticker already in `instruments_universe`. Reactivation invariant
broken for SEC registered direct-ticker funds.

Fix: remove the prefilter. The minimal ON CONFLICT clause (only is_active
+ updated_at) cannot overwrite Phase 2's name/attributes, so the
prefilter is redundant.

### P2 — regression test asserted `is_active` in whole SQL
The Q94 tests asserted `"is_active" in sql.lower()` against the whole
INSERT statement (where `is_active` appears in the column list and SELECT
side). Test would pass even if ON CONFLICT clause stopped setting
is_active.

Fix: new helper `_extract_on_conflict_clause` extracts ON CONFLICT body
only; tests assert reactivation pattern in that scope.

## Test plan

- [x] 6 existing reactivation tests pass with stricter assertion
- [x] 1 new test (no NOT EXISTS prefilter) passes
- [x] Smoke: manual deactivate → universe_sync → row reactivated
- [x] make lint clean
```

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.

## DISPATCH NOTES (for Andrei)

Branch: `fix/pr-q106-q94-reactivation-correctness`
After agent push, return to me — I open the PR.
