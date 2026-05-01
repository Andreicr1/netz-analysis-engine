"""PR-BE-7 — migration 0199 consolidates legacy ``aggressive`` into ``growth``.

The migration is purely a defensive backfill (every wealth row in the
local docker DB and Timescale Cloud target is already on the canonical
3-profile enum per the F1 audit, 2026-04-30). These tests assert:

  * The migration revision chain points at the prior head.
  * The upgrade SQL targets the four expected tables.
  * The downgrade explicitly rejects reversal.

Live-DB invariants (no row carries ``aggressive`` after upgrade) are
covered by the broader integration suite — kept out of this file so it
can run in fast CI without the docker compose stack.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "core"
    / "db"
    / "migrations"
    / "versions"
    / "0199_q165_consolidate_aggressive_into_growth.py"
)


def test_migration_file_exists() -> None:
    assert _MIGRATION_PATH.is_file(), f"missing migration: {_MIGRATION_PATH}"


def test_revision_chain_anchored_at_0198_head() -> None:
    src = _MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "0199_q165_consolidate_aggressive_into_growth"' in src
    assert (
        'down_revision = "0198_q159_rebuild_mv_nport_sector_attribution"' in src
    ), "PR-BE-7 must rebase on the current alembic head (0198_q159)."


# Profile-column tables are rewritten via a loop over ``_PROFILE_TABLES``;
# the test asserts each table name is present in the tuple literal.
@pytest.mark.parametrize("table", [
    "model_portfolios",
    "strategic_allocation",
    "allocation_approvals",
    "allocation_template_audit",
    "backtest_runs",
    "portfolio_snapshots",
    "rebalance_events",
    "taa_regime_state",
    "tactical_positions",
])
def test_upgrade_covers_each_profile_column_table(table: str) -> None:
    src = _MIGRATION_PATH.read_text(encoding="utf-8")
    assert f'"{table}",' in src, (
        f"upgrade _PROFILE_TABLES must include {table!r} — Codex P2 "
        "catch on PR #463 required full sweep of profile-column tables "
        "to honour the 180-day alias compat contract."
    )


def test_upgrade_rewrites_mandate_in_portfolio_calibration() -> None:
    src = _MIGRATION_PATH.read_text(encoding="utf-8")
    assert (
        "UPDATE portfolio_calibration SET mandate = 'growth' "
        "WHERE mandate = 'aggressive'" in src
    )


# ── Phase 1 — pre-UPDATE dedup (Codex P3 catch on PR #463) ───────────
# Five tables enforce uniqueness on a key tuple that includes ``profile``;
# the migration must DELETE colliding aggressive rows BEFORE the UPDATE
# loop so a legacy environment with both ``growth`` and ``aggressive``
# rows for the same logical key does not abort with unique-violation.

@pytest.mark.parametrize("table,join_predicate", [
    ("model_portfolios", "mp_g.organization_id = mp_a.organization_id"),
    ("portfolio_snapshots", "ps_g.snapshot_date = ps_a.snapshot_date"),
    ("rebalance_events", "re_g.event_type = 'drift_rebalance'"),
    ("taa_regime_state", "ts_g.as_of_date = ts_a.as_of_date"),
    ("tactical_positions", "tp_g.block_id = tp_a.block_id"),
])
def test_upgrade_dedups_before_rewriting(table: str, join_predicate: str) -> None:
    src = _MIGRATION_PATH.read_text(encoding="utf-8")
    assert f"DELETE FROM {table}" in src, (
        f"upgrade must DELETE colliding aggressive rows from {table} "
        "BEFORE the UPDATE loop (unique-key collision risk)."
    )
    assert join_predicate in src, (
        f"DELETE on {table} must scope by the partial-index key "
        f"({join_predicate!r}) so non-colliding aggressive rows survive "
        "to be rewritten in phase 2."
    )


def test_downgrade_explicitly_rejects_reversal() -> None:
    src = _MIGRATION_PATH.read_text(encoding="utf-8")
    assert "raise NotImplementedError" in src
    assert "consolidates" in src.lower(), (
        "downgrade docstring must explain why the rollback is unsupported"
    )
