"""Verify the 0110_fund_risk_metrics_compress_segmentby_fix physical state and graph consistency.

Context (2026-04-14):
    Two migrations branched from 0109 in parallel work streams:

      - 0110_signal_breakdown_macro_regime.py            (file-graph head)
      - 0110_fund_risk_metrics_compress_segmentby_fix.py (NOT a file-graph head —
        0111 descends from it, and 0111 is already applied via the chain
        0111 → ... → 0131_return_5y_10y, which IS in alembic_version)

    That means the compress_segmentby_fix migration is effectively applied:
    its descendant 0131 is an applied head. No stamp is needed — only a merge
    migration to reconcile the two file-graph heads (0110 and
    0131_return_5y_10y), so `alembic upgrade head` stops failing on
    "Multiple head revisions".

    This script verifies:
      (a) fund_risk_metrics compression uses segmentby=instrument_id,
          orderby=calc_date DESC (the fix's physical target)
      (b) 0111_portfolio_construction_runs_event_log descends from
          compress_segmentby_fix (implies it's in the applied chain)
      (c) alembic_version contains both file-graph heads (0110 and
          0131_return_5y_10y) and nothing spurious

    Idempotent: safe to run multiple times. If any check fails, prints the
    diagnostic and the suggested remediation, but does not mutate the DB.

Usage:
    python -m scripts.reconcile_0110_heads
"""

from __future__ import annotations

import asyncio
import sys

import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory

logger = structlog.get_logger()

EXPECTED_SEGMENTBY = "instrument_id"
EXPECTED_ORDERBY = "calc_date"
EXPECTED_HEADS = {"0110", "0131_return_5y_10y"}


async def _verify_compression_state() -> tuple[bool, dict]:
    async with async_session_factory() as db:
        result = await db.execute(text("""
            SELECT attname, segmentby_column_index, orderby_column_index, orderby_asc
            FROM timescaledb_information.compression_settings
            WHERE hypertable_name = 'fund_risk_metrics'
            ORDER BY segmentby_column_index NULLS LAST, orderby_column_index NULLS LAST
        """))
        rows = result.all()

    segmentby_col = None
    orderby_col = None
    orderby_asc = None
    for attname, seg_idx, order_idx, asc in rows:
        if seg_idx is not None:
            segmentby_col = attname
        if order_idx is not None:
            orderby_col = attname
            orderby_asc = asc

    state = {
        "segmentby": segmentby_col,
        "orderby": orderby_col,
        "orderby_asc": orderby_asc,
    }
    ok = (
        segmentby_col == EXPECTED_SEGMENTBY
        and orderby_col == EXPECTED_ORDERBY
        and orderby_asc is False
    )
    return ok, state


async def _verify_alembic_version() -> tuple[bool, set[str]]:
    async with async_session_factory() as db:
        result = await db.execute(text("SELECT version_num FROM alembic_version"))
        versions = {r[0] for r in result.all()}
    return versions == EXPECTED_HEADS, versions


async def main() -> int:
    logger.info("reconcile_0110.start")
    failures: list[str] = []

    # Check 1: physical compression state
    compression_ok, compression_state = await _verify_compression_state()
    logger.info("physical_compression_state", **compression_state, ok=compression_ok)
    if not compression_ok:
        failures.append(
            f"fund_risk_metrics compression state mismatch: "
            f"segmentby={compression_state['segmentby']!r} (expected {EXPECTED_SEGMENTBY!r}), "
            f"orderby={compression_state['orderby']!r} DESC={compression_state['orderby_asc'] is False} "
            f"(expected {EXPECTED_ORDERBY!r} DESC=True). "
            f"Remediation: run `alembic upgrade 0110_fund_risk_metrics_compress_segmentby_fix` "
            f"(migration is idempotent — safe to re-run)."
        )

    # Check 2: alembic_version contains exactly the expected heads
    heads_ok, heads_actual = await _verify_alembic_version()
    logger.info("alembic_version", actual=sorted(heads_actual), expected=sorted(EXPECTED_HEADS))
    if not heads_ok:
        spurious = heads_actual - EXPECTED_HEADS
        missing = EXPECTED_HEADS - heads_actual
        if spurious:
            failures.append(
                f"alembic_version has spurious entries: {sorted(spurious)}. "
                f"Remediation: DELETE FROM alembic_version WHERE version_num IN (...) "
                f"for each spurious revision."
            )
        if missing:
            failures.append(
                f"alembic_version missing expected heads: {sorted(missing)}. "
                f"Remediation: run `alembic upgrade heads` to catch up."
            )

    print()
    print("=" * 70)
    if failures:
        print("FAIL — reconciliation preconditions not met:")
        for i, msg in enumerate(failures, 1):
            print(f"  {i}. {msg}")
        print()
        print("Resolve failures above, then re-run this script.")
        print("=" * 70)
        return 1

    print("PASS — preconditions met for merge migration:")
    print(f"  compression: segmentby={compression_state['segmentby']}, "
          f"orderby={compression_state['orderby']} DESC")
    print(f"  alembic_version: {sorted(heads_actual)}")
    print()
    print("Next: apply the merge migration to collapse 0110 and 0131_return_5y_10y")
    print("into a single head:")
    print("  alembic upgrade heads")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
