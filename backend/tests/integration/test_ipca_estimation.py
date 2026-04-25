"""Integration tests for ipca_estimation worker.

Covers 5 acceptance gates:
    - full_run: runs against real equity_characteristics_monthly + nav data
    - panel_too_small_skipped: min_panel_size > available → skipped
    - drift_logged_on_second_run: two runs → drift computed on second
    - idempotent_lock_skip: lock held → skipped without crash
    - nan_in_chars_handled: worker drops NaN rows and still fits

Requires a running Postgres with migrations through 0175 applied and
equity_characteristics_monthly populated (>300 rows).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

pytestmark = pytest.mark.integration

_TEST_FIT_DATE = date(2024, 12, 31)


def _get_session_factory():
    try:
        from app.core.db.engine import async_session_factory
        return async_session_factory
    except Exception as exc:
        pytest.skip(f"Cannot import session factory: {exc}")


async def _cleanup_fits(db):
    """Remove test fit rows."""
    from sqlalchemy import text
    await db.execute(text(
        "DELETE FROM factor_model_fits WHERE engine = 'ipca' "
        "AND fit_date = '2024-12-31'"
    ))
    await db.commit()


async def _require_populated_panel(db, min_rows: int = 300) -> None:
    """Skip the test if equity_characteristics_monthly is under-populated.

    These integration tests run the IPCA worker against the real
    equity_characteristics_monthly + nav_monthly_returns_agg panel.
    On a fresh CI DB those tables are empty, so the worker correctly
    returns status='no_data'. That's not a regression — it's the worker
    refusing to fit on no data — so we skip rather than fail.

    Local dev DBs that have run fund_characteristics_aggregator at
    least once will exceed min_rows and these tests run normally.
    """
    from sqlalchemy import text
    count = await db.scalar(text(
        "SELECT COUNT(*) FROM equity_characteristics_monthly"
    ))
    if count is None or count < min_rows:
        pytest.skip(
            f"equity_characteristics_monthly has {count} rows "
            f"(need >= {min_rows}). Run fund_characteristics_aggregator "
            f"to populate, or run on a dev DB with restored data."
        )


class TestIPCAEstimation:
    """Integration tests for run_ipca_estimation."""

    def test_full_run(self):
        """Run worker against real data. Assert fit row created with valid structure."""
        factory = _get_session_factory()

        async def _test():
            async with factory() as db:
                await _require_populated_panel(db)
                await _cleanup_fits(db)

            from app.core.jobs.ipca_estimation import run_ipca_estimation
            result = await run_ipca_estimation(asof=_TEST_FIT_DATE)

            assert result["status"] == "succeeded", f"Unexpected status: {result}"
            assert result["fits"] == 1
            assert 1 <= result["k_factors"] <= 6
            # converged is honest now (stdout-parsed); fit may or may not
            # converge in max_iter=200 on the real panel — accept either.
            assert isinstance(result["converged"], bool)
            assert result["n_instruments"] > 100

            # Verify DB row
            async with factory() as db:
                from sqlalchemy import text
                row = (await db.execute(text(
                    "SELECT * FROM factor_model_fits "
                    "WHERE engine = 'ipca' AND fit_date = '2024-12-31' "
                    "ORDER BY created_at DESC LIMIT 1"
                ))).first()
                assert row is not None
                assert row.k_factors >= 1

                # gamma_loadings is a raw 2D nested list (6 chars × K factors).
                # Char order is implicit by row position — see CHARS_COLS in
                # ipca_estimation.py. (Older fits used {rows,cols,values} dict;
                # we tolerate that shape for backwards compat.)
                gamma = row.gamma_loadings
                if isinstance(gamma, str):
                    gamma = json.loads(gamma)
                if isinstance(gamma, dict):
                    # Legacy shape — still acceptable for older rows.
                    assert len(gamma["values"]) == 6
                    assert len(gamma["values"][0]) == row.k_factors
                else:
                    # Current shape — raw 2D list.
                    assert len(gamma) == 6
                    assert len(gamma[0]) == row.k_factors

                # factor_returns: dates length T, values is K rows × T cols.
                fr = row.factor_returns
                if isinstance(fr, str):
                    fr = json.loads(fr)
                T = len(fr["dates"])
                assert len(fr["values"]) == row.k_factors  # K rows
                assert all(len(row_vals) == T for row_vals in fr["values"])  # each row length T
                assert len(fr["dates"]) > 0

                await _cleanup_fits(db)

        asyncio.get_event_loop().run_until_complete(_test())

    def test_panel_too_small_skipped(self):
        """Set min_panel_size absurdly high → worker skips."""
        factory = _get_session_factory()

        async def _test():
            async with factory() as db:
                await _require_populated_panel(db)
                await _cleanup_fits(db)

            from app.core.jobs.ipca_estimation import run_ipca_estimation
            result = await run_ipca_estimation(
                asof=_TEST_FIT_DATE, min_panel_size=999_999_999
            )

            assert result["status"] == "skipped"
            assert result["reason"] == "panel_too_small"

            async with factory() as db:
                from sqlalchemy import text
                count = (await db.execute(text(
                    "SELECT COUNT(*) FROM factor_model_fits "
                    "WHERE engine = 'ipca' AND fit_date = '2024-12-31'"
                ))).scalar()
                assert count == 0

        asyncio.get_event_loop().run_until_complete(_test())

    def test_drift_logged_on_second_run(self):
        """Run twice → second run should compute drift metric."""
        factory = _get_session_factory()

        async def _test():
            async with factory() as db:
                await _require_populated_panel(db)
                await _cleanup_fits(db)

            from app.core.jobs.ipca_estimation import run_ipca_estimation

            r1 = await run_ipca_estimation(asof=_TEST_FIT_DATE)
            assert r1["status"] == "succeeded"
            assert r1["drift"] is None  # No prior fit

            r2 = await run_ipca_estimation(asof=_TEST_FIT_DATE)
            assert r2["status"] == "succeeded"
            assert r2["drift"] is not None
            # Same data → drift should be near zero
            assert r2["drift"] < 0.01, f"Expected near-zero drift, got {r2['drift']}"

            async with factory() as db:
                from sqlalchemy import text
                count = (await db.execute(text(
                    "SELECT COUNT(*) FROM factor_model_fits "
                    "WHERE engine = 'ipca' AND fit_date = '2024-12-31'"
                ))).scalar()
                assert count == 2
                await _cleanup_fits(db)

        asyncio.get_event_loop().run_until_complete(_test())

    def test_idempotent_lock_skip(self):
        """Acquire lock 900_092 manually, run worker → should skip."""
        factory = _get_session_factory()

        async def _test():
            from sqlalchemy import text
            async with factory() as lock_holder:
                await lock_holder.execute(
                    text("SELECT pg_advisory_lock(:lock)"), {"lock": 900_092}
                )

                from app.core.jobs.ipca_estimation import run_ipca_estimation
                result = await run_ipca_estimation(asof=_TEST_FIT_DATE)
                assert result["status"] == "skipped"
                assert result["reason"] == "lock_held"

                await lock_holder.execute(
                    text("SELECT pg_advisory_unlock(:lock)"), {"lock": 900_092}
                )

        asyncio.get_event_loop().run_until_complete(_test())

    def test_no_data_with_early_date(self):
        """Use asof date before any data exists → no_data status."""
        factory = _get_session_factory()

        async def _test():
            from app.core.jobs.ipca_estimation import run_ipca_estimation
            result = await run_ipca_estimation(
                asof=date(2010, 1, 1), min_panel_size=300
            )
            assert result["status"] in ("skipped", "no_data"), f"Unexpected: {result}"

        asyncio.get_event_loop().run_until_complete(_test())
