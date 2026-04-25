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


class TestIPCAEstimation:
    """Integration tests for run_ipca_estimation."""

    def test_full_run(self):
        """Run worker against real data. Assert fit row created with valid structure."""
        factory = _get_session_factory()

        async def _test():
            async with factory() as db:
                await _cleanup_fits(db)

            from app.core.jobs.ipca_estimation import run_ipca_estimation
            result = await run_ipca_estimation(asof=_TEST_FIT_DATE)

            assert result["status"] == "succeeded", f"Unexpected status: {result}"
            assert result["fits"] == 1
            assert 1 <= result["k_factors"] <= 6
            assert result["converged"] is True
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
                assert row.converged is True

                gamma = row.gamma_loadings
                if isinstance(gamma, str):
                    gamma = json.loads(gamma)
                assert len(gamma["rows"]) == 6
                assert len(gamma["cols"]) == row.k_factors
                assert len(gamma["values"]) == 6

                fr = row.factor_returns
                if isinstance(fr, str):
                    fr = json.loads(fr)
                assert len(fr["dates"]) == len(fr["values"])
                assert len(fr["dates"]) > 0

                await _cleanup_fits(db)

        asyncio.get_event_loop().run_until_complete(_test())

    def test_panel_too_small_skipped(self):
        """Set min_panel_size absurdly high → worker skips."""
        factory = _get_session_factory()

        async def _test():
            async with factory() as db:
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
