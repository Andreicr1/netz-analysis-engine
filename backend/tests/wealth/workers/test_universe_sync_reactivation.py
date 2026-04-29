"""Tests for universe_sync is_active reactivation (PR-Q94).

Validates C-01: all 6 ON CONFLICT clauses include is_active in the UPDATE SET,
ensuring that _deactivate_no_nav deactivation is reversed on next sync run
when the source table still contains the ticker.

Approach: mock the AsyncSession, call each sync function, capture the SQL
executed, and assert that the ON CONFLICT clause sets is_active.
"""

from __future__ import annotations  # noqa: I001

import pytest

from app.domains.wealth.workers import universe_sync as mod


# ── Helpers ────────────────────────────────────────────────────────────


class _CapturingResult:
    """Minimal CursorResult proxy."""

    def __init__(self, rowcount: int = 0):
        self.rowcount = rowcount

    def scalar(self):
        return None


class _CapturingSession:
    """Fake AsyncSession that captures executed SQL text."""

    def __init__(self):
        self.executed_sql: list[str] = []

    async def execute(self, stmt, params=None):
        self.executed_sql.append(str(stmt))
        return _CapturingResult(rowcount=0)

    async def commit(self):
        pass


def _extract_on_conflict_sql(sqls: list[str]) -> str | None:
    """Find the SQL statement containing ON CONFLICT and return it."""
    for sql in sqls:
        if "ON CONFLICT" in sql.upper():
            return sql
    return None


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


# ── Phase 1: SEC ETFs ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_etf_reactivation_sets_is_active():
    """_sync_sec_etfs ON CONFLICT includes is_active = EXCLUDED.is_active."""
    db = _CapturingSession()
    await mod._sync_sec_etfs(db)  # type: ignore[arg-type]

    clause = _extract_on_conflict_clause(db.executed_sql)
    assert clause is not None, "Expected ON CONFLICT clause from _sync_sec_etfs"
    clause_lower = clause.lower()
    assert "is_active" in clause_lower, "ON CONFLICT clause must reference is_active"
    assert (
        "is_active = excluded.is_active" in clause_lower
        or "is_active = true" in clause_lower
    ), f"_sync_sec_etfs ON CONFLICT must reactivate. Clause was:\n{clause}"


# ── Phase 2: SEC MF Series ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_mf_series_reactivation_sets_is_active():
    """_sync_sec_mf_series ON CONFLICT includes is_active = EXCLUDED.is_active."""
    db = _CapturingSession()
    await mod._sync_sec_mf_series(db)  # type: ignore[arg-type]

    clause = _extract_on_conflict_clause(db.executed_sql)
    assert clause is not None, "Expected ON CONFLICT clause from _sync_sec_mf_series"
    clause_lower = clause.lower()
    assert "is_active" in clause_lower, "ON CONFLICT clause must reference is_active"
    assert (
        "is_active = excluded.is_active" in clause_lower
        or "is_active = true" in clause_lower
    ), f"_sync_sec_mf_series ON CONFLICT must reactivate. Clause was:\n{clause}"


# ── Phase 3: SEC Registered Funds ────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_registered_reactivation_sets_is_active():
    """_sync_sec_registered ON CONFLICT sets is_active = true.

    Changed from DO NOTHING to DO UPDATE SET is_active = true, updated_at = now().
    Only reactivates — does not overwrite Phase 2's richer name/attributes.
    """
    db = _CapturingSession()
    await mod._sync_sec_registered(db)  # type: ignore[arg-type]

    clause = _extract_on_conflict_clause(db.executed_sql)
    assert clause is not None, "Expected ON CONFLICT clause from _sync_sec_registered"
    # Must no longer use DO NOTHING
    assert "DO NOTHING" not in clause.upper(), (
        "_sync_sec_registered must not use DO NOTHING (blocks reactivation)"
    )
    clause_lower = clause.lower()
    assert "is_active" in clause_lower, "ON CONFLICT clause must reference is_active"
    assert (
        "is_active = excluded.is_active" in clause_lower
        or "is_active = true" in clause_lower
    ), f"_sync_sec_registered ON CONFLICT must reactivate. Clause was:\n{clause}"


# ── Phase 3b: SEC BDCs ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_bdcs_reactivation_sets_is_active():
    """_sync_sec_bdcs ON CONFLICT includes is_active = EXCLUDED.is_active."""
    db = _CapturingSession()
    await mod._sync_sec_bdcs(db)  # type: ignore[arg-type]

    clause = _extract_on_conflict_clause(db.executed_sql)
    assert clause is not None, "Expected ON CONFLICT clause from _sync_sec_bdcs"
    clause_lower = clause.lower()
    assert "is_active" in clause_lower, "ON CONFLICT clause must reference is_active"
    assert (
        "is_active = excluded.is_active" in clause_lower
        or "is_active = true" in clause_lower
    ), f"_sync_sec_bdcs ON CONFLICT must reactivate. Clause was:\n{clause}"


# ── Phase 4: ESMA UCITS ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_esma_funds_reactivation_sets_is_active():
    """_sync_esma_funds ON CONFLICT includes is_active = EXCLUDED.is_active."""
    db = _CapturingSession()
    await mod._sync_esma_funds(db)  # type: ignore[arg-type]

    clause = _extract_on_conflict_clause(db.executed_sql)
    assert clause is not None, "Expected ON CONFLICT clause from _sync_esma_funds"
    clause_lower = clause.lower()
    assert "is_active" in clause_lower, "ON CONFLICT clause must reference is_active"
    assert (
        "is_active = excluded.is_active" in clause_lower
        or "is_active = true" in clause_lower
    ), f"_sync_esma_funds ON CONFLICT must reactivate. Clause was:\n{clause}"


# ── Phase 5: SEC MMFs ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_mmfs_reactivation_sets_is_active():
    """_sync_sec_mmfs ON CONFLICT includes is_active = EXCLUDED.is_active."""
    db = _CapturingSession()
    await mod._sync_sec_mmfs(db)  # type: ignore[arg-type]

    clause = _extract_on_conflict_clause(db.executed_sql)
    assert clause is not None, "Expected ON CONFLICT clause from _sync_sec_mmfs"
    clause_lower = clause.lower()
    assert "is_active" in clause_lower, "ON CONFLICT clause must reference is_active"
    assert (
        "is_active = excluded.is_active" in clause_lower
        or "is_active = true" in clause_lower
    ), f"_sync_sec_mmfs ON CONFLICT must reactivate. Clause was:\n{clause}"


# ── Q106: NOT EXISTS prefilter guard ────────────────────────────────


@pytest.mark.asyncio
async def test_sec_registered_no_not_exists_prefilter():
    """Q106: _sync_sec_registered must NOT prefilter on NOT EXISTS — that
    blocked the reactivation path the Q94 fix was meant to enable."""
    db = _CapturingSession()
    await mod._sync_sec_registered(db)  # type: ignore[arg-type]

    matched = [s for s in db.executed_sql if "FROM sec_registered_funds" in s]
    assert matched, "Expected _sync_sec_registered to issue an INSERT against sec_registered_funds"
    sql = matched[0]
    # Strip SQL comments (-- ...) before checking, so the Q106 explanatory
    # comment ("NOT EXISTS prefilter removed") doesn't trigger a false positive.
    import re
    sql_no_comments = re.sub(r"--[^\n]*", "", sql)
    assert "NOT EXISTS" not in sql_no_comments.upper(), (
        "_sync_sec_registered must not prefilter via NOT EXISTS — it blocks reactivation"
    )
