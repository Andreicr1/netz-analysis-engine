"""Tests for the polymorphic NAV reader — nav_reader.py.

Verifies that the unified interface correctly dispatches to
nav_timeseries (funds) vs model_portfolio_nav (portfolios).
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.wealth.services.nav_reader import NavRow


class TestNavRow:
    """NavRow dataclass behaves correctly."""

    def test_frozen(self):
        row = NavRow(entity_id=uuid.uuid4(), nav_date=date(2026, 1, 1), nav=1000.0, daily_return=0.01)
        with pytest.raises(AttributeError):
            row.nav = 2000.0  # type: ignore[misc]

    def test_none_return(self):
        row = NavRow(entity_id=uuid.uuid4(), nav_date=date(2026, 1, 1), nav=1000.0, daily_return=None)
        assert row.daily_return is None


class TestIsModelPortfolio:
    """Test entity type detection."""

    @pytest.mark.asyncio
    async def test_portfolio_detected(self):
        from app.domains.wealth.services.nav_reader import is_model_portfolio

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = uuid.uuid4()
        db.execute.return_value = mock_result

        assert await is_model_portfolio(db, uuid.uuid4()) is True

    @pytest.mark.asyncio
    async def test_fund_detected(self):
        from app.domains.wealth.services.nav_reader import is_model_portfolio

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        assert await is_model_portfolio(db, uuid.uuid4()) is False


class TestFetchNavSeries:
    """Test the async fetch_nav_series dispatcher."""

    @pytest.mark.asyncio
    async def test_returns_nav_rows(self):
        """Verify NavRow construction from query results."""
        from app.domains.wealth.services.nav_reader import fetch_nav_series

        eid = uuid.uuid4()
        db = AsyncMock()

        # First call: is_model_portfolio check → None (it's a fund)
        # Second call: actual NAV query
        portfolio_check = MagicMock()
        portfolio_check.scalar_one_or_none.return_value = None

        nav_data = MagicMock()
        nav_data.all.return_value = [
            (eid, date(2026, 1, 2), 1010.0, 0.01),
            (eid, date(2026, 1, 3), 1005.0, -0.00495),
        ]

        db.execute = AsyncMock(side_effect=[portfolio_check, nav_data])

        rows = await fetch_nav_series(db, eid, date(2026, 1, 1), date(2026, 1, 5))
        assert len(rows) == 2
        assert all(isinstance(r, NavRow) for r in rows)
        assert rows[0].nav == pytest.approx(1010.0)
        assert rows[1].daily_return == pytest.approx(-0.00495)


class TestFetchReturnsOnly:
    """Test the returns-only convenience function."""

    @pytest.mark.asyncio
    async def test_filters_none_returns(self):
        from app.domains.wealth.services.nav_reader import fetch_returns_only

        eid = uuid.uuid4()
        db = AsyncMock()

        portfolio_check = MagicMock()
        portfolio_check.scalar_one_or_none.return_value = None

        nav_data = MagicMock()
        nav_data.all.return_value = [
            (eid, date(2026, 1, 1), 1000.0, None),  # Day 0, no return
            (eid, date(2026, 1, 2), 1010.0, 0.01),
            (eid, date(2026, 1, 3), 1005.0, -0.005),
        ]

        db.execute = AsyncMock(side_effect=[portfolio_check, nav_data])

        returns = await fetch_returns_only(db, eid)
        assert len(returns) == 2  # None filtered out
        assert returns[0] == pytest.approx(0.01)
        assert returns[1] == pytest.approx(-0.005)


class TestDuckTypingContract:
    """Verify nav_reader imports both models correctly."""

    def test_imports(self):
        from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav
        from app.domains.wealth.models.nav import NavTimeseries
        # Both tables expose the columns nav_reader expects
        mp_cols = {c.name for c in ModelPortfolioNav.__table__.columns}
        nt_cols = {c.name for c in NavTimeseries.__table__.columns}

        assert "nav_date" in mp_cols and "nav_date" in nt_cols
        assert "nav" in mp_cols and "nav" in nt_cols
        assert "daily_return" in mp_cols  # portfolio
        assert "return_1d" in nt_cols  # fund — different name, same semantics

    def test_navrow_compatible_with_factsheet(self):
        """NavRow fields map to FactSheetData.NavPoint."""
        from vertical_engines.wealth.fact_sheet.models import NavPoint

        row = NavRow(
            entity_id=uuid.uuid4(),
            nav_date=date(2026, 3, 26),
            nav=1234.56,
            daily_return=0.005,
        )
        # Can construct NavPoint from NavRow
        point = NavPoint(nav_date=row.nav_date, nav=row.nav)
        assert point.nav_date == row.nav_date
        assert point.nav == row.nav
