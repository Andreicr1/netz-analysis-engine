# PR-Q104 — Codex Auto Review hotfix — regime_fit lock-owning session held idle in transaction (P1)

**Status:** READY FOR DISPATCH (fresh Opus 4.7 1M session)
**Origin:** Codex Auto Review on PR-Q99 ([#403](https://github.com/Andreicr1/netz-analysis-engine/pull/403)) — P1 catch
**Target file:** `backend/app/domains/wealth/workers/regime_fit.py`
**Severity:** P1 (production race window during managed-Postgres idle-tx timeout)
**Memory:** `feedback_codex_review_integration.md` — Codex P1 catches → standalone hotfix immediately.

---

## STAGE — Q104 Hotfix

You are implementing PR-Q104, a narrow hotfix for a Codex Auto Review P1 catch on PR-Q99 (regime_fit advisory lock acquire/release, Wave 6 Session 09 finding C-04, already merged to main as commit `[regime_fit lock]`).

The Q99 fix introduced a different production risk: the lock-owning `AsyncSession` is held idle in transaction for the entire duration of the regime fit job, while the actual work runs on three separate child sessions. In managed Postgres environments (Timescale Cloud, AWS RDS) with `idle_in_transaction_session_timeout` configured (typical default 5 minutes), the lock-owning session can be terminated by the server during phase 2 (CPU-bound `_fit_markov_regime`), implicitly releasing the advisory lock. A second concurrent worker would then start, reintroducing the very race Q99 was meant to prevent.

This hotfix restructures the execution to use a single session for the entire job + explicit commits between phases. Advisory locks are session-scoped (not transaction-scoped) and survive `COMMIT` / `ROLLBACK`, so committing between phases keeps the session healthy without releasing the lock.

## CODEX CATCH (verbatim)

> `run_regime_fit` acquires `pg_try_advisory_lock` on one `AsyncSession`, but `_do_regime_fit` immediately opens new sessions and performs all reads/writes there, leaving the lock-owning session idle in an open transaction for the whole job. In environments with `idle_in_transaction_session_timeout`, PostgreSQL can terminate that idle lock-holder and implicitly release the advisory lock while the job is still running, allowing a second worker to start and reintroducing the concurrent-write race this change is meant to prevent.

## CURRENT CODE (from main, post-Q99)

`backend/app/domains/wealth/workers/regime_fit.py`:

```python
async def _do_regime_fit() -> dict[str, Any]:
    async with async_session() as db:                  # SESSION B — child
        vix_with_dates = await _fetch_vix_series_with_dates(db)

    n_obs = len(vix_with_dates)
    if n_obs < MIN_VIX_OBS:
        return {"status": "skipped", "reason": "insufficient_vix_history", "n_obs": n_obs}

    # ... CPU computation _fit_markov_regime — no DB activity, but session A still idle in tx ...
    high_vol_probs = _fit_markov_regime(vix_values)

    if high_vol_probs is None:
        return {"status": "skipped", "reason": "fitting_failed"}

    # ... derive series ...

    async with async_session() as db:                  # SESSION C — child
        n_persisted = await _persist_regime_history(db, dates_list, ...)

    async with async_session() as db:                  # SESSION D — child
        n_updated = await _update_snapshots_with_regime_probs(db, p_high)

    return {"status": "completed", ...}


async def run_regime_fit() -> dict[str, Any]:
    async with async_session() as db:                  # SESSION A — lock-owner
        lock_result = await db.execute(text(f"SELECT pg_try_advisory_lock({LOCK_ID})"))
        if not lock_result.scalar():
            return {"status": "skipped", "reason": "lock_held"}
        try:
            return await _do_regime_fit()              # children opened here, A is idle
        finally:
            await db.execute(text(f"SELECT pg_advisory_unlock({LOCK_ID})"))
```

## REQUIRED FIX

Refactor so all DB operations use the **same session A**. Explicit `db.commit()` after each phase (and after lock acquisition) so the session is never left idle inside an open transaction.

### Pattern

```python
async def _do_regime_fit(db: AsyncSession) -> dict[str, Any]:
    """Core regime fitting logic — uses lock-owning session for all I/O.

    Phase commits are explicit so the session is never idle in an open
    transaction across CPU-bound work or external waits.
    """
    vix_with_dates = await _fetch_vix_series_with_dates(db)
    await db.commit()  # phase 1 done; session is idle but NOT in transaction

    n_obs = len(vix_with_dates)
    if n_obs < MIN_VIX_OBS:
        logger.warning(...)
        return {"status": "skipped", "reason": "insufficient_vix_history", "n_obs": n_obs}

    # ... existing pre-fit prep ...

    high_vol_probs = _fit_markov_regime(vix_values)  # CPU only; session not in tx
    if high_vol_probs is None:
        return {"status": "skipped", "reason": "fitting_failed"}

    # ... existing post-fit derivation ...

    n_persisted = await _persist_regime_history(db, dates_list, ...)
    await db.commit()  # phase 3 done

    n_updated = await _update_snapshots_with_regime_probs(db, p_high)
    await db.commit()  # phase 4 done

    return {"status": "completed", ...}


async def run_regime_fit() -> dict[str, Any]:
    logger.info("Starting Markov regime fitting")

    async with async_session() as db:
        lock_result = await db.execute(text(f"SELECT pg_try_advisory_lock({LOCK_ID})"))
        lock_acquired = bool(lock_result.scalar())
        await db.commit()  # close the implicit tx opened by lock query; lock persists

        if not lock_acquired:
            logger.warning("Regime fit already running — skipping")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            return await _do_regime_fit(db)
        finally:
            await db.execute(text(f"SELECT pg_advisory_unlock({LOCK_ID})"))
            await db.commit()
```

### Helper signature changes

`_fetch_vix_series_with_dates`, `_persist_regime_history`, `_update_snapshots_with_regime_probs` already accept `db: AsyncSession` as their first argument. **No signature changes** — just pass through the lock-owning session instead of opening new ones.

## CONSTRAINTS

- **Do NOT change `LOCK_ID`** or the lock acquire/release pattern at the outer level.
- **Do NOT modify** `_fetch_vix_series_with_dates`, `_persist_regime_history`, `_update_snapshots_with_regime_probs` bodies. Only callers change.
- Keep the `pg_advisory_unlock(LOCK_ID)` in `finally` — required for clean release on exception.
- Keep the `await db.commit()` after the unlock — closes the unlock query's implicit tx.
- Keep the existing 5 tests in `backend/tests/wealth/workers/test_regime_fit_lock.py` passing — they don't depend on session topology.
- **DO add 1 new test** covering the new invariant (see below).

## REQUIRED NEW TEST

Add to `backend/tests/wealth/workers/test_regime_fit_lock.py`:

```python
@pytest.mark.asyncio
async def test_regime_fit_uses_lock_owning_session_for_all_io():
    """Q104 invariant: all phases of regime fit must use the lock-owning
    session, not child sessions. This prevents idle-in-transaction timeout
    from killing the lock-holder mid-job and silently releasing the lock.

    Verified by patching async_session() and asserting it's called exactly once.
    """
    from unittest.mock import patch, AsyncMock
    from app.domains.wealth.workers import regime_fit

    call_count = 0
    real_factory = regime_fit.async_session

    def counting_factory(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_factory(*args, **kwargs)

    with patch.object(regime_fit, 'async_session', side_effect=counting_factory):
        # Will likely return "skipped" because no real VIX data in test DB,
        # but that's fine — we're checking session topology, not output.
        await regime_fit.run_regime_fit()

    assert call_count == 1, (
        f"Expected exactly 1 async_session() open (lock-owning session). "
        f"Got {call_count}. _do_regime_fit must use the passed db, not open new sessions."
    )
```

If your test environment lacks fixtures for VIX/macro data and the function short-circuits before reaching all phases, the test still validates the invariant: only one session was opened at any point.

## ACCEPTANCE

- `_do_regime_fit` accepts `db: AsyncSession` parameter
- `run_regime_fit` passes its `db` to `_do_regime_fit`
- Three `async with async_session() as db:` blocks inside `_do_regime_fit` removed (replaced by direct use of passed `db`)
- 4 explicit `await db.commit()` placed: after lock acquire (lines ~325), after fetch phase, after persist phase, after snapshot update phase, and 1 in finally after unlock (5 commits total — but the final one is in `finally` not the happy path proper)
- 1 new test (`test_regime_fit_uses_lock_owning_session_for_all_io`) passes
- All 5 existing Q99 tests still pass
- Lint clean: `.venv/Scripts/python.exe -m ruff check backend/app/domains/wealth/workers/regime_fit.py backend/tests/wealth/workers/test_regime_fit_lock.py`

## PR DESCRIPTION

Title: `fix(wealth): PR-Q104 — Codex P1 — regime_fit lock-owning session held idle in transaction`

Body:

```markdown
## Codex Auto Review P1 catch (post-merge of PR-Q99 #403)

Q99 introduced advisory lock around `run_regime_fit` to fix Wave 6 S09 C-04 (dead lock ID). The implementation acquires the lock on one `AsyncSession` and runs the job body in three child sessions, leaving the lock-owning session idle in an open transaction for the entire ~30-60s job duration.

In managed Postgres (Timescale Cloud, AWS RDS) with `idle_in_transaction_session_timeout` configured (typical default 5 min), the server can terminate the idle lock-holder mid-job, implicitly releasing the advisory lock and reintroducing the concurrent-write race C-04 was meant to prevent.

## Fix

Pass the lock-owning session through to `_do_regime_fit` and use it for all I/O. Explicit `await db.commit()` between phases so the session is never idle inside an open transaction across CPU-bound `_fit_markov_regime` work. Advisory locks are session-scoped (not transaction-scoped) and survive commits, so the lock persists across phase boundaries.

## Test plan

- [x] `test_regime_fit_uses_lock_owning_session_for_all_io` — new invariant: exactly 1 `async_session()` opened
- [x] All 5 existing Q99 tests still pass
- [x] `make lint` clean

## Out of scope

Sweep of other workers for the same pattern → handoff to Q105+ if Codex flags more or to a future Wave 6 follow-up audit. Workers known to follow this anti-pattern: TBD by review.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.

## DISPATCH NOTES (for Andrei)

- Open fresh Opus 4.7 (1M) session in worktree (or local repo).
- Paste this prompt entirely.
- Agent commits + pushes branch `fix/pr-q104-regime-fit-session-fix`.
- After push, return to me — I open the PR with body matching the sketch above (same pattern as Sprint 1+2).
