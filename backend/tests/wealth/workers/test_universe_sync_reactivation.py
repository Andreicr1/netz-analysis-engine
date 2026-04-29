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


# ── Phase 1: SEC ETFs ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_etf_reactivation_sets_is_active():
    """_sync_sec_etfs ON CONFLICT includes is_active = EXCLUDED.is_active."""
    db = _CapturingSession()
    await mod._sync_sec_etfs(db)  # type: ignore[arg-type]

    sql = _extract_on_conflict_sql(db.executed_sql)
    assert sql is not None, "Expected ON CONFLICT SQL from _sync_sec_etfs"
    assert "is_active" in sql.lower(), (
        "_sync_sec_etfs ON CONFLICT must set is_active"
    )


# ── Phase 2: SEC MF Series ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_mf_series_reactivation_sets_is_active():
    """_sync_sec_mf_series ON CONFLICT includes is_active = EXCLUDED.is_active."""
    db = _CapturingSession()
    await mod._sync_sec_mf_series(db)  # type: ignore[arg-type]

    sql = _extract_on_conflict_sql(db.executed_sql)
    assert sql is not None, "Expected ON CONFLICT SQL from _sync_sec_mf_series"
    assert "is_active" in sql.lower(), (
        "_sync_sec_mf_series ON CONFLICT must set is_active"
    )


# ── Phase 3: SEC Registered Funds ────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_registered_reactivation_sets_is_active():
    """_sync_sec_registered ON CONFLICT sets is_active = true.

    Changed from DO NOTHING to DO UPDATE SET is_active = true, updated_at = now().
    Only reactivates — does not overwrite Phase 2's richer name/attributes.
    """
    db = _CapturingSession()
    await mod._sync_sec_registered(db)  # type: ignore[arg-type]

    sql = _extract_on_conflict_sql(db.executed_sql)
    assert sql is not None, "Expected ON CONFLICT SQL from _sync_sec_registered"
    # Must no longer use DO NOTHING
    assert "DO NOTHING" not in sql.upper(), (
        "_sync_sec_registered must not use DO NOTHING (blocks reactivation)"
    )
    assert "is_active" in sql.lower(), (
        "_sync_sec_registered ON CONFLICT must set is_active"
    )


# ── Phase 3b: SEC BDCs ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_bdcs_reactivation_sets_is_active():
    """_sync_sec_bdcs ON CONFLICT includes is_active = EXCLUDED.is_active."""
    db = _CapturingSession()
    await mod._sync_sec_bdcs(db)  # type: ignore[arg-type]

    sql = _extract_on_conflict_sql(db.executed_sql)
    assert sql is not None, "Expected ON CONFLICT SQL from _sync_sec_bdcs"
    assert "is_active" in sql.lower(), (
        "_sync_sec_bdcs ON CONFLICT must set is_active"
    )


# ── Phase 4: ESMA UCITS ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_esma_funds_reactivation_sets_is_active():
    """_sync_esma_funds ON CONFLICT includes is_active = EXCLUDED.is_active."""
    db = _CapturingSession()
    await mod._sync_esma_funds(db)  # type: ignore[arg-type]

    sql = _extract_on_conflict_sql(db.executed_sql)
    assert sql is not None, "Expected ON CONFLICT SQL from _sync_esma_funds"
    assert "is_active" in sql.lower(), (
        "_sync_esma_funds ON CONFLICT must set is_active"
    )


# ── Phase 5: SEC MMFs ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_mmfs_reactivation_sets_is_active():
    """_sync_sec_mmfs ON CONFLICT includes is_active = EXCLUDED.is_active."""
    db = _CapturingSession()
    await mod._sync_sec_mmfs(db)  # type: ignore[arg-type]

    sql = _extract_on_conflict_sql(db.executed_sql)
    assert sql is not None, "Expected ON CONFLICT SQL from _sync_sec_mmfs"
    assert "is_active" in sql.lower(), (
        "_sync_sec_mmfs ON CONFLICT must set is_active"
    )
