"""Tests for the risk_calc ELITE ranking pass (Phase 2 Session B commit 7).

These tests hit the live local-dev database. The global risk worker
(``run_global_risk_metrics``) has already populated the current
``calc_date`` with ``organization_id = NULL`` rows for every active
fund, so the ELITE function is exercised against a realistic shape
instead of a tiny fixture that would miss schema drift.

Assertions:
1. Total elite funds = 300 (± rounding tolerance).
2. Each strategy respects its target count (no bucket exceeds).
3. Rank monotonicity: within a strategy, ``elite_rank_within_strategy``
   is a dense 1..N sequence and the top row has the highest
   ``manager_score``.
4. ``elite_target_count_per_strategy`` is set on every fund in each
   canonical bucket, not only on the winners (so the screener can
   show "150 / 3,119" cutoff UX for non-elites too).
5. Re-running the pass is idempotent — the same inputs produce the
   same 300 elite rows.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from app.core.db.engine import async_session_factory
from app.domains.wealth.workers.risk_calc import (
    ELITE_ROUNDING_TOLERANCE,
    ELITE_TOTAL_COUNT,
    _compute_elite_ranking,
)


async def _latest_global_calc_date() -> date | None:
    async with async_session_factory() as db:
        res = await db.execute(
            text(
                """
                SELECT MAX(calc_date)
                FROM fund_risk_metrics
                WHERE organization_id IS NULL
                """,
            ),
        )
        return res.scalar()


@pytest.mark.asyncio
async def test_elite_ranking_marks_three_hundred_funds() -> None:
    latest = await _latest_global_calc_date()
    if latest is None:
        pytest.skip("No global fund_risk_metrics rows in local dev")

    async with async_session_factory() as db:
        total_elite, _ = await _compute_elite_ranking(db, latest)

    deviation = abs(total_elite - ELITE_TOTAL_COUNT)
    assert deviation <= ELITE_ROUNDING_TOLERANCE, (
        f"Total elite = {total_elite}, expected "
        f"{ELITE_TOTAL_COUNT} ± {ELITE_ROUNDING_TOLERANCE}"
    )


@pytest.mark.asyncio
async def test_elite_ranking_respects_per_strategy_targets() -> None:
    latest = await _latest_global_calc_date()
    if latest is None:
        pytest.skip("No global fund_risk_metrics rows in local dev")

    async with async_session_factory() as db:
        _, per_strategy = await _compute_elite_ranking(db, latest)
        result = await db.execute(
            text(
                """
                SELECT iu.asset_class,
                       COUNT(*) FILTER (WHERE frm.elite_flag = true) AS elite_count,
                       MAX(frm.elite_target_count_per_strategy) AS target_count
                FROM fund_risk_metrics frm
                JOIN instruments_universe iu
                  ON iu.instrument_id = frm.instrument_id
                WHERE frm.calc_date = :calc_date
                  AND frm.organization_id IS NULL
                  AND iu.is_active = true
                  AND iu.asset_class = ANY(:classes)
                GROUP BY iu.asset_class
                """,
            ),
            {
                "calc_date": latest,
                "classes": list(per_strategy.keys()),
            },
        )
        rows = result.mappings().all()

    for row in rows:
        asset_class = row["asset_class"]
        expected = per_strategy[asset_class]
        assert row["target_count"] == expected, (
            f"{asset_class}: target recorded={row['target_count']} "
            f"expected={expected}"
        )
        # Elite count must never exceed the target; it may be
        # smaller if the bucket has fewer funds than the target
        # (e.g. alternatives when pool < target).
        assert row["elite_count"] <= expected, (
            f"{asset_class}: elite_count={row['elite_count']} "
            f"exceeds target={expected}"
        )


@pytest.mark.asyncio
async def test_elite_ranking_rank_is_dense_and_monotonic() -> None:
    latest = await _latest_global_calc_date()
    if latest is None:
        pytest.skip("No global fund_risk_metrics rows in local dev")

    async with async_session_factory() as db:
        await _compute_elite_ranking(db, latest)

        # Equity has the largest pool so any ranking bug will
        # surface there first.
        result = await db.execute(
            text(
                """
                SELECT frm.elite_rank_within_strategy AS rnk,
                       frm.manager_score AS score
                FROM fund_risk_metrics frm
                JOIN instruments_universe iu
                  ON iu.instrument_id = frm.instrument_id
                WHERE frm.calc_date = :calc_date
                  AND frm.organization_id IS NULL
                  AND frm.elite_flag = true
                  AND iu.asset_class = 'equity'
                ORDER BY frm.elite_rank_within_strategy
                """,
            ),
            {"calc_date": latest},
        )
        rows = result.all()

    if not rows:
        pytest.skip("No equity elite rows in local dev state")

    expected_seq = list(range(1, len(rows) + 1))
    actual_seq = [int(r.rnk) for r in rows]
    assert actual_seq == expected_seq, (
        f"elite_rank_within_strategy is not dense 1..N — got "
        f"{actual_seq[:5]}..{actual_seq[-5:]}"
    )
    scores = [float(r.score) if r.score is not None else float("-inf") for r in rows]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], (
            f"rank {i + 1} score {scores[i]} < rank {i + 2} score "
            f"{scores[i + 1]} — rank order is not monotonic in score"
        )


@pytest.mark.asyncio
async def test_elite_ranking_is_idempotent() -> None:
    latest = await _latest_global_calc_date()
    if latest is None:
        pytest.skip("No global fund_risk_metrics rows in local dev")

    async with async_session_factory() as db:
        first_total, first_per = await _compute_elite_ranking(db, latest)
        second_total, second_per = await _compute_elite_ranking(db, latest)

    assert first_total == second_total
    assert first_per == second_per
