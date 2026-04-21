"""Regression: factor-analysis returns 200 with data_available=False on NAV gap.

Before the fix, insufficient NAV data raised HTTP 422, which the frontend
api-client threw as a ValidationError — blocking the Portfolio Workspace
from loading entirely.

After the fix the route returns 200 + FactorAnalysisResponse(data_available=False)
so the UI degrades gracefully (empty chart) instead of throwing.
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.routes.analytics import get_factor_analysis
from app.domains.wealth.schemas.analytics import FactorAnalysisResponse


def _make_user() -> MagicMock:
    u = MagicMock()
    u.name = "tester"
    return u


def _make_db_no_instruments() -> AsyncMock:
    """DB stub that returns no allocation blocks → fetch_returns_matrix raises ValueError."""
    db = AsyncMock()
    call_n = {"i": 0}

    async def _execute(stmt, params=None):
        call_n["i"] += 1
        n = call_n["i"]
        if n == 1:
            # _resolve_profile_weights → strategic_allocation rows
            sa_row = MagicMock()
            sa_row.block_id = "na_equity_large"
            sa_row.target_weight = 1.0
            r = MagicMock()
            r.scalars.return_value.all.return_value = [sa_row]
            return r
        # All subsequent DB calls return empty results (no instruments in org)
        empty = MagicMock()
        empty.all.return_value = []
        empty.scalars.return_value.all.return_value = []
        return empty

    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.mark.asyncio
async def test_factor_analysis_returns_200_when_nav_data_insufficient() -> None:
    """Route returns 200 + data_available=False instead of 422 on NAV gap.

    Regression: GET /analytics/factor-analysis/growth was returning 422 when
    the profile's blocks had no NAV data in instruments_org, causing the
    frontend to throw a ValidationError and crash the Portfolio Workspace.
    """
    with patch(
        "app.domains.wealth.routes.analytics.fetch_returns_matrix",
        side_effect=ValueError("No active funds found for the requested blocks"),
    ), patch(
        "app.domains.wealth.routes.analytics._resolve_profile_weights",
        return_value=(None, ["na_equity_large"], None, [1.0]),
    ), patch(
        "app.domains.wealth.routes.analytics._validate_profile",
        return_value=None,
    ):
        import numpy as np
        db = AsyncMock()

        result = await get_factor_analysis(
            profile="growth",
            n_factors=3,
            db=db,
            user=_make_user(),
        )

    assert isinstance(result, FactorAnalysisResponse)
    assert result.data_available is False
    assert result.profile == "growth"
    assert result.factor_contributions == []
    assert result.portfolio_factor_exposures == {}
    assert result.systematic_risk_pct == 0.0
    assert result.r_squared == 0.0
